import frappe


@frappe.whitelist(allow_guest=False)
def search_suppliers(company, query=""):
	"""Search suppliers by name.

	args:
	        company: Company name
	        query: (optional) Search term to filter supplier names
	"""
	if not company:
		frappe.throw("Company is required")

	filters = {"disabled": 0}
	if query:
		filters["supplier_name"] = ["like", f"%{query}%"]

	suppliers = frappe.get_all(
		"Supplier", filters=filters, fields=["name", "supplier_name"], limit=20, order_by="supplier_name"
	)

	return [{"name": s.name, "supplier_name": s.supplier_name} for s in suppliers]


@frappe.whitelist(allow_guest=False)
def search_warehouses(company):
	"""List all non-group warehouses for a company.

	args:
	        company: Company name
	"""
	if not company:
		frappe.throw("Company is required")

	warehouses = frappe.get_all(
		"Warehouse", filters={"company": company, "is_group": 0}, fields=["name"], order_by="name"
	)

	return [{"name": w.name} for w in warehouses]
