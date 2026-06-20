import frappe


def _validate_purchase_inputs(company, supplier, warehouse, items, invoice_number, amended_from=None):
	if not company:
		frappe.throw("Company is required")
	if not frappe.db.exists("Company", company):
		frappe.throw(f"Company '{company}' does not exist")

	if not supplier:
		frappe.throw("Supplier is required")
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Supplier '{supplier}' does not exist")

	if not warehouse:
		frappe.throw("Warehouse is required")
	if not frappe.db.exists("Warehouse", warehouse):
		frappe.throw(f"Warehouse '{warehouse}' does not exist")

	if not items or not isinstance(items, list) or len(items) == 0:
		frappe.throw("At least one item is required")

	for item in items:
		if not isinstance(item, dict):
			frappe.throw("Each item must be a dictionary with item_code, qty, and rate")
		if not item.get("item_code"):
			frappe.throw("item_code is required for each item")
		if not frappe.db.exists("Item", item["item_code"]):
			frappe.throw(f"Item '{item['item_code']}' does not exist")
		if not item.get("qty") or float(item["qty"] or 0) <= 0:
			frappe.throw(f"qty must be greater than 0 for item '{item['item_code']}'")
		if item.get("rate") is None or float(item["rate"] or 0) < 0:
			frappe.throw(f"rate must be 0 or greater for item '{item['item_code']}'")

	if invoice_number:
		existing = frappe.db.exists(
			"Purchase Invoice", {"bill_no": invoice_number, "supplier": supplier, "docstatus": 1}
		)
		if existing and existing != amended_from:
			frappe.throw(
				f"Purchase Invoice with invoice_number '{invoice_number}' already exists for this supplier"
			)


def _create_purchase_order(company, supplier, warehouse, items, invoice_date):
	po = frappe.get_doc({
		"doctype": "Purchase Order",
		"company": company,
		"supplier": supplier,
		"transaction_date": invoice_date,
		"schedule_date": invoice_date,
		"set_warehouse": warehouse,
		"items": [
			{
				"item_code": item["item_code"],
				"qty": float(item["qty"] or 0),
				"rate": float(item["rate"] or 0),
				"warehouse": warehouse,
			}
			for item in items
		],
	})
	po.insert()
	po.submit()
	return po


def _create_purchase_receipt(po, invoice_date):
	pr = frappe.get_doc({
		"doctype": "Purchase Receipt",
		"company": po.company,
		"supplier": po.supplier,
		"posting_date": invoice_date,
		"posting_time": "00:00:00",
		"set_warehouse": po.set_warehouse,
		"purchase_order": po.name,
		"items": [
			{
				"item_code": item.item_code,
				"qty": item.qty,
				"rate": item.rate,
				"warehouse": item.warehouse,
				"purchase_order": po.name,
				"purchase_order_item": item.name,
			}
			for item in po.items
		],
	})
	pr.insert()
	pr.submit()
	return pr


def _create_purchase_invoice(pr, invoice_number, invoice_date, amended_from=None):
	pi_data = {
		"doctype": "Purchase Invoice",
		"company": pr.company,
		"supplier": pr.supplier,
		"posting_date": invoice_date,
		"posting_time": "00:00:00",
		"bill_date": invoice_date,
		"purchase_receipt": pr.name,
		"update_stock": 0,
		"items": [
			{
				"item_code": item.item_code,
				"qty": item.qty,
				"rate": item.rate,
				"warehouse": item.warehouse,
				"purchase_order": item.purchase_order,
				"po_detail": item.purchase_order_item,
				"purchase_receipt": pr.name,
				"pr_detail": item.name,
			}
			for item in pr.items
		],
	}
	if invoice_number:
		pi_data["bill_no"] = invoice_number
	if amended_from:
		pi_data["amended_from"] = amended_from
	pi = frappe.get_doc(pi_data)
	pi.insert()
	pi.submit()
	return pi


def _create_payment_entry(pi, invoice_date, company):
	supplier_name = frappe.db.get_value("Supplier", pi.supplier, "supplier_name") or pi.supplier

	default_cash_account = frappe.db.get_value("Company", company, "default_cash_account")
	if not default_cash_account:
		default_cash_account = frappe.db.get_value(
			"Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name"
		)
	if not default_cash_account:
		frappe.throw(f"No default cash account found for company '{company}'")

	default_payable = frappe.db.get_value("Company", company, "default_payable_account")
	if not default_payable:
		default_payable = frappe.db.get_value(
			"Account", {"company": company, "account_type": "Payable", "is_group": 0}, "name"
		)
	if not default_payable:
		frappe.throw(f"No default payable account found for company '{company}'")

	if not frappe.db.exists("Mode of Payment", "Cash"):
		frappe.throw("Mode of Payment 'Cash' does not exist. Please create it first.")

	pe = frappe.get_doc({
		"doctype": "Payment Entry",
		"company": company,
		"payment_type": "Pay",
		"party_type": "Supplier",
		"party": pi.supplier,
		"party_name": supplier_name,
		"posting_date": invoice_date,
		"mode_of_payment": "Cash",
		"paid_from": default_cash_account,
		"paid_to": default_payable,
		"paid_amount": pi.grand_total,
		"received_amount": pi.grand_total,
		"reference_no": pi.bill_no or pi.name,
		"reference_date": pi.bill_date,
		"references": [
			{
				"reference_doctype": "Purchase Invoice",
				"reference_name": pi.name,
				"total_amount": pi.grand_total,
				"outstanding_amount": pi.outstanding_amount,
				"allocated_amount": pi.grand_total,
				"exchange_rate": 1,
			}
		],
	})
	pe.insert()
	pe.submit()
	return pe


def _update_item_prices(items):
	buying_pl = frappe.db.get_value("Buying Settings", None, "buying_price_list") or "Standard Buying"
	selling_pl = frappe.db.get_value("Selling Settings", None, "selling_price_list") or "Standard Selling"

	for item in items:
		buy_rate = float(item.get("rate") or 0)
		if buy_rate > 0:
			existing_buy = frappe.db.exists(
				"Item Price", {"item_code": item["item_code"], "price_list": buying_pl, "buying": 1}
			)
			if existing_buy:
				frappe.db.set_value("Item Price", existing_buy, "price_list_rate", buy_rate)
			else:
				frappe.get_doc({
					"doctype": "Item Price",
					"item_code": item["item_code"],
					"price_list": buying_pl,
					"buying": 1,
					"price_list_rate": buy_rate,
				}).insert()

		sell_rate = float(item.get("sell_rate") or 0)
		if sell_rate > 0:
			existing_sell = frappe.db.exists(
				"Item Price", {"item_code": item["item_code"], "price_list": selling_pl, "selling": 1}
			)
			if existing_sell:
				frappe.db.set_value("Item Price", existing_sell, "price_list_rate", sell_rate)
			else:
				frappe.get_doc({
					"doctype": "Item Price",
					"item_code": item["item_code"],
					"price_list": selling_pl,
					"selling": 1,
					"price_list_rate": sell_rate,
				}).insert()


@frappe.whitelist(allow_guest=False)
def create_full_purchase(company, supplier, warehouse, items, invoice_number=None, invoice_date=None):
	"""Create full purchase cycle: Purchase Order → Purchase Receipt → Purchase Invoice → Payment Entry.

	args:
	        company: Company name
	        supplier: Supplier name
	        warehouse: Receiving warehouse
	        items: List of {item_code, qty, rate} dicts
	        invoice_number: (optional) Supplier's invoice number
	        invoice_date: (optional) Invoice date (YYYY-MM-DD), defaults to today
	"""
	if not invoice_date:
		invoice_date = frappe.utils.nowdate()

	_validate_purchase_inputs(company, supplier, warehouse, items, invoice_number)

	try:
		po = _create_purchase_order(company, supplier, warehouse, items, invoice_date)
		pr = _create_purchase_receipt(po, invoice_date)
		pi = _create_purchase_invoice(pr, invoice_number, invoice_date)
		pe = _create_payment_entry(pi, invoice_date, company)

		for doc, doctype in [
			(pr, "Purchase Receipt"), (pi, "Purchase Invoice"), (pe, "Payment Entry")
		]:
			frappe.db.set_value(doctype, doc.name, "posting_date", invoice_date)

		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise

	_update_item_prices(items)

	return {
		"purchase_order": po.name,
		"purchase_receipt": pr.name,
		"purchase_invoice": pi.name,
		"payment_entry": pe.name,
	}


@frappe.whitelist(allow_guest=False)
def cancel_full_purchase(purchase_invoice):
	"""Cancel full purchase cycle: Payment Entry → Purchase Invoice → Purchase Receipt → Purchase Order.

	args:
	        purchase_invoice: Name of the Purchase Invoice to cancel
	"""
	if not purchase_invoice:
		frappe.throw("purchase_invoice is required")

	if not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw(f"Purchase Invoice '{purchase_invoice}' does not exist")

	docstatus = frappe.db.get_value("Purchase Invoice", purchase_invoice, "docstatus")
	if docstatus != 1:
		frappe.throw(f"Purchase Invoice '{purchase_invoice}' is not in Submitted state")

	pr_name = frappe.db.get_value(
		"Purchase Invoice Item", {"parent": purchase_invoice}, "purchase_receipt"
	)
	if not pr_name:
		frappe.throw("Could not find linked Purchase Receipt")

	po_name = frappe.db.get_value("Purchase Receipt Item", {"parent": pr_name}, "purchase_order")
	if not po_name:
		frappe.throw("Could not find linked Purchase Order")

	pe_name = frappe.db.get_value(
		"Payment Entry Reference",
		{"reference_doctype": "Purchase Invoice", "reference_name": purchase_invoice},
		"parent",
	)

	cancelled = []
	if pe_name:
		pe = frappe.get_doc("Payment Entry", pe_name)
		if pe.docstatus == 1:
			pe.cancel()
			cancelled.append(pe_name)

	pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
	pi.cancel()
	cancelled.append(purchase_invoice)

	pr = frappe.get_doc("Purchase Receipt", pr_name)
	pr.cancel()
	cancelled.append(pr_name)

	po = frappe.get_doc("Purchase Order", po_name)
	po.cancel()
	cancelled.append(po_name)

	frappe.db.commit()

	return {
		"cancelled": cancelled,
		"message": "All purchase documents cancelled successfully",
	}


