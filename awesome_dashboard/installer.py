from __future__ import annotations

import frappe
from frappe import _

DASHBOARD_ROLE = "Awesome Dashboard User"

# Role-based read access the dashboard needs on core ERPNext doctypes.
#
# IMPORTANT: these are granted via frappe.permissions.add_permission /
# update_permission_property, NOT synced as `Custom DocPerm` fixtures. A
# Custom DocPerm on a doctype REPLACES the whole standard permission set for
# that doctype (frappe.model.meta.set_custom_permissions), so fixture-syncing
# one silently strips System Manager / Accounts User / etc. access. The
# add_permission path preserves standard perms by copying them into Custom
# DocPerm first.
DASHBOARD_PERMISSIONS = {
	"Account": {"read": 1},
	"Buying Settings": {"read": 1},
	"Company": {"read": 1},
	"Customer": {"read": 1},
	"Item": {"read": 1, "write": 1, "create": 1},
	"Item Group": {"read": 1},
	"Item Price": {"read": 1, "write": 1, "create": 1},
	"Journal Entry": {
		"read": 1,
		"write": 1,
		"create": 1,
		"delete": 1,
		"submit": 1,
		"cancel": 1,
		"amend": 1,
	},
	"Mode of Payment": {"read": 1},
	"Payment Entry": {
		"read": 1,
		"write": 1,
		"create": 1,
		"submit": 1,
		"cancel": 1,
		"amend": 1,
	},
	"POS Closing Entry": {"read": 1, "create": 1, "submit": 1},
	"POS Invoice": {"read": 1, "write": 1, "create": 1, "submit": 1},
	"POS Opening Entry": {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1},
	"POS Profile": {"read": 1},
	"Serial and Batch Bundle": {"read": 1, "write": 1, "create": 1, "submit": 1},
	"Purchase Invoice": {
		"read": 1,
		"write": 1,
		"create": 1,
		"submit": 1,
		"cancel": 1,
		"amend": 1,
	},
	"Purchase Order": {
		"read": 1,
		"write": 1,
		"create": 1,
		"submit": 1,
		"cancel": 1,
		"amend": 1,
	},
	"Purchase Receipt": {
		"read": 1,
		"write": 1,
		"create": 1,
		"submit": 1,
		"cancel": 1,
		"amend": 1,
	},
	"Selling Settings": {"read": 1},
	"Stock Reconciliation": {"read": 1, "write": 1, "create": 1, "submit": 1, "amend": 1},
	"Supplier": {"read": 1, "write": 1, "create": 1},
	"Warehouse": {"read": 1},
}


def after_install():
	"""Grant dashboard role permissions after the app is installed."""
	ensure_dashboard_permissions()


def after_migrate():
	"""Keep the dashboard role permissions in sync on every migrate.

	Idempotent; safe to run repeatedly. Standard permissions are preserved
	because add_permission copies them into Custom DocPerm before adding the
	new rule."""
	ensure_dashboard_permissions()
	seed_dashboard_pos_profiles()


def ensure_dashboard_permissions():
	"""Grant DASHBOARD_PERMISSIONS to DASHBOARD_ROLE without clobbering.

	Adds the role if missing (in case the Role fixture has not run yet), then
	grants each (doctype, ptype) pair. `add_permission` calls
	`setup_custom_perms`, which copies the standard permission set for the
	doctype into Custom DocPerm before the new rule is added, so existing
	roles keep their access."""
	from frappe.permissions import add_permission, update_permission_property

	if not frappe.db.exists("Role", DASHBOARD_ROLE):
		frappe.get_doc(
			{"doctype": "Role", "role_name": DASHBOARD_ROLE, "desk_access": 0, "is_custom": 1}
		).insert(ignore_permissions=True)

	for doctype, ptypes in DASHBOARD_PERMISSIONS.items():
		for ptype in ptypes:
			existing = frappe.db.get_value(
				"Custom DocPerm",
				{"parent": doctype, "role": DASHBOARD_ROLE, "permlevel": 0},
				"name",
			)
			if not existing:
				add_permission(doctype, DASHBOARD_ROLE, ptype=ptype)
				continue
			if not frappe.db.get_value("Custom DocPerm", existing, ptype):
				update_permission_property(doctype, DASHBOARD_ROLE, 0, ptype, 1)

	# Outside any request transaction (migrate hooks) — commit makes the grant durable immediately.
	frappe.db.commit()  # nosemgrep


