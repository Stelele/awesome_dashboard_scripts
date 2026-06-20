import frappe

from awesome_dashboard.api.stock import _sanitize_time_grouping


def _get_account_bounds(company, account_name):
	"""Get lft/rgt bounds for an account group by name."""
	result = frappe.db.get_value(
		"Account",
		{"company": company, "account_name": account_name, "is_group": 1},
		["lft", "rgt"],
		as_dict=False,
	)
	if result:
		return {"lft": result[0], "rgt": result[1]}
	return None


def _build_expense_account_conditions(company, params, conditions):
	"""Build expense account tree conditions for Direct + Indirect Expenses, excluding Stock Expenses."""
	indirect = _get_account_bounds(company, "Indirect Expenses")
	direct = _get_account_bounds(company, "Direct Expenses")
	stock = _get_account_bounds(company, "Stock Expenses")

	if not indirect and not direct:
		frappe.throw(
			f"Could not find 'Indirect Expenses' or 'Direct Expenses' roots for company {company}"
		)

	if indirect:
		conditions.append("(acc.lft BETWEEN %s AND %s)")
		params.extend([indirect["lft"], indirect["rgt"]])

	if direct:
		if stock:
			conditions.append(
				"(acc.lft BETWEEN %s AND %s AND NOT (acc.lft BETWEEN %s AND %s))"
			)
			params.extend([direct["lft"], direct["rgt"], stock["lft"], stock["rgt"]])
		else:
			conditions.append("(acc.lft BETWEEN %s AND %s)")
			params.extend([direct["lft"], direct["rgt"]])


@frappe.whitelist(allow_guest=False)
def grouped_sales_summary(from_date, to_date, company, time_grouping):
	"""Get sales grouped by time period.

	args:
	        from_date: Start date (YYYY-MM-DD)
	        to_date: End date (YYYY-MM-DD)
	        company: Company name
	        time_grouping: MySQL DATE_FORMAT string (e.g. '%%Y-%%m' for monthly)
	"""
	time_grouping = _sanitize_time_grouping(time_grouping)

	query = f"""
		SELECT
			DATE_FORMAT(posting_date, '{time_grouping}') AS grouping_name,
			SUM(total) AS total,
			COUNT(name) AS count
		FROM `tabPOS Invoice`
		WHERE
			status in ('Paid', 'Consolidated')
			AND company = %s
			AND posting_date BETWEEN %s AND %s
		GROUP BY DATE_FORMAT(posting_date, '{time_grouping}')
		ORDER BY grouping_name
	"""

	return frappe.db.sql(query, (company, from_date, to_date), as_dict=True)


@frappe.whitelist(allow_guest=False)
def grouped_expenses_summary(from_date, to_date, company, time_grouping):
	"""Get expenses (Direct + Indirect, excluding Stock) grouped by time period.

	args:
	        from_date: Start date (YYYY-MM-DD)
	        to_date: End date (YYYY-MM-DD)
	        company: Company name
	        time_grouping: MySQL DATE_FORMAT string (e.g. '%%Y-%%m' for monthly)
	"""
	time_grouping = _sanitize_time_grouping(time_grouping)

	if not from_date or not to_date or not company:
		frappe.throw("from_date, to_date and company are required")

	params = [company, from_date, to_date]
	conditions = []
	_build_expense_account_conditions(company, params, conditions)

	account_tree_condition = " OR ".join(conditions)

	query = f"""
		SELECT
			DATE_FORMAT(gle.posting_date, '{time_grouping}') AS grouping_name,
			SUM(gle.debit) - SUM(gle.credit) AS total,
			COUNT(gle.name) AS count
		FROM `tabGL Entry` gle
		INNER JOIN `tabAccount` acc
			ON acc.name = gle.account
		WHERE
			gle.company = %s
			AND gle.posting_date BETWEEN %s AND %s
			AND gle.is_cancelled = 0
			AND ({account_tree_condition})
		GROUP BY
			DATE_FORMAT(gle.posting_date, '{time_grouping}')
		ORDER BY
			grouping_name ASC
	"""

	return frappe.db.sql(query, tuple(params), as_dict=True)


