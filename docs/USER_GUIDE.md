# Awesome Dashboard — User Guide

## Welcome

The **Awesome Dashboard** is a Frappe/ERPNext app that gives you a unified view of your business metrics — sales, purchases, expenses, profits, and stock — plus a one-click full purchase cycle (Purchase Order → Purchase Receipt → Purchase Invoice → Payment Entry).

Once installed, you'll find the dashboard under **Home** or **Reports** in the Frappe Desk.

---

## Getting Started

### 1. Log in to the Desk
After installation, navigate to the **Awesome Dashboard** menu. If it doesn't appear immediately, refresh the page or run:

```bash
bench --site <your_site> execute "awesome_dashboard.installer.ensure_dashboard_permissions()"
```

### 2. Set Your Company
All dashboard metrics are company-scoped. Make sure at least one **Company** is configured (**Home** → **Company** → **New Company**).

### 3. Understand the "Awesome Dashboard User" Role
The app creates a custom role **Awesome Dashboard User** with granular permissions on core ERPNext doctypes. This role is assigned to users who should have dashboard access. Permissions are idempotent and preserve standard system permissions (e.g., System Manager, Accounts User).

---

## Dashboard Overview

When you open the dashboard, you'll see:

### Key Metrics (Current vs Previous Period)

| Metric | Description |
|--------|-------------|
| **Sales** | Total `tabPOS Invoice` total (docstatus = 1) for the period |
| **Purchases** | Total `tabPurchase Invoice` grand_total (docstatus = 1) for the period |
| **Expenses** | `SUM(debit) - SUM(credit)` from `tabGL Entry` (excluding Stock Expenses) |
| **Gross Profit** | `Sales - Purchases` |
| **Net Profit** | `Gross Profit - Expenses` |
| **Gross Margin %** | `(Gross Profit / Sales) * 100` (0 if Sales = 0) |
| **Net Margin %** | `(Net Profit / Sales) * 100` (0 if Sales = 0) |

### Charts & Breakdowns

- **Sales by Month**: Last 6 months trend, grouped by `YYYY-MM`
- **Sales by Item Group**: Item groups ranked by total sales amount
- **Expense Breakdown**: Direct + Indirect expenses by account (Stock Expenses excluded)
- **Purchase Order Breakdown**: Purchase invoices grouped by supplier
- **Stock Levels**: Current warehouse stock with quantities and values

---

## Creating an Item

1. Go to **Awesome Dashboard** → **Create Item**
2. Fill in the fields:
   - **Company** — required, must exist in ERPNext
   - **Item Name** — the name/code for the new item (required)
   - **Item Group** — must already exist in ERPNext (required)
   - **Buying Price** (optional) — sets the Standard Buying price list rate
   - **Selling Price** (optional) — sets the Standard Selling price list rate
3. Click **Create**

The item is created with stock tracking enabled (`is_stock_item: 1`). If buying/selling prices are provided, corresponding `Item Price` records are created.

---

## Full Purchase Cycle (PO → PR → PI → PE)

This feature creates all four document types in a single flow:

1. **Go to** **Awesome Dashboard** → **Create Full Purchase**
2. **Enter**:
   - **Company** — required
   - **Supplier** — an existing Supplier in ERPNext (required)
   - **Warehouse** — a non-group warehouse belonging to the company (required)
   - **Items** — list of dicts, each with `item_code`, `qty`, `rate` (required)
   - **Invoice Number** (optional) — supplier's invoice number
   - **Invoice Date** (optional) — defaults to today
3. **Click Create Full Purchase**

**What happens behind the scenes:**

| Document | Action |
|----------|--------|
| **Purchase Order** | Created and submitted |
| **Purchase Receipt** | Created, linked to the PO, and submitted |
| **Purchase Invoice** | Created, linked to the PR, and submitted. If `invoice_number` is provided, it's set as `bill_no`. |
| **Payment Entry** | Created to pay the supplier the full `grand_total`, linked to the PI. Supplier is paid via Cash account → Payable account. |
| **Item Prices** | Updated if rates > 0 (buying price → Standard Buying list, selling price → Standard Selling list) |

**Output**: Returns a dict with the names of all four created documents:
```json
{
  "purchase_order": "PO-00012",
  "purchase_receipt": "PR-00015",
  "purchase_invoice": "PI-00018",
  "payment_entry": "PE-00021"
}
```

---

## Amending a Purchase Cycle

If you need to update an existing purchase chain:

1. Go to **Awesome Dashboard** → **Amend Full Purchase**
2. Enter the **Purchase Invoice** name you want to amend
3. Update **Company**, **Supplier**, **Warehouse**, and **Items** as needed
4. Click **Amend**

**What happens:**

1. The existing Purchase Invoice, Payment Entry, Purchase Receipt, and Purchase Order are **cancelled**
2. A new chain is created with the updated details
3. Item prices are updated based on the new rates
4. The new posting dates are set to the specified invoice date

**Output**: Returns the names of the new documents created.

---

## Cancelling a Purchase Cycle

To reverse an entire purchase chain:

1. Go to **Awesome Dashboard** → **Cancel Full Purchase**
2. Enter the **Purchase Invoice** name to cancel
3. Click **Cancel**

**What happens**: The cancellation proceeds in reverse order:
1. Payment Entry (if submitted) → Cancelled
2. Purchase Invoice → Cancelled
3. Purchase Receipt → Cancelled
4. Purchase Order → Cancelled

