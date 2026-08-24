from __future__ import annotations

import frappe

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

	frappe.db.commit()
