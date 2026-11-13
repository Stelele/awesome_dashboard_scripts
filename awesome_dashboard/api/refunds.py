import json

import frappe
from erpnext.controllers.sales_and_purchase_return import (
	get_invoice_item_returned_qty,
	is_invoice_returnable,
	make_return_doc,
)
from frappe import _
from frappe.utils import cint, flt


@frappe.whitelist(allow_guest=False)
def get_pos_invoices_for_refund(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	status: str | None = None,
	search_term: str | None = None,
	limit: int = 200,
):
	"""Get submitted POS invoices that are still returnable.

	args:
	        company: Company name
	        from_date: (optional) Start posting date (YYYY-MM-DD)
	        to_date: (optional) End posting date (YYYY-MM-DD)
	        status: (optional) Invoice status filter ("All" disables the filter)
	        search_term: (optional) Matches invoice name or customer name
	        limit: Maximum number of invoices to fetch (default 200)
	"""
	if not company:
		frappe.throw(_("Company is required"))

	frappe.has_permission("POS Invoice", "read", throw=True)

	filters = {"docstatus": 1, "company": company}

	if from_date and to_date:
		filters["posting_date"] = ["between", [from_date, to_date]]
	elif from_date:
		filters["posting_date"] = [">=", from_date]
	elif to_date:
		filters["posting_date"] = ["<=", to_date]

	if status and status != "All":
		filters["status"] = status

	or_filters = None
	if search_term:
		or_filters = {
			"name": ["like", f"%{search_term}%"],
			"customer_name": ["like", f"%{search_term}%"],
		}

	invoices = frappe.get_all(
		"POS Invoice",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"customer",
			"customer_name",
			"status",
			"grand_total",
			"currency",
			"posting_date",
			"posting_time",
			"paid_amount",
			"total_qty",
			"owner",
		],
		order_by="posting_date desc, posting_time desc",
		limit=cint(limit) or 200,
	)

	# Filter to only returnable invoices (excludes already-returned, drafts, etc.)
	returnable = []
	for inv in invoices:
		if is_invoice_returnable("POS Invoice", inv.name):
			returnable.append(inv)

	return returnable


@frappe.whitelist(allow_guest=False)
def get_invoice_detail_for_refund(invoice_name: str, company: str | None = None):
	"""Get a POS invoice's items with returnable quantities, plus taxes and payments.

	args:
	        invoice_name: Name of the POS Invoice
	        company: (optional) Company name; when given, the invoice must belong to it
	"""
	doc = frappe.get_doc("POS Invoice", invoice_name)

	frappe.has_permission("POS Invoice", "read", doc=doc, throw=True)

	if company and doc.company != company:
		frappe.throw(_("Invoice {0} does not belong to company {1}.").format(doc.name, company))

	items = []
	for item in doc.items:
		item_qty = abs(item.qty) if item.qty else 0
		returned = get_invoice_item_returned_qty("POS Invoice", invoice_name, doc.customer, item.name)
		returned_qty = abs(returned.qty) if returned and returned.qty else 0
		returnable_qty = item_qty - returned_qty

		items.append(
			{
				"name": item.name,
				"item_code": item.item_code,
				"item_name": item.item_name,
				"qty": item_qty,
				"returnable_qty": max(returnable_qty, 0),
				"uom": item.uom,
				"rate": item.rate,
				"amount": abs(item.amount) if item.amount else 0,
			}
		)

	taxes = []
	for tax in doc.taxes:
		taxes.append(
			{
				"description": tax.description,
				"tax_amount_after_discount_amount": abs(tax.tax_amount_after_discount_amount)
				if tax.tax_amount_after_discount_amount
				else 0,
			}
		)

	payments = []
	for payment in doc.get("payments", []):
		payments.append(
			{
				"mode_of_payment": payment.mode_of_payment,
				"amount": abs(payment.amount) if payment.amount else 0,
			}
		)

	return {
		"name": doc.name,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"status": doc.status,
		"posting_date": str(doc.posting_date),
		"posting_time": str(doc.posting_time) if doc.posting_time else "",
		"paid_amount": doc.paid_amount,
		"owner": doc.owner,
		"currency": doc.currency,
		"net_total": abs(doc.net_total) if doc.net_total else 0,
		"grand_total": abs(doc.grand_total) if doc.grand_total else 0,
		"discount_amount": abs(doc.discount_amount) if doc.discount_amount else 0,
		"additional_discount_percentage": doc.additional_discount_percentage,
		"total_qty": doc.total_qty,
		"items": items,
		"taxes": taxes,
		"payments": payments,
	}