**Output**: Returns a list of cancelled document names and a success message.

---

## Checking Stock Levels

1. Go to **Awesome Dashboard** → **Get Stock Levels**
2. Enter:
   - **Warehouse** — the warehouse name (warehouse_name field)
   - **Company** — the company name (required)
3. (Optional) **Pack Size Map** — dict mapping item_name substrings to divisor integers, e.g. `{"Pint": 24, "Quart": 12}` computes `pack_size = real_qty / divisor`

**Output**: A list of items in the warehouse with:
- Item code and name
- Real quantity (actual_qty - reserved_qty)
- Item group
- Selling price (Standard Selling)
- Buying price (Standard Buying)
- Optional `pack_size` field if pack_size_map is provided

---

## Getting Stock Valuation Over Time

### Average Stock Value (per period)

1. Go to **Awesome Dashboard** → **Get Average Stock Value**
2. Enter:
   - **From Date** — start date (YYYY-MM-DD, required)
   - **To Date** — end date (YYYY-MM-DD, required)
   - **Company** — company name (required)
   - **Time Grouping** — MySQL DATE_FORMAT string, e.g. `%%Y-%%m` for monthly, `%%Y` for yearly (required; the leading `%` must be double-escaped)

**Output**: Average stock value per time period, with closing balance for each period.

### Daily Stock Value

1. Go to **Awesome Dashboard** → **Get Daily Stock Value**
2. Enter:
   - **From Date** — start date (YYYY-MM-DD, required)
   - **To Date** — end date (YYYY-MM-DD, required)
   - **Company** — company name (required)

**Output**: Daily stock value with `days_from_end` column (1 = today, 2 = yesterday, etc.).

---

## Lookup Data (Suppliers & Warehouses)

### Search Suppliers

1. Go to **Awesome Dashboard** → **Search Suppliers**
2. Enter:
   - **Company** — required
   - **Query** (optional) — search term to filter supplier names

**Output**: List of `{name, supplier_name}` objects (limited to 20, sorted by name).

### Search Warehouses

1. Go to **Awesome Dashboard** → **Search Warehouses**
2. Enter:
   - **Company** — required

**Output**: List of non-group warehouse names for the company, sorted alphabetically.

---

## API Methods (Whitelisted)

All API functions are exposed as `/api/method/awesome_dashboard.api.<module>.<method>` and are marked `allow_guest=False`. The full list of verified endpoints:

| Module | Method | Signature |
|--------|--------|-----------|
| `awesome_dashboard.api.dashboard` | `dashboard_complete` | `(from_date, to_date, prev_from_date, prev_to_date, company, warehouse=None)` |
| `awesome_dashboard.api.dashboard` | `dashboard_bar_chart` | `(from_date, to_date, grouping, company)` |
| `awesome_dashboard.api.dashboard` | `dashboard_sales_aggregated` | `(from_date, to_date, company)` |
| `awesome_dashboard.api.dashboard` | `dashboard_expense_breakdown` | `(from_date, to_date, company)` |
| `awesome_dashboard.api.dashboard` | `dashboard_order_breakdown` | `(from_date, to_date, company)` |
| `awesome_dashboard.api.dashboard` | `dashboard_payment_entries` | `(from_date, to_date, company)` |
| `awesome_dashboard.api.dashboard` | `grouped_sales_summary` | `(from_date, to_date, company, time_grouping)` |
| `awesome_dashboard.api.dashboard` | `grouped_expenses_summary` | `(from_date, to_date, company, time_grouping)` |
| `awesome_dashboard.api.finance` | `account_names` | `(company, include_groups=False)` |
| `awesome_dashboard.api.finance` | `get_journal_entries` | `(company, start_date, end_date)` |
| `awesome_dashboard.api.finance` | `amend_expense_journal_entry` | `(journal_entry, amount, description, expense_account, income_account, posting_date, company)` |
| `awesome_dashboard.api.item` | `create_item` | `(company, item_name, item_group, buying_price=0, selling_price=0)` |
| `awesome_dashboard.api.item` | `search_items` | `(company, query="")` |
| `awesome_dashboard.api.lookup` | `search_suppliers` | `(company, query="")` |
| `awesome_dashboard.api.lookup` | `search_warehouses` | `(company)` |
| `awesome_dashboard.api.purchase` | `create_full_purchase` | `(company, supplier, warehouse, items, invoice_number=None, invoice_date=None)` |
| `awesome_dashboard.api.purchase` | `cancel_full_purchase` | `(purchase_invoice)` |
| `awesome_dashboard.api.purchase` | `amend_full_purchase` | `(purchase_invoice, company, supplier, warehouse, items, invoice_number=None, invoice_date=None)` |
| `awesome_dashboard.api.stock` | `get_stock_levels` | `(warehouse, company, pack_size_map=None)` |
| `awesome_dashboard.api.stock` | `get_average_stock_value` | `(from_date, to_date, company, time_grouping)` |
| `awesome_dashboard.api.stock` | `get_daily_stock_value` | `(from_date, to_date, company)` |

All endpoints require authentication (`allow_guest=False`) and return data in Frappe's standard format.

---

## Need Help?

- Run `bench --site <site> execute "awesome_dashboard.installer.ensure_dashboard_permissions()"` to refresh permissions
- Check the **Troubleshooting** section in the README.md for common issues
- Ensure ERPNext Stock is enabled if stock metrics return 0
- All dates must be in `YYYY-MM-DD` format