import frappe


@frappe.whitelist(allow_guest=False)
def get_stock_levels(warehouse, company, pack_size_map=None):
	"""Get current stock levels for a warehouse, with optional pack-size calculation.

	args:
	        warehouse: Warehouse name (warehouse_name field)
	        company: Company name
	        pack_size_map: (optional) Dict mapping item_name substrings to divisor integers.
	                      e.g. {"Pint": 24, "Quart": 12} computes pack_size = real_qty / divisor.
	"""
	if not warehouse or not company:
		frappe.throw("Both 'warehouse' and 'company' are required")

	wh_name = frappe.db.get_value(
		"Warehouse", {"warehouse_name": warehouse, "company": company}, "name"
	)
	if not wh_name:
		frappe.throw(f"Warehouse '{warehouse}' not found for company '{company}'")

	query = """
		SELECT
			bin.item_code,
			item.item_name,
			(bin.actual_qty - COALESCE(pos_reserved.reserved_qty, 0)) as real_qty,
			item.item_group,
			sp.price_list_rate as selling_price,
			bp.price_list_rate as buying_price
		FROM
			`tabBin` bin
		JOIN
			`tabItem` item
			ON bin.item_code = item.item_code
		LEFT JOIN (
			SELECT
				item_code,
				SUM(reserved_qty) as reserved_qty
			FROM (
				SELECT
					item_code,
					SUM(stock_qty) as reserved_qty
				FROM `tabPOS Invoice Item`
				WHERE warehouse = %s
				AND parent IN (
					SELECT name FROM `tabPOS Invoice`
					WHERE docstatus = 1
					AND (consolidated_invoice IS NULL OR consolidated_invoice = '')
					AND company = %s
				)
				GROUP BY item_code
				UNION ALL
				SELECT
					item_code,
					SUM(qty) as reserved_qty
				FROM `tabPacked Item`
				WHERE warehouse = %s
				AND parent IN (
					SELECT name FROM `tabPOS Invoice`
					WHERE docstatus = 1
					AND (consolidated_invoice IS NULL OR consolidated_invoice = '')
					AND company = %s
				)
				GROUP BY item_code
			) pos_items
			GROUP BY item_code
		) pos_reserved ON bin.item_code = pos_reserved.item_code
		LEFT JOIN (
			SELECT
				item_code,
				price_list_rate
			FROM `tabItem Price`
			WHERE price_list = 'Standard Buying'
		) bp ON bin.item_code = bp.item_code
		LEFT JOIN (
			SELECT
				item_code,
				price_list_rate
			FROM `tabItem Price`
			WHERE price_list = 'Standard Selling'
		) sp ON bin.item_code = sp.item_code
		WHERE
			bin.warehouse = %s
			AND bin.actual_qty > 0
		ORDER BY item_group ASC, item_name ASC
	"""

	data = frappe.db.sql(query, (wh_name, company, wh_name, company, wh_name), as_dict=True)

	if pack_size_map and isinstance(pack_size_map, dict):
		for entry in data:
			for key, divisor in pack_size_map.items():
				if key in entry.item_name:
					try:
						div = int(divisor)
						if div > 0:
							entry["pack_size"] = f"{round(entry.real_qty / div, 2)} crates"
					except (ValueError, ZeroDivisionError):
						pass
					break

	return data


@frappe.whitelist(allow_guest=False)
def get_average_stock_value(from_date, to_date, company, time_grouping):
	"""Get average stock value per time period using running balance.

	args:
	        from_date: Start date (YYYY-MM-DD)
	        to_date: End date (YYYY-MM-DD)
	        company: Company name
	        time_grouping: MySQL DATE_FORMAT string (e.g. '%%Y-%%m' for monthly)
	"""
	time_grouping = _sanitize_time_grouping(time_grouping)

	query = f"""
		SELECT
			grouping_name,
			AVG(current_asset_value) AS average_stock_value,
			MAX(closing_balance) AS closing_balance
		FROM (
			SELECT
				posting_date,
				current_asset_value,
				DATE_FORMAT(posting_date, '{time_grouping}') AS grouping_name,
				FIRST_VALUE(current_asset_value) OVER (
					PARTITION BY DATE_FORMAT(posting_date, '{time_grouping}')
					ORDER BY posting_date DESC, creation DESC
				) AS closing_balance
			FROM (
				SELECT
					posting_date,
					creation,
					SUM(stock_value_difference) OVER (
						PARTITION BY company
						ORDER BY posting_date, creation
						ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
					) AS current_asset_value
				FROM `tabStock Ledger Entry`
				WHERE
					company = %s
					AND is_cancelled = 0
					AND posting_date <= %s
			) AS BaseBalance
			WHERE
				posting_date >= %s
		) AS GroupedBalance
		GROUP BY
			grouping_name
		ORDER BY
			grouping_name
	"""

	return frappe.db.sql(query, (company, to_date, from_date), as_dict=True)


@frappe.whitelist(allow_guest=False)
def get_daily_stock_value(from_date, to_date, company):
	"""Get daily stock value with days-from-end calculation.

	args:
	        from_date: Start date (YYYY-MM-DD)
	        to_date: End date (YYYY-MM-DD)
	        company: Company name
	"""
	query = """
		SELECT
			posting_date,
			current_asset_value AS daily_stock_value,
			DATEDIFF(%s, posting_date) + 1 AS days_from_end
		FROM (
			SELECT
				posting_date,
				SUM(stock_value_difference) OVER (
					PARTITION BY company
					ORDER BY posting_date, creation
					ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
				) as current_asset_value,
				ROW_NUMBER() OVER (
					PARTITION BY posting_date
					ORDER BY creation DESC
				) as rn
			FROM `tabStock Ledger Entry`
			WHERE
				company = %s
				AND is_cancelled = 0
				AND posting_date <= %s
		) AS RunningBalance
		WHERE
			rn = 1
			AND posting_date >= %s
		ORDER BY
			posting_date
	"""

	return frappe.db.sql(query, (to_date, company, to_date, from_date), as_dict=True)


_TIME_GROUPINGS = frozenset({
	"%%Y-%%m-%%d", "%%Y-%%m", "%%Y-%%U", "%%Y",
	"%%Y-%%m-%%d %%H:%%i:%%s", "%%H:%%i:%%s",
})


def _sanitize_time_grouping(grouping):
	if grouping not in _TIME_GROUPINGS:
		frappe.throw(f"Invalid time_grouping: '{grouping}'. Allowed: {sorted(_TIME_GROUPINGS)}")
	return grouping