def get_dashboard_user() -> str:
	"""Return the first enabled user holding the Awesome Dashboard User role."""
	users = frappe.get_all(
		"Has Role",
		filters={"role": DASHBOARD_ROLE, "parenttype": "User"},
		pluck="parent",
	)
	for user in users:
		if frappe.db.get_value("User", user, "enabled"):
			return user
	frappe.throw(_("No enabled user found with role {0}.").format(DASHBOARD_ROLE))


def _abbr(company: str) -> str:
	return frappe.get_cached_value("Company", company, "abbr")


def _dashboard_logger():
	return frappe.logger("dashboard_pos")


def get_dashboard_pos_profile(company: str) -> str:
	"""Return the dashboard POS profile for a company, creating it if missing.

	Idempotent. Uses ignore_permissions so it can be called from migrate/scheduler.
	Profile name: `Dashboard POS - {abbr}`. The profile's payment rows are not used
	for refund money (`_set_return_payments` rebuilds from the source invoice); we
	add Cash if available for a valid default payment configuration.
	"""
	if not company:
		frappe.throw(_("Company is required"))

	profile_name = f"Dashboard POS - {_abbr(company)}"
	if frappe.db.exists("POS Profile", profile_name):
		return profile_name

	warehouse = frappe.db.get_value("Warehouse", {"company": company, "warehouse_name": "Stores"})
	if not warehouse:
		warehouse = frappe.db.get_value("Company", company, "default_warehouse")

	write_off_account = None
	write_off_cost_center = None
	existing = frappe.get_all("POS Profile", filters={"company": company}, limit=1, pluck="name")
	if existing:
		write_off_account, write_off_cost_center = frappe.db.get_value(
			"POS Profile", existing[0], ["write_off_account", "write_off_cost_center"]
		)

	if not write_off_cost_center:
		write_off_cost_center = frappe.db.get_value("Company", company, "cost_center")
	if not write_off_cost_center:
		# Loud failure beats a guessed cost center: a wrong one mis-states
		# write-off accounting downstream.
		frappe.throw(
			_("Company {0} has no write-off cost center; set one before enabling dashboard refunds.").format(
				frappe.bold(company)
			)
		)
	if not write_off_account:
		write_off_account = frappe.db.get_value(
			"Account", {"company": company, "account_name": "Write Off"}, "name"
		)
	if not write_off_account:
		frappe.throw(
			_("Company {0} has no Write Off account; set one before enabling dashboard refunds.").format(
				frappe.bold(company)
			)
		)
	if not warehouse:
		frappe.throw(
			_(
				"Company {0} has no Stores warehouse or default warehouse; set one before enabling dashboard refunds."
			).format(frappe.bold(company))
		)
	if not frappe.db.exists("Mode of Payment", "Cash"):
		frappe.throw(
			_(
				"Mode of Payment 'Cash' does not exist; it is required to seed the dashboard POS profile."
			).format()
		)

	doc = frappe.get_doc(
		{
			"doctype": "POS Profile",
			"name": profile_name,
			"company": company,
			"warehouse": warehouse,
			"write_off_account": write_off_account,
			"write_off_cost_center": write_off_cost_center,
		}
	)

	if frappe.db.exists("Mode of Payment", "Cash"):
		doc.append("payments", {"mode_of_payment": "Cash", "default": 1})

	# Duplicate-insert race (two concurrent refunds seeding the same profile):
	# catch and re-fetch so the caller always gets a working profile name.
	try:
		doc.insert(ignore_permissions=True)
	except Exception as e:
		if frappe.db.exists("POS Profile", profile_name):
			return profile_name
		raise e
	_dashboard_logger().info("Created dashboard POS profile %s for company %s", profile_name, company)
	return profile_name


def seed_dashboard_pos_profiles():
	"""Seed dashboard POS profiles for all companies. Best-effort per company."""
	logger = _dashboard_logger()
	for company in frappe.get_all("Company", pluck="name"):
		try:
			get_dashboard_pos_profile(company)
		except Exception:
			logger.error(
				"Failed to seed dashboard POS profile for company %s: %s",
				company,
				frappe.get_traceback(),
			)