@frappe.whitelist(allow_guest=False)
def dashboard_complete(from_date, to_date, prev_from_date, prev_to_date, company, warehouse=None):
	"""Get complete dashboard metrics: sales, purchases, expenses, profits, stock.

	args:
	        from_date: Current period start (YYYY-MM-DD)
	        to_date: Current period end (YYYY-MM-DD)
	        prev_from_date: Previous period start (YYYY-MM-DD)
	        prev_to_date: Previous period end (YYYY-MM-DD)
	        company: Company name
	        warehouse: (optional) Warehouse name (warehouse_name field) for stock metrics
	"""
	results = []

	current_sales = frappe.db.sql("""
		SELECT COALESCE(SUM(total), 0) as total, COALESCE(COUNT(*), 0) as count
		FROM `tabPOS Invoice`
		WHERE status IN ('Paid', 'Consolidated') AND posting_date BETWEEN %s AND %s AND company = %s
	""", (from_date, to_date, company), as_dict=True)[0]

	prev_sales = frappe.db.sql("""
		SELECT COALESCE(SUM(total), 0) as total, COALESCE(COUNT(*), 0) as count
		FROM `tabPOS Invoice`
		WHERE status IN ('Paid', 'Consolidated') AND posting_date BETWEEN %s AND %s AND company = %s
	""", (prev_from_date, prev_to_date, company), as_dict=True)[0]

	results.append({
		"metric_type": "sales_summary",
		"cur_total": current_sales.total,
		"cur_count": current_sales.count,
		"prev_total": prev_sales.total,
		"prev_count": prev_sales.count,
	})

	current_purchases = frappe.db.sql("""
		SELECT COALESCE(SUM(grand_total), 0) as total, COALESCE(COUNT(*), 0) as count
		FROM `tabPurchase Invoice`
		WHERE docstatus = 1 AND posting_date BETWEEN %s AND %s AND company = %s
	""", (from_date, to_date, company), as_dict=True)[0]

	prev_purchases = frappe.db.sql("""
		SELECT COALESCE(SUM(grand_total), 0) as total, COALESCE(COUNT(*), 0) as count
		FROM `tabPurchase Invoice`
		WHERE docstatus = 1 AND posting_date BETWEEN %s AND %s AND company = %s
	""", (prev_from_date, prev_to_date, company), as_dict=True)[0]

	results.append({
		"metric_type": "purchase_summary",
		"cur_total": current_purchases.total,
		"cur_count": current_purchases.count,
		"prev_total": prev_purchases.total,
		"prev_count": prev_purchases.count,
	})

	expense_params = [company, from_date, to_date]
	expense_conditions = []
	_build_expense_account_conditions(company, expense_params, expense_conditions)
	expense_condition = " OR ".join(expense_conditions)

	current_expenses = frappe.db.sql(f"""
		SELECT COALESCE(SUM(gle.debit) - SUM(gle.credit), 0) as total, COALESCE(COUNT(*), 0) as count
		FROM `tabGL Entry` gle
		INNER JOIN `tabAccount` acc ON acc.name = gle.account
		WHERE gle.company = %s AND gle.posting_date BETWEEN %s AND %s AND gle.is_cancelled = 0
		AND ({expense_condition})
	""", tuple(expense_params), as_dict=True)[0]

	prev_expense_params = [company, prev_from_date, prev_to_date, *expense_params[3:]]
	prev_expenses = frappe.db.sql(f"""
		SELECT COALESCE(SUM(gle.debit) - SUM(gle.credit), 0) as total, COALESCE(COUNT(*), 0) as count
		FROM `tabGL Entry` gle
		INNER JOIN `tabAccount` acc ON acc.name = gle.account
		WHERE gle.company = %s AND gle.posting_date BETWEEN %s AND %s AND gle.is_cancelled = 0
		AND ({expense_condition})
	""", tuple(prev_expense_params), as_dict=True)[0]

	results.append({
		"metric_type": "expense_summary",
		"cur_total": current_expenses.total,
		"cur_count": current_expenses.count,
		"prev_total": prev_expenses.total,
		"prev_count": prev_expenses.count,
	})

	cur_gross_profit = current_sales.total - current_purchases.total
	prev_gross_profit = prev_sales.total - prev_purchases.total
	cur_net_profit = cur_gross_profit - current_expenses.total
	prev_net_profit = prev_gross_profit - prev_expenses.total

	results.append({
		"metric_type": "gross_profit_summary",
		"cur_total": cur_gross_profit,
		"prev_total": prev_gross_profit,
	})
	results.append({
		"metric_type": "gross_margin_summary",
		"cur_total": (current_sales.total and (cur_gross_profit / current_sales.total * 100)) or 0,
		"prev_total": (prev_sales.total and (prev_gross_profit / prev_sales.total * 100)) or 0,
	})
	results.append({
		"metric_type": "net_profit_summary",
		"cur_total": cur_net_profit,
		"prev_total": prev_net_profit,
	})
	results.append({
		"metric_type": "net_margin_summary",
		"cur_total": (current_sales.total and (cur_net_profit / current_sales.total * 100)) or 0,
		"prev_total": (prev_sales.total and (prev_net_profit / prev_sales.total * 100)) or 0,
	})

	month_sales = frappe.db.sql("""
		SELECT DATE_FORMAT(posting_date, '%%Y-%%m') as grouping_name, SUM(total) as total, COUNT(*) as count
		FROM `tabPOS Invoice`
		WHERE status IN ('Paid', 'Consolidated') AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH) AND company = %s
		GROUP BY DATE_FORMAT(posting_date, '%%Y-%%m')
		ORDER BY grouping_name
	""", (company,), as_dict=True)

	for row in month_sales:
		results.append({
			"metric_type": "sales_by_month",
			"grouping_name": row.grouping_name,
			"total": row.total,
			"count": row.count,
		})

	category_sales = frappe.db.sql("""
		SELECT i.item_group, SUM(pii.amount) as total
		FROM `tabPOS Invoice` pi
		INNER JOIN `tabPOS Invoice Item` pii ON pii.parent = pi.name
		INNER JOIN `tabItem` i ON i.name = pii.item_code
		WHERE pi.status IN ('Paid', 'Consolidated') AND pi.posting_date BETWEEN %s AND %s AND pi.company = %s
		GROUP BY i.item_group
		ORDER BY total DESC
	""", (from_date, to_date, company), as_dict=True)

	for row in category_sales:
		results.append({
			"metric_type": "sales_by_category",
			"item_group": row.item_group,
			"total": row.total,
		})

	if warehouse:
		wh_name = frappe.db.get_value(
			"Warehouse", {"warehouse_name": warehouse, "company": company}, "name"
		)

		if wh_name:
			stock_groups = frappe.db.sql("""
				SELECT
					item.item_group,
					ROUND(SUM((bin.actual_qty - COALESCE(pos_reserved.reserved_qty, 0)) * COALESCE(bp.price_list_rate, 0)), 2) as total,
					ROUND(SUM((bin.actual_qty - COALESCE(pos_reserved.reserved_qty, 0)) * COALESCE(sp.price_list_rate, 0)), 2) as selling_value
				FROM `tabBin` bin
				JOIN `tabItem` item ON bin.item_code = item.item_code
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
					SELECT item_code, price_list_rate
					FROM `tabItem Price`
					WHERE price_list = 'Standard Buying'
				) bp ON bin.item_code = bp.item_code
				LEFT JOIN (
					SELECT item_code, price_list_rate
					FROM `tabItem Price`
					WHERE price_list = 'Standard Selling'
				) sp ON bin.item_code = sp.item_code
				WHERE bin.warehouse = %s AND bin.actual_qty > 0
				GROUP BY item.item_group
				ORDER BY total DESC
			""", (wh_name, company, wh_name, company, wh_name), as_dict=True)

			for row in stock_groups:
				results.append({
					"metric_type": "stock_by_group",
					"item_group": row.item_group,
					"total": row.total or 0,
					"selling_value": row.selling_value or 0,
				})

			stock_summary = frappe.db.sql("""
				SELECT
					ROUND(SUM((bin.actual_qty - COALESCE(pos_reserved.reserved_qty, 0)) * COALESCE(bp.price_list_rate, 0)), 2) as total_value,
					ROUND(SUM((bin.actual_qty - COALESCE(pos_reserved.reserved_qty, 0)) * COALESCE(sp.price_list_rate, 0)), 2) as selling_value
				FROM `tabBin` bin
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
					SELECT item_code, price_list_rate
					FROM `tabItem Price`
					WHERE price_list = 'Standard Buying'
				) bp ON bin.item_code = bp.item_code
				LEFT JOIN (
					SELECT item_code, price_list_rate
					FROM `tabItem Price`
					WHERE price_list = 'Standard Selling'
				) sp ON bin.item_code = sp.item_code
				WHERE bin.warehouse = %s AND bin.actual_qty > 0
			""", (wh_name, company, wh_name, company, wh_name), as_dict=True)[0]

			results.append({
				"metric_type": "stock_summary",
				"total_value": stock_summary.total_value or 0,
				"selling_value": stock_summary.selling_value or 0,
			})

	return results


