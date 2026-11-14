import json

import frappe
from erpnext.accounts.doctype.pos_invoice.pos_invoice import make_sales_return
from erpnext.controllers.sales_and_purchase_return import (
	get_invoice_item_returned_qty,
	is_invoice_returnable,
)
from frappe import _
from frappe.utils import cint, flt, today

from awesome_dashboard.installer import get_dashboard_pos_profile, get_dashboard_user


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


def _dashboard_logger():
	return frappe.logger("dashboard_pos")


def _close_dashboard_opening_entry(ope_name: str, today_date: str | None = None):
	"""Close an open POS Opening Entry by creating and submitting a POS Closing Entry."""
	ope = frappe.get_doc("POS Opening Entry", ope_name)
	if ope.status != "Open":
		return
	close_date = today_date or today()
	closing = frappe.get_doc(
		{
			"doctype": "POS Closing Entry",
			"pos_opening_entry": ope.name,
			"company": ope.company,
			"pos_profile": ope.pos_profile,
			"user": ope.user,
			"period_start_date": close_date,
			"posting_date": close_date,
		}
	)
	closing.insert(ignore_permissions=True)
	closing.submit()
	_dashboard_logger().info(
		"Closed dashboard POS opening entry %s for profile %s", ope.name, ope.pos_profile
	)


def _ensure_dashboard_session(company: str) -> str:
	"""Ensure today's open dashboard POS session for the company and return its OPE name.

	Design: docs/superpowers/specs/2026-11-15-dashboard-pos-sessions-design.md.
	One user cannot hold two open POS sessions globally (check_user_already_assigned),
	so stale/other-company dashboard sessions are closed first. Let exceptions propagate
	so refund callers see the real failure.
	"""
	profile = get_dashboard_pos_profile(company)
	today_date = today()

	open_dashboard = frappe.get_all(
		"POS Opening Entry",
		filters={"pos_profile": ["like", "Dashboard POS - %"], "status": "Open", "docstatus": 1},
		fields=["name", "pos_profile", "period_start_date", "company"],
	)

	for entry in open_dashboard:
		period = str(entry.period_start_date) if entry.period_start_date else ""
		if entry.pos_profile == profile and period == today_date:
			return entry.name

	# Close stale same-company or any other open dashboard session (one user, one open session).
	for entry in open_dashboard:
		_close_dashboard_opening_entry(entry.name, today_date=today_date)

	dashboard_user = get_dashboard_user()
	profile_doc = frappe.get_doc("POS Profile", profile)
	mode_of_payment = "Cash"
	if profile_doc.get("payments"):
		mode_of_payment = profile_doc.payments[0].mode_of_payment or "Cash"

	ope = frappe.get_doc(
		{
			"doctype": "POS Opening Entry",
			"pos_profile": profile,
			"company": company,
			"user": dashboard_user,
			"period_start_date": today_date,
			"posting_date": today_date,
			"balance_details": [{"mode_of_payment": mode_of_payment, "opening_amount": 0}],
		}
	)
	ope.insert(ignore_permissions=True)
	ope.submit()
	frappe.db.commit()  # nosemgrep
	_dashboard_logger().info("Opened dashboard POS session %s for profile %s", ope.name, profile)
	return ope.name


def close_stale_dashboard_sessions():
	"""Daily scheduler: close stale dashboard POS sessions (period != today)."""
	today_date = today()
	closed = 0
	open_dashboard = frappe.get_all(
		"POS Opening Entry",
		filters={"pos_profile": ["like", "Dashboard POS - %"], "status": "Open", "docstatus": 1},
		fields=["name", "period_start_date"],
	)
	for entry in open_dashboard:
		period = str(entry.period_start_date) if entry.period_start_date else ""
		if period == today_date:
			continue
		try:
			_close_dashboard_opening_entry(entry.name, today_date=today_date)
			closed += 1
		except Exception:
			_dashboard_logger().error(
				"Failed to close stale dashboard POS opening entry %s: %s",
				entry.name,
				frappe.get_traceback(),
			)
	if closed:
		frappe.db.commit()  # nosemgrep
	_dashboard_logger().info("Closed %s stale dashboard POS session(s)", closed)


