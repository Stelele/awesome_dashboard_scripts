import frappe


@frappe.whitelist(allow_guest=False)
def account_names(company, include_groups=False):
	"""Get expense and income account names for a company.

	args:
	        company: Company name
	        include_groups: If True, includes group accounts and returns is_group field.
	                       Defaults to False (leaf accounts only).
	"""
	if not company:
		frappe.throw("Company is required")

	expense_filters = {"company": company, "root_type": "Expense"}
	income_filters = {"company": company, "root_type": "Income"}
	fields = ["name", "account_name"]

	if include_groups:
		fields.append("is_group")
	else:
		expense_filters["is_group"] = 0
		income_filters["is_group"] = 0

	return {
		"expense": frappe.get_all("Account", filters=expense_filters, fields=fields),
		"income": frappe.get_all("Account", filters=income_filters, fields=fields),
	}


@frappe.whitelist(allow_guest=False)
def get_journal_entries(company, start_date, end_date):
	"""Get journal entries for a company within a date range.

	args:
	        company: Company name
	        start_date: Start date (YYYY-MM-DD)
	        end_date: End date (YYYY-MM-DD)
	"""
	if not company or not start_date or not end_date:
		frappe.throw("Missing required parameters: company, start_date, and end_date")

	query = """
		SELECT
			je.name,
			je.posting_date,
			je.docstatus,
			je.user_remark,
			jea.account as debit_account,
			jea.debit as total_debit
		FROM
			`tabJournal Entry` je
		INNER JOIN
			`tabJournal Entry Account` jea ON je.name = jea.parent
		WHERE
			je.company = %(company)s
			AND je.posting_date BETWEEN %(start_date)s AND %(end_date)s
			AND jea.debit > 0
			AND je.docstatus < 2
	"""

	return frappe.db.sql(query, {
		"company": company,
		"start_date": start_date,
		"end_date": end_date,
	}, as_dict=True)


@frappe.whitelist(allow_guest=False)
def amend_expense_journal_entry(journal_entry, amount, description, expense_account, income_account, posting_date, company):
	"""Cancel and recreate a journal entry with new values.

	args:
	        journal_entry: Name of the existing Journal Entry to amend
	        amount: New amount (must be > 0)
	        description: User remark / description
	        expense_account: Expense account (debit)
	        income_account: Income account (credit)
	        posting_date: Posting date (YYYY-MM-DD)
	        company: Company name
	"""
	amount = float(amount or 0)

	if not journal_entry:
		frappe.throw("journal_entry is required")
	if amount <= 0:
		frappe.throw("amount must be greater than 0")
	if not expense_account:
		frappe.throw("expense_account is required")
	if not income_account:
		frappe.throw("income_account is required")
	if not posting_date:
		frappe.throw("posting_date is required")
	if not company:
		frappe.throw("company is required")

	if not frappe.db.exists("Company", company):
		frappe.throw(f"Company '{company}' does not exist")
	if not frappe.db.exists("Account", expense_account):
		frappe.throw(f"Account '{expense_account}' does not exist")
	if not frappe.db.exists("Account", income_account):
		frappe.throw(f"Account '{income_account}' does not exist")
	if not frappe.db.exists("Journal Entry", journal_entry):
		frappe.throw(f"Journal Entry '{journal_entry}' does not exist")

	docstatus = frappe.db.get_value("Journal Entry", journal_entry, "docstatus")
	if docstatus != 1:
		frappe.throw(f"Journal Entry '{journal_entry}' is not in Submitted state")

	try:
		je = frappe.get_doc("Journal Entry", journal_entry)
		je.cancel()

		new_je = frappe.get_doc({
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": company,
			"posting_date": posting_date,
			"user_remark": description or "",
			"amended_from": journal_entry,
			"accounts": [
				{"account": expense_account, "debit_in_account_currency": amount},
				{"account": income_account, "credit_in_account_currency": amount},
			],
		})
		new_je.insert()
		new_je.submit()

		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise

	return {"journal_entry": new_je.name}