@frappe.whitelist(allow_guest=False)
def dashboard_bar_chart(from_date, to_date, grouping, company):
	"""Get sales as bar chart data grouped by day/week/month/quarter.

	args:
	        from_date: Start date (YYYY-MM-DD)
	        to_date: End date (YYYY-MM-DD)
	        grouping: One of 'day', 'week', 'month', 'quarter'
	        company: Company name
	"""
	if not from_date or not to_date or not grouping or not company:
		frappe.throw("from_date, to_date, grouping, and company are required")

	format_map = {
		"day": "DATE(posting_date)",
		"week": "DATE(DATE_SUB(posting_date, INTERVAL WEEKDAY(posting_date) DAY))",
		"month": "CONCAT(YEAR(posting_date), '-', LPAD(MONTH(posting_date), 2, '0'))",
		"quarter": "CONCAT(YEAR(posting_date), '-Q', QUARTER(posting_date))",
	}

	sql_expr = format_map.get(grouping)
	if not sql_expr:
		frappe.throw(f"Invalid grouping '{grouping}'. Allowed: {list(format_map.keys())}")

	raw_rows = frappe.db.sql(f"""
		SELECT
			{sql_expr} as grouping_name,
			SUM(total) as total,
			COUNT(*) as count
		FROM `tabPOS Invoice`
		WHERE status IN ('Paid', 'Consolidated')
			AND posting_date BETWEEN %s AND %s
			AND company = %s
		GROUP BY {sql_expr}
		ORDER BY grouping_name
	""", (from_date, to_date, company), as_dict=True)

	labels = []
	data = []
	for row in raw_rows:
		labels.append(row.grouping_name)
		data.append(row.total or 0)

	return {
		"labels": labels,
		"datasets": [{"label": "Sales", "data": data}],
	}