def _set_return_payments(target_doc, source_doc):
	"""Rebuild a return doc's payments from the returned rows' own totals, capped at tendered.

	ERPNext model (erpnext/controllers/sales_and_purchase_return.py:make_return_doc ~625,
	erpnext/accounts/doctype/pos_invoice/pos_invoice.py:validate_payment_amount ~561,
	validate_change_amount ~549, set_outstanding_amount ~584): a return's payment rows
	must each be <= 0 and their total must not exceed the return's grand_total in
	magnitude — equality is not required, and refunding more than tendered is impossible.
	``make_return_doc`` copies ``-source.paid_amount`` verbatim, which breaks invoices
	where paid != grand_total (change given, partial credit), so both refund paths
	re-derive payments here: the returned rows' recalculated value, capped at what the
	customer actually tendered, allocated across the source payment rows — each row
	capped at its own tendered share and rounded to currency precision, with the
	largest-tendered row absorbing the final remainder uncapped so the rows sum to
	exactly ``-refund_total``.
	"""
	precision = source_doc.precision("paid_amount")
	refund_total = flt(min(abs(flt(target_doc.grand_total)), abs(flt(source_doc.paid_amount))), precision)
	tendered = sum(abs(flt(p.amount)) for p in source_doc.payments)

	target_doc.set("payments", [])
	if not tendered or not refund_total:
		target_doc.paid_amount = 0
		target_doc.base_paid_amount = 0
		return

	# Absorber takes the final remainder uncapped so the rows sum exactly.
	absorber_idx = max(range(len(source_doc.payments)), key=lambda i: abs(flt(source_doc.payments[i].amount)))

	allocated = []
	allocated_sum = 0.0
	for i, payment in enumerate(source_doc.payments):
		if i == absorber_idx:
			continue
		share = min(abs(flt(payment.amount)) / tendered * refund_total, refund_total - allocated_sum)
		amount = min(flt(share, precision), flt(refund_total - allocated_sum, precision))
		if not amount:
			continue
		allocated.append((payment, amount))
		allocated_sum += amount

	absorber_amount = flt(refund_total - allocated_sum, precision)
	if absorber_amount:
		allocated.append((source_doc.payments[absorber_idx], absorber_amount))

	for payment, amount in allocated:
		target_doc.append(
			"payments",
			{
				"mode_of_payment": payment.mode_of_payment,
				"type": payment.type,
				"amount": -amount,
				"base_amount": flt(
					-amount * flt(source_doc.conversion_rate),
					source_doc.precision("base_paid_amount"),
				),
				"account": payment.account,
				"default": payment.default,
			},
		)

	target_doc.paid_amount = -refund_total
	target_doc.base_paid_amount = flt(
		-refund_total * flt(source_doc.conversion_rate),
		source_doc.precision("base_paid_amount"),
	)


