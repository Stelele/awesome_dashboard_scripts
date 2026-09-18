# Awesome Dashboard — Developer Guide

## Architecture Overview

The **awesome_dashboard** app is a Frappe/ERPNext application that provides a unified dashboard and full purchase cycle automation. It follows the Frappe app architecture with a clear separation between:

### Layers

| Layer | Location | Description |
|-------|----------|-------------|
| **Hooks** | `awesome_dashboard/hooks.py` | App metadata, fixtures, `after_install`, `after_migrate` hooks |
| **Installer** | `awesome_dashboard/installer.py` | Permission management, role creation, `ensure_dashboard_permissions()` |
| **API** | `awesome_dashboard/api/` | Whitelisted methods exposed as `/api/method/awesome_dashboard.api.<module>.<method>` |
| **Utils** | `awesome_dashboard/api/_utils.py` | Shared utilities (time grouping sanitization) |
| **Fixtures** | `awesome_dashboard/fixtures/role.json` | Role fixture for "Awesome Dashboard User" |
| **Patches** | `awesome_dashboard/patches/` | Database schema patches (currently empty) |

### Data Flow

1. **Installation**: `bench get-app <url> --branch version-16` + `bench --site <site> install-app awesome_dashboard`
2. **Post-Install**: `after_install` hook runs `ensure_dashboard_permissions()`, which:
   - Creates the "Awesome Dashboard User" role if missing
   - Grants read/write/create permissions on 16 core ERPNext doctypes
   - Is idempotent — safe to run repeatedly
3. **On Migrate**: `after_migrate` hook runs `ensure_dashboard_permissions()` to keep permissions in sync
4. **API Calls**: All endpoints are `@frappe.whitelist(allow_guest=False)`, authenticated via Frappe's standard session/auth

### Key APIs

The app exposes **21 whitelisted methods** across 6 modules:

- **dashboard** (8 methods): Metrics, charts, breakdowns
- **finance** (3 methods): Accounts, journal entries, journal entry amendment
- **item** (2 methods): Item creation and search
- **lookup** (2 methods): Supplier and warehouse lookup
- **purchase** (3 methods): Full purchase cycle, amend, cancel
- **stock** (3 methods): Stock levels, average value, daily value

All endpoints are at `/api/method/awesome_dashboard.api.<module>.<method>` and require a valid Frappe session (no guest access).

---

## Hooks

### `after_install()`

**Location**: `awesome_dashboard/installer.py:72`

```python
def after_install():
    """Grant dashboard role permissions after the app is installed."""
    ensure_dashboard_permissions()
```

- Runs automatically after `bench --site <site> install-app awesome_dashboard`
- Calls `ensure_dashboard_permissions()` to set up role-based access

### `after_migrate()`

**Location**: `awesome_dashboard/installer.py:77`

```python
def after_migrate():
    """Keep the dashboard role permissions in sync on every migrate."""
    ensure_dashboard_permissions()
```

- Runs on every `bench migrate`
- Idempotent — safe to run repeatedly
- Preserves standard system permissions (System Manager, Accounts User, etc.) because `frappe.permissions.add_permission` copies standard perms into Custom DocPerm before adding the new rule

### `ensure_dashboard_permissions()`

**Location**: `awesome_dashboard/installer.py:86`

```python
def ensure_dashboard_permissions():
    """Grant DASHBOARD_PERMISSIONS to DASHBOARD_ROLE without clobbering."""
```

**Logic**:
1. If the "Awesome Dashboard User" Role doesn't exist, create it (desk_access=0, is_custom=1)
2. For each `(doctype, ptype)` in `DASHBOARD_PERMISSIONS`:
   - Check if a `Custom DocPerm` already exists for that doctype + role + permlevel=0
   - If not, call `add_permission(doctype, role, ptype=ptype)` — this copies standard perms into Custom DocPerm first
   - If it exists but is missing a permission type, call `update_permission_property(doctype, role, 0, ptype, 1)`