@frappe.whitelist(allow_guest=False)
def amend_full_purchase(purchase_invoice, company, supplier, warehouse, items, invoice_number=None, invoice_date=None):
	"""Cancel old purchase chain and create a new one with updated details.

	args:
	        purchase_invoice: Name of the Purchase Invoice to amend
	        company: Company name
	        supplier: Supplier name
	        warehouse: Receiving warehouse
	        items: List of {item_code, qty, rate} dicts
	        invoice_number: (optional) Supplier's invoice number
	        invoice_date: (optional) Invoice date (YYYY-MM-DD), defaults to today
	"""
	if not purchase_invoice:
		frappe.throw("purchase_invoice is required")
	if not company:
		frappe.throw("company is required")
	if not supplier:
		frappe.throw("supplier is required")
	if not warehouse:
		frappe.throw("warehouse is required")
	if not items or not isinstance(items, list) or len(items) == 0:
		frappe.throw("At least one item is required")

	if not frappe.db.exists("Company", company):
		frappe.throw(f"Company '{company}' does not exist")
	if not frappe.db.exists("Supplier", supplier):
		frappe.throw(f"Supplier '{supplier}' does not exist")
	if not frappe.db.exists("Warehouse", warehouse):
		frappe.throw(f"Warehouse '{warehouse}' does not exist")

	for item in items:
		if not isinstance(item, dict):
			frappe.throw("Each item must be a dictionary with item_code, qty, rate, and sell_rate")
		if not item.get("item_code"):
			frappe.throw("item_code is required for each item")
		if not frappe.db.exists("Item", item["item_code"]):
			frappe.throw(f"Item '{item['item_code']}' does not exist")
		if not item.get("qty") or float(item["qty"] or 0) <= 0:
			frappe.throw(f"qty must be greater than 0 for item '{item['item_code']}'")
		if item.get("rate") is None or float(item["rate"] or 0) < 0:
			frappe.throw(f"rate must be 0 or greater for item '{item['item_code']}'")

	if invoice_number:
		existing = frappe.db.exists(
			"Purchase Invoice", {"bill_no": invoice_number, "supplier": supplier, "docstatus": 1}
		)
		if existing and existing != purchase_invoice:
			frappe.throw(
				f"Purchase Invoice with invoice_number '{invoice_number}' already exists for this supplier"
			)

	if not frappe.db.exists("Purchase Invoice", purchase_invoice):
		frappe.throw(f"Purchase Invoice '{purchase_invoice}' does not exist")

	docstatus = frappe.db.get_value("Purchase Invoice", purchase_invoice, "docstatus")
	if docstatus != 1:
		frappe.throw(f"Purchase Invoice '{purchase_invoice}' is not in Submitted state")

	if not invoice_date:
		invoice_date = frappe.utils.nowdate()

	try:
		pr_name = frappe.db.get_value(
			"Purchase Invoice Item", {"parent": purchase_invoice}, "purchase_receipt"
		)
		if not pr_name:
			frappe.throw("Could not find linked Purchase Receipt")

		po_name = frappe.db.get_value(
			"Purchase Receipt Item", {"parent": pr_name}, "purchase_order"
		)
		if not po_name:
			frappe.throw("Could not find linked Purchase Order")

		pe_name = frappe.db.get_value(
			"Payment Entry Reference",
			{"reference_doctype": "Purchase Invoice", "reference_name": purchase_invoice},
			"parent",
		)

		if pe_name:
			pe = frappe.get_doc("Payment Entry", pe_name)
			if pe.docstatus == 1:
				pe.cancel()

		pi = frappe.get_doc("Purchase Invoice", purchase_invoice)
		pi.cancel()

		pr = frappe.get_doc("Purchase Receipt", pr_name)
		pr.cancel()

		po = frappe.get_doc("Purchase Order", po_name)
		po.cancel()

		new_po = _create_purchase_order(company, supplier, warehouse, items, invoice_date)
		new_pr = _create_purchase_receipt(new_po, invoice_date)
		new_pi = _create_purchase_invoice(new_pr, invoice_number, invoice_date, purchase_invoice)
		new_pe = _create_payment_entry(new_pi, invoice_date, company)

		for doc, doctype in [
			(new_pr, "Purchase Receipt"), (new_pi, "Purchase Invoice"), (new_pe, "Payment Entry")
		]:
			frappe.db.set_value(doctype, doc.name, "posting_date", invoice_date)

		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise

	_update_item_prices(items)

	return {
		"purchase_order": new_po.name,
		"purchase_receipt": new_pr.name,
		"purchase_invoice": new_pi.name,
		"payment_entry": new_pe.name,
	}