@frappe.whitelist(allow_guest=False)
def process_pos_refund(invoice_name: str, return_items: str, company: str | None = None):
	"""Create and submit a return POS Invoice for the given items.

	Return creation is delegated to ERPNext's own ``make_sales_return`` — the
	same entry point the POS page calls — so item negation, taxes and return
	linkage track upstream. The item selection is applied to the draft it
	returns; payments are then re-derived from the returned rows' own
	recalculated totals, capped at what the customer tendered (see
	``_set_return_payments``) — never scaled off the source invoice's paid
	amount (which may include change given or partial credit).

	The return is routed onto the company's dashboard-managed POS profile and
	ensures today's dashboard POS session is open, so refunds work on any day
	regardless of shop till state. Design/spec:
	docs/superpowers/specs/2026-11-15-dashboard-pos-sessions-design.md.
	ERPNext validates the open session against the return doc's own pos_profile
	(`validate_pos_opening_entry`), so the profile switch happens before save.

	Over-quantity or otherwise invalid selections are rejected by ERPNext's own
	controller validation when the return is submitted — no duplicated
	returnable-qty checks here by design.

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
	selected_qty = {}
	for ri in return_items:
		item_name = ri.get("item_name")
		if not isinstance(item_name, str):
			frappe.throw(_("Each return item must have a valid item_name."))
		if not item_name:
			frappe.throw(_("Each return item must have an item_name."))
		if item_name in seen_item_names:
			frappe.throw(_("Duplicate item {0} in return items.").format(item_name))
		seen_item_names.add(item_name)
		qty = flt(ri.get("qty", 0))
		if qty <= 0:
			frappe.throw(_("Return quantity must be greater than zero for item {0}.").format(item_name))
		selected_qty[item_name] = qty

	source_doc = frappe.get_doc("POS Invoice", invoice_name)

	frappe.has_permission("POS Invoice", "read", doc=source_doc, throw=True)

	if company and source_doc.company != company:
		frappe.throw(_("Invoice {0} does not belong to company {1}.").format(source_doc.name, company))

	if source_doc.docstatus != 1:
		frappe.throw(_("Only submitted invoices can be returned."))

	if source_doc.is_return:
		frappe.throw(_("Cannot return a return invoice."))

	# Ensure today's dashboard-managed POS session and route the return onto it.
	# validate_pos_opening_entry checks the return doc's own pos_profile, so switch
	# pos_profile before save (see spec above).
	_ensure_dashboard_session(source_doc.company)
	dashboard_profile = get_dashboard_pos_profile(source_doc.company)

	# Draft the return via ERPNext's own POS entry point (the same call the POS page makes).
	target_doc = make_sales_return(invoice_name)
	if not target_doc:
		frappe.throw(_("Could not create return invoice."))

	frappe.has_permission("POS Invoice", "create", doc=target_doc, throw=True)

	try:
		# Keep only selected rows at the selected (negative) quantities.
		items_to_keep = []
		matched_names = set()
		for item in target_doc.items:
			source_item_name = getattr(item, "pos_invoice_item", None) or item.name
			if source_item_name in selected_qty:
				item.qty = -abs(selected_qty[source_item_name])
				item.amount = item.rate * item.qty if item.rate else 0
				items_to_keep.append(item)
				matched_names.add(source_item_name)

		if not items_to_keep:
			frappe.throw(_("No matching items found in return document."))

		# Every requested row must exist on the invoice — never silently under-refund.
		for requested_name in selected_qty:
			if requested_name not in matched_names:
				frappe.throw(_("Item {0} not found in invoice {1}.").format(requested_name, invoice_name))

		target_doc.items = items_to_keep
		target_doc.calculate_taxes_and_totals()
		target_doc.pos_profile = dashboard_profile

		_set_return_payments(target_doc, source_doc)

		target_doc.save()
		target_doc.submit()
	except Exception:
		# Never leave a stray draft behind: drop the return if it was saved as a draft.
		try:
			if target_doc and target_doc.docstatus == 0 and frappe.db.exists("POS Invoice", target_doc.name):
				frappe.delete_doc("POS Invoice", target_doc.name, ignore_permissions=False)
		except Exception as cleanup_err:
			frappe.log_error(
				title="POS refund cleanup failed",
				message=frappe.get_traceback() or str(cleanup_err),
			)
		raise

	return {"return_invoice": target_doc.name}


@frappe.whitelist(allow_guest=False)
def get_refunds_for_period(company: str, from_date: str, to_date: str, limit: int = 200):
	"""Get submitted POS return invoices for a company within a date range.

	Each refund dict carries an ``items`` list of what was returned:
	``[{"item_name": <POS Invoice Item name>, "qty": <abs qty>}]``
	(empty list if the return has no item rows).

	args:
	        company: Company name
	        from_date: Start posting date (YYYY-MM-DD)
	        to_date: End posting date (YYYY-MM-DD)
	        limit: Maximum number of refunds to fetch (default 200)
	"""
	if not company:
		frappe.throw(_("Company is required"))

	frappe.has_permission("POS Invoice", "read", throw=True)

	refunds = frappe.get_all(
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

	# One aggregate item fetch for all refunds (no N+1); return rows carry negative qty.
	items_by_parent: dict[str, list] = {}
	names = [r.name for r in refunds]
	if names:
		for row in frappe.get_all(
			"POS Invoice Item",
			filters={"parent": ["in", names]},
			fields=["parent", "item_name", "qty"],
		):
			items_by_parent.setdefault(row.parent, []).append(
				{"item_name": row.item_name, "qty": abs(row.qty)}
			)

	for r in refunds:
		r["items"] = items_by_parent.get(r.name, [])

	return refunds