3. Commit all changes at once

**`DASHBOARD_PERMISSIONS`** (defined at module level in `installer.py`):

Grants the following access to the "Awesome Dashboard User" role on core ERPNext doctypes:

| Doctype | Read | Write | Create | Delete | Submit | Cancel | Amend |
|---------|------|-------|--------|--------|--------|--------|-------|
| Account | ✓ | | | | | | |
| Buying Settings | ✓ | | | | | | |
| Company | ✓ | | | | | | |
| Item | ✓ | ✓ | ✓ | | | | |
| Item Group | ✓ | | | | | | |
| Item Price | ✓ | ✓ | ✓ | | | | |
| Journal Entry | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Mode of Payment | ✓ | | | | | | |
| Payment Entry | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ |
| Purchase Invoice | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ |
| Purchase Order | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ |
| Purchase Receipt | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ |
| Selling Settings | ✓ | | | | | | |
| Stock Reconciliation | ✓ | ✓ | ✓ | | ✓ | | ✓ |
| Supplier | ✓ | ✓ | ✓ | | | | |
| Warehouse | ✓ | | | | | | |

---

## Whitelisted API Endpoints

All endpoints are verified and match the actual Python module paths. Format: `GET/POST /api/method/awesome_dashboard.api.<module>.<method>`

### `awesome_dashboard.api.dashboard`

| Method | Args | Description |
|--------|------|-------------|
| `dashboard_complete` | `from_date, to_date, prev_from_date, prev_to_date, company, warehouse=None` | Complete dashboard metrics: sales, purchases, expenses, profits, stock |
| `dashboard_bar_chart` | `from_date, to_date, grouping, company` | Sales as bar chart grouped by day/week/month/quarter |
| `dashboard_sales_aggregated` | `from_date, to_date, company` | Sales aggregated by posting date, item name, item group |
| `dashboard_expense_breakdown` | `from_date, to_date, company` | Expense breakdown by account (Direct + Indirect, excl. Stock) |
| `dashboard_order_breakdown` | `from_date, to_date, company` | Purchase invoice breakdown by supplier |
| `dashboard_payment_entries` | `from_date, to_date, company` | Journal entries and purchase invoices as payment entries |
| `grouped_sales_summary` | `from_date, to_date, company, time_grouping` | Sales grouped by time period (MySQL DATE_FORMAT) |
| `grouped_expenses_summary` | `from_date, to_date, company, time_grouping` | Expenses grouped by time period |

### `awesome_dashboard.api.finance`

| Method | Args | Description |
|--------|------|-------------|
| `account_names` | `company, include_groups=False` | Expense and income account names for a company |
| `get_journal_entries` | `company, start_date, end_date` | Journal entries within a date range |
| `amend_expense_journal_entry` | `journal_entry, amount, description, expense_account, income_account, posting_date, company` | Cancel and recreate a journal entry with new values |

### `awesome_dashboard.api.item`

| Method | Args | Description |
|--------|------|-------------|
| `create_item` | `company, item_name, item_group, buying_price=0, selling_price=0` | Create an item with optional buying/selling prices |
| `search_items` | `company, query=""` | Search items by name with current buying/selling prices |

### `awesome_dashboard.api.lookup`

| Method | Args | Description |
|--------|------|-------------|
| `search_suppliers` | `company, query=""` | Search suppliers by name |
| `search_warehouses` | `company` | List all non-group warehouses for a company |

### `awesome_dashboard.api.purchase`

| Method | Args | Description |
|--------|------|-------------|
| `create_full_purchase` | `company, supplier, warehouse, items, invoice_number=None, invoice_date=None` | Full purchase cycle: PO → PR → PI → PE |
| `cancel_full_purchase` | `purchase_invoice` | Cancel full purchase cycle: PE → PI → PR → PO |
| `amend_full_purchase` | `purchase_invoice, company, supplier, warehouse, items, invoice_number=None, invoice_date=None` | Cancel old chain, create new one with updated details |

