import frappe


@frappe.whitelist(allow_guest=False)
def create_item(company, item_name, item_group, buying_price=0, selling_price=0):
	"""Create an item with optional buying and selling prices.

	args:
	        company: Company name
	        item_name: Name and code for the new item
	        item_group: Item Group to assign (must exist)
	        buying_price: (optional) Buying price, defaults to 0
	        selling_price: (optional) Selling price, defaults to 0
	"""
	buying_price = float(buying_price or 0)
	selling_price = float(selling_price or 0)
	item_name = item_name.strip() if item_name else ""
	item_group = item_group.strip() if item_group else ""

	if not company:
		frappe.throw("Company is required")
	if not item_name:
		frappe.throw("Item name is required")
	if not item_group:
		frappe.throw("Item group is required")
	if not frappe.db.exists("Item Group", item_group):
		frappe.throw(f"Item group '{item_group}' does not exist")
	if frappe.db.exists("Item", item_name):
		frappe.throw(f"Item '{item_name}' already exists")

	try:
		item = frappe.get_doc({
			"doctype": "Item",
			"item_code": item_name,
			"item_name": item_name,
			"item_group": item_group,
			"stock_uom": "Nos",
			"is_stock_item": 1,
			"is_purchase_item": 1,
			"is_sales_item": 1,
			"include_item_in_manufacturing": 0,
		})
		item.insert(ignore_permissions=True)

		buying_pl = frappe.db.get_value("Buying Settings", None, "buying_price_list") or "Standard Buying"
		selling_pl = frappe.db.get_value("Selling Settings", None, "selling_price_list") or "Standard Selling"

		if buying_price > 0:
			buy_ip = frappe.get_doc({
				"doctype": "Item Price",
				"item_code": item_name,
				"price_list": buying_pl,
				"buying": 1,
				"price_list_rate": buying_price,
			})
			buy_ip.insert(ignore_permissions=True)

		if selling_price > 0:
			sell_ip = frappe.get_doc({
				"doctype": "Item Price",
				"item_code": item_name,
				"price_list": selling_pl,
				"selling": 1,
				"price_list_rate": selling_price,
			})
			sell_ip.insert(ignore_permissions=True)

		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise

	return {
		"item_code": item_name,
		"item_name": item_name,
		"last_purchase_rate": buying_price,
		"last_selling_rate": selling_price,
		"description": "",
	}


@frappe.whitelist(allow_guest=False)
def search_items(company, query=""):
	"""Search items by name with current buying and selling prices.

	args:
	        company: Company name
	        query: (optional) Search term to filter item names
	"""
	if not company:
		frappe.throw("Company is required")

	filters = {"disabled": 0}
	if query:
		filters["item_name"] = ["like", f"%{query}%"]

	items = frappe.get_all(
		"Item", filters=filters, fields=["item_code", "item_name"], limit=20, order_by="item_name"
	)

	buying_pl = frappe.db.get_value("Buying Settings", None, "buying_price_list") or "Standard Buying"
	selling_pl = frappe.db.get_value("Selling Settings", None, "selling_price_list") or "Standard Selling"

	result = []
	for item in items:
		buy_rate = float(
			frappe.db.get_value(
				"Item Price",
				{"item_code": item.item_code, "price_list": buying_pl, "buying": 1},
				"price_list_rate",
			)
			or 0
		)
		sell_rate = float(
			frappe.db.get_value(
				"Item Price",
				{"item_code": item.item_code, "price_list": selling_pl, "selling": 1},
				"price_list_rate",
			)
			or 0
		)
		result.append({
			"item_code": item.item_code,
			"item_name": item.item_name,
			"last_purchase_rate": buy_rate,
			"last_selling_rate": sell_rate,
			"description": "Buy: " + str(buy_rate) + " | Sell: " + str(sell_rate),
		})

	return result