@frappe.whitelist(allow_guest=False)
def dashboard_sales_aggregated(from_date, to_date, company):
	"""Get sales aggregated by posting date, item name and item group.

	args:
	        from_date: Start date (YYYY-MM-DD)
	        to_date: End date (YYYY-MM-DD)
	        company: Company name
	"""
	query = """
		SELECT
			parent.posting_date,
			child.item_name,
			child.item_group,
			SUM(child.qty) as qty,
			ROUND(SUM(child.amount), 2) as item_total_amount
		FROM `tabPOS Invoice` parent
		INNER JOIN `tabPOS Invoice Item` child ON child.parent = parent.name
		WHERE parent.status IN ('Paid', 'Consolidated')
		AND parent.company = %s
		AND parent.posting_date BETWEEN %s AND %s
		GROUP BY parent.posting_date, child.item_name, child.item_group
		ORDER BY parent.posting_date DESC, child.item_group ASC, child.item_name ASC
	"""

	return frappe.db.sql(query, (company, from_date, to_date), as_dict=True)


@frappe.whitelist(allow_guest=False)
def dashboard_expense_breakdown(from_date, to_date, company):
	"""Get expense breakdown by account for Direct + Indirect Expenses (excluding Stock).

	args:
	        from_date: Start date (YYYY-MM-DD)
	        to_date: End date (YYYY-MM-DD)
	        company: Company name
	"""
	params = [company, from_date, to_date]
	conditions = []
	_build_expense_account_conditions(company, params, conditions)

	account_tree_condition = " OR ".join(conditions)

	query = """
		SELECT
			acc.account_name AS expense_type,
			SUM(gle.debit) - SUM(gle.credit) AS total,
			COUNT(gle.name) AS count
		FROM `tabGL Entry` gle
		INNER JOIN `tabAccount` acc ON acc.name = gle.account
		WHERE gle.company = %s
		AND gle.posting_date BETWEEN %s AND %s
		AND gle.is_cancelled = 0
		AND (""" + account_tree_condition + """)
		GROUP BY gle.account
		ORDER BY total DESC
	"""

	return frappe.db.sql(query, tuple(params), as_dict=True)


@frappe.whitelist(allow_guest=False)
def dashboard_order_breakdown(from_date, to_date, company):
	"""Get purchase invoice breakdown by supplier.

	args:
	        from_date: Start date (YYYY-MM-DD)
	        to_date: End date (YYYY-MM-DD)
	        company: Company name
	"""
	query = """
		SELECT
			supplier AS description,
			SUM(grand_total) AS total,
			COUNT(name) AS count
		FROM `tabPurchase Invoice`
		WHERE docstatus = 1
		AND company = %s
		AND posting_date BETWEEN %s AND %s
		GROUP BY supplier
		ORDER BY total DESC
	"""

	return frappe.db.sql(query, (company, from_date, to_date), as_dict=True)


@frappe.whitelist(allow_guest=False)
def dashboard_payment_entries(from_date, to_date, company):
	"""Get expense journal entries and purchase invoices as payment entries.

	args:
	        from_date: Start date (YYYY-MM-DD)
	        to_date: End date (YYYY-MM-DD)
	        company: Company name
	"""
	query = """
		SELECT
			je.name AS id,
			je.posting_date AS date,
			CASE je.docstatus
				WHEN 0 THEN 'Draft'
				WHEN 1 THEN 'Submitted'
				WHEN 2 THEN 'Cancelled'
			END AS status,
			'Expense' AS type,
			jea.account AS account,
			COALESCE(je.user_remark, '') AS description,
			jea.debit AS amount
		FROM `tabJournal Entry` je
		INNER JOIN `tabJournal Entry Account` jea ON je.name = jea.parent
		WHERE je.posting_date BETWEEN %s AND %s
		AND je.company = %s AND jea.debit > 0

		UNION ALL

		SELECT
			name AS id,
			posting_date AS date,
			CASE docstatus
				WHEN 0 THEN 'Draft'
				WHEN 1 THEN 'Submitted'
				WHEN 2 THEN 'Cancelled'
			END AS status,
			'Order' AS type,
			'' AS account,
			COALESCE(supplier, '') AS description,
			grand_total AS amount
		FROM `tabPurchase Invoice`
		WHERE posting_date BETWEEN %s AND %s
		AND company = %s

		ORDER BY date DESC, id DESC
	"""

	return frappe.db.sql(query, (from_date, to_date, company, from_date, to_date, company), as_dict=True)