### `awesome_dashboard.api.stock`

| Method | Args | Description |
|--------|------|-------------|
| `get_stock_levels` | `warehouse, company, pack_size_map=None` | Current stock levels for a warehouse |
| `get_average_stock_value` | `from_date, to_date, company, time_grouping` | Average stock value per time period |
| `get_daily_stock_value` | `from_date, to_date, company` | Daily stock value with days-from-end calculation |

---

## Installer Behavior

The installer (`installer.py`) is the core behavioral layer of the app. Key points:

### `after_install()`

- Automatically executed after `bench --site <site> install-app awesome_dashboard`
- Calls `ensure_dashboard_permissions()` to set up the "Awesome Dashboard User" role with all required doctype permissions

### `after_migrate()`

- Automatically executed on every `bench migrate`
- Calls `ensure_dashboard_permissions()` to keep permissions in sync
- **Idempotent**: Safe to run multiple times; will not remove existing standard permissions because `add_permission` uses `setup_custom_perms` which copies standard perms into Custom DocPerm before adding the new rule

### Permission Preservation Strategy

The app uses `frappe.permissions.add_permission()` rather than Custom DocPerm fixtures because:

- **Fixtures approach**: `frappe.model.meta.set_custom_permissions()` replaces the *entire* standard permission set for a doctype, which would silently strip System Manager, Accounts User, and other standard roles access.
- **`add_permission` approach**: Copies the standard permission set for the doctype into Custom DocPerm first, then adds the new rule. This preserves all existing roles' access while adding the dashboard role's permissions.

### Running Manually

```bash
# Refresh permissions after any role/perm changes
bench --site <site> execute "awesome_dashboard.installer.ensure_dashboard_permissions()"
```

---

## Development Setup

### Prerequisites

- Frappe v16 (managed by bench)
- Python 3.11+ (Frappe v16 runtime; pyproject.toml declares requires-python >=3.14 — verify against your bench before use)
- Node.js/npm (for frontend assets)
- `pre-commit` (for code quality checks)

### Installing the App for Development

```bash
# 1. In your bench directory (branch is selected at get-app time)
bench get-app https://github.com/Stelele/awesome_dashboard_scripts --branch version-16
mv apps/awesome_dashboard_scripts apps/awesome_dashboard

# 2. Install prerequisites first (ERPNext is required — see hooks.py:18 required_apps)
bench --site <site_name> install-app erpnext

# 3. Install on a site
bench --site <site_name> install-app awesome_dashboard

# 4. Run migrations / set up permissions
bench --site <site> migrate

# 5. Ensure dashboard permissions are granted
bench --site <site> execute "awesome_dashboard.installer.ensure_dashboard_permissions()"
```

### Local Development Workflow

```bash
# 1. Make changes to Python files
# 2. Run linting (pre-commit is configured)
cd apps/awesome_dashboard
pre-commit run --all-files

# 3. If API methods changed, verify they're exported in api/__init__.py
#    and that the function signatures match the docs/DEVELOPER.md

# 4. Test manually on the site
#    - Create items, run purchase cycles
#    - Check dashboard metrics
#    - Verify stock level reports

# 5. Commit and push
git add .
git commit -m "fix: something descriptive"
git push origin <branch>
```

### Running Tests

```bash
# If test files exist
bench --site <site> run-tests --app awesome_dashboard

# Or run specific test modules
pytest path/to/tests -v
```

### Code Formatting

This app uses **pre-commit** with the following tools (configured in `.pre-commit-config.yaml` and `pyproject.toml`):

- **ruff** — Python linting and formatting
- **eslint** — JavaScript linting
- **prettier** — JavaScript formatting
- **pyupgrade** — Python version upgrades (automatic)

Pre-commit config (`.pre-commit-config.yaml`):

