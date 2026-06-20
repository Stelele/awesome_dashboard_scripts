import frappe

_TIME_GROUPINGS = frozenset({
	"%%Y-%%m-%%d", "%%Y-%%m", "%%Y-%%U", "%%Y",
	"%%Y-%%m-%%d %%H:%%i:%%s", "%%H:%%i:%%s",
})


def sanitize_time_grouping(grouping):
	if grouping not in _TIME_GROUPINGS:
		frappe.throw(f"Invalid time_grouping: '{grouping}'. Allowed: {sorted(_TIME_GROUPINGS)}")
	return grouping