@frappe.whitelist(allow_guest=False)
def process_pos_refund(invoice_name: str, return_items: str, company: str | None = None):
	"""Create and submit a return POS Invoice for the given items.

	args:
	        invoice_name: Name of the submitted POS Invoice to return against
	        return_items: JSON string list of {"item_name": <POS Invoice Item name>, "qty": <qty>}
	        company: (optional) Company name; when given, the invoice must belong to it
	"""
	try:
		return_items = json.loads(return_items)
	except (ValueError, TypeError):
		frappe.throw(_("Invalid return items payload."))

	if not return_items or not isinstance(return_items, list):
		frappe.throw(_("No items selected for return."))

	for ri in return_items:
		if not isinstance(ri, dict):
			frappe.throw(_("Each return item must be an object with item_name and qty."))

	seen_item_names = set()
	for ri in return_items:
		item_name = ri.get("item_name")
		if not isinstance(item_name, str):
			frappe.throw(_("Each return item must have a valid item_name."))
		if item_name in seen_item_names:
			frappe.throw(_("Duplicate item {0} in return items.").format(item_name))
		seen_item_names.add(item_name)

	source_doc = frappe.get_doc("POS Invoice", invoice_name)

	frappe.has_permission("POS Invoice", "read", doc=source_doc, throw=True)

	if company and source_doc.company != company:
		frappe.throw(_("Invoice {0} does not belong to company {1}.").format(source_doc.name, company))

	if source_doc.docstatus != 1:
		frappe.throw(_("Only submitted invoices can be returned."))

	if source_doc.is_return:
		frappe.throw(_("Cannot return a return invoice."))

	# Validate all items exist and quantities are within returnable limits
	source_items_by_name = {item.name: item for item in source_doc.items}
	validated_qty = {}
	for ri in return_items:
		item_name = ri.get("item_name")
		qty = flt(ri.get("qty", 0))
		if not item_name:
			frappe.throw(_("Each return item must have an item_name."))
		if qty <= 0:
			frappe.throw(_("Return quantity must be greater than zero for item {0}.").format(item_name))
		if item_name not in source_items_by_name:
			frappe.throw(_("Item {0} not found in invoice {1}.").format(item_name, invoice_name))
		source_item = source_items_by_name[item_name]
		item_qty = abs(source_item.qty) if source_item.qty else 0
		returned = get_invoice_item_returned_qty("POS Invoice", invoice_name, source_doc.customer, item_name)
		returned_qty = abs(returned.qty) if returned and returned.qty else 0
		max_returnable = item_qty - returned_qty
		if qty > max_returnable:
			frappe.throw(
				_("Return quantity {0} for item {1} exceeds maximum returnable quantity {2}.").format(
					qty, item_name, max_returnable
				)
			)
		validated_qty[item_name] = qty

	# Get all source item names for comparison
	all_source_item_names = [item.name for item in source_doc.items]
	return_item_names = [ri["item_name"] for ri in return_items]
	is_partial = len(return_item_names) < len(all_source_item_names) or any(
		abs(validated_qty[name] - abs(source_items_by_name[name].qty or 0)) > 0.001
		for name in return_item_names
	)

	# Create the return document via ERPNext's standard mechanism
	target_doc = make_return_doc("POS Invoice", invoice_name, target_doc=None)
	if not target_doc:
		frappe.throw(_("Could not create return invoice."))

	frappe.has_permission("POS Invoice", "create", doc=target_doc, throw=True)

	if is_partial:
		# Remove items not in return_items and adjust quantities
		items_to_keep = []
		for item in target_doc.items:
			source_item_name = getattr(item, "pos_invoice_item", None) or item.name
			match = next((ri for ri in return_items if ri["item_name"] == source_item_name), None)
			if match:
				item.qty = -abs(match["qty"])
				item.amount = item.rate * item.qty if item.rate else 0
				items_to_keep.append(item)

		if not items_to_keep:
			frappe.throw(_("No matching items found in return document."))

		target_doc.items = items_to_keep
		target_doc.calculate_taxes_and_totals()

		# Adjust payments proportionally for partial return
		original_total = abs(source_doc.grand_total) or 0
		if original_total == 0:
			frappe.throw(_("Cannot partially refund an invoice with a zero grand total."))
		returned_total = abs(target_doc.grand_total)
		proportion = returned_total / original_total

		target_doc.set("payments", [])
		for payment in source_doc.payments:
			adjusted_amount = -1 * flt(payment.amount) * proportion
			if adjusted_amount != 0:
				target_doc.append(
					"payments",
					{
						"mode_of_payment": payment.mode_of_payment,
						"amount": adjusted_amount,
						"account": payment.account,
						"type": payment.type,
						"default": payment.default,
					},
				)

		target_doc.paid_amount = sum(flt(p.amount) for p in target_doc.payments)

	target_doc.save()
	target_doc.submit()

	return {"return_invoice": target_doc.name}


@frappe.whitelist(allow_guest=False)
def get_refunds_for_period(company: str, from_date: str, to_date: str, limit: int = 200):
	"""Get submitted POS return invoices for a company within a date range.

	args:
	        company: Company name
	        from_date: Start posting date (YYYY-MM-DD)
	        to_date: End posting date (YYYY-MM-DD)
	        limit: Maximum number of refunds to fetch (default 200)
	"""
	if not company:
		frappe.throw(_("Company is required"))

	frappe.has_permission("POS Invoice", "read", throw=True)

	return frappe.get_all(
		"POS Invoice",
		filters={
			"docstatus": 1,
			"is_return": 1,
			"company": company,
			"posting_date": ["between", [from_date, to_date]],
		},
		fields=[
			"name",
			"customer",
			"customer_name",
			"return_against",
			"grand_total",
			"currency",
			"posting_date",
			"posting_time",
			"owner",
		],
		order_by="posting_date desc, posting_time desc",
		limit=cint(limit) or 200,
	)