```yaml
repos:
  - repo: local
    hooks:
      - id: ruff
      - id: eslint
      - id: prettier
      - id: pyupgrade
```

### Adding New API Endpoints

1. Add the function to the appropriate `awesome_dashboard/api/<module>.py` file
2. Mark it with `@frappe.whitelist(allow_guest=False)`
3. Add the import and export in `awesome_dashboard/api/__init__.py`
4. Document the method in `docs/DEVELOPER.md` with:
   - Full function signature
   - Arg descriptions (type and requirement)
   - Return value description
   - Verified URL: `/api/method/awesome_dashboard.api.<module>.<method>`
5. Add a test fixture or integration test if applicable

### Adding New Hooks

1. Edit `awesome_dashboard/hooks.py` to add the hook reference
2. Implement the corresponding function in the appropriate module
3. Ensure the hook function follows Frappe's signature conventions
4. Document in `docs/DEVELOPER.md`

### Database Patches

Patches go in `awesome_dashboard/patches/` and are declared in `patches.txt`. The current `patches.txt` has two sections:

- `[pre_model_sync]` — executed before doctypes are migrated
- `[post_model_sync]` — executed after doctypes are migrated

To add a patch:

```python
# awesome_dashboard/patches/auto_2024xxxx_some_name.py
def patch(app_name):
    # ... database schema or data changes
    pass
```

Register in `patches.txt`:

```
[pre_model_sync]
# Description of pre-sync patch

[post_model_sync]
# Description of post-sync patch
```

---

## Project Structure

```
awesome_dashboard/
├── .github/              # CI/CD workflows
├── license.txt           # MIT License
├── pyproject.toml        # Project config (ruff, bench deps)
├── README.md             # User-facing overview + installation
├── awesome_dashboard/    # App package
│   ├── __init__.py       # App namespace
│   ├── api/              # Whitelisted API methods
│   │   ├── __init__.py   # Exports all API functions
│   │   ├── dashboard.py  # Dashboard metrics & charts
│   │   ├── finance.py    # Accounts, journal entries
│   │   ├── item.py       # Item creation & search
│   │   ├── lookup.py     # Suppliers & warehouses
│   │   ├── purchase.py   # Full purchase cycle
│   │   └── stock.py      # Stock levels & valuation
│   │   └── _utils.py     # Shared utilities
│   ├── config/           # App configuration (empty currently)
│   ├── fixtures/         # DocType fixtures (role.json)
│   ├── hooks.py          # App metadata, hooks, fixtures
│   ├── installer.py      # Permission management, after_install/after_migrate
│   ├── modules.txt       # App module definition
├── public/               # Static assets (currently .gitkeep only)
├── templates/            # Jinja templates (pages, etc.)
└── .gitignore
```

---

## Verified API URL Format

All endpoints follow this exact pattern:

```
/api/method/awesome_dashboard.api.<module>.<method>
```

Where `awesome_dashboard.api` is the Python package path and `<module>` is one of: `dashboard`, `finance`, `item`, `lookup`, `purchase`, `stock`

And `<method>` is the function name as defined in the respective `.py` file.

**Examples (all verified against actual code)**:

- `GET /api/method/awesome_dashboard.api.dashboard.dashboard_complete`
- `GET /api/method/awesome_dashboard.api.purchase.create_full_purchase`
- `GET /api/method/awesome_dashboard.api.item.create_item`
- `GET /api/method/awesome_dashboard.api.stock.get_stock_levels`

All endpoints return `allow_guest=False`, meaning they require a valid Frappe/ERPNext session cookie (`frappe.session` or authenticated browser login).

---

## Versioning & Changelog

This app follows semantic versioning managed via `pyproject.toml` (`dynamic = ["version"]`). The current branch is `version-16`, targeting Frappe Framework v16.

Release workflow:
1. Features developed on feature branches
2. Merged to `version-16` branch
3. `bench get-app <url> --branch version-16` deploys the latest version
4. `bench --site <site> migrate` applies any database patches