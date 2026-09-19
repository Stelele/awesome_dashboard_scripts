### Awesome Dashboard

What if there's one dashboard to rule them all — within reason, of course.

A Frappe/ERPNext app that provides a unified dashboard with sales, purchases, expenses, profit metrics, stock levels, and a full purchase cycle (PO → PR → PI → Payment Entry) at your fingertips.

---

### Features

- **Dashboard Metrics**: Current vs previous period sales, purchases, expenses, gross profit, net profit, and margins
- **Sales Analysis**: Grouped by time period (day/week/month/quarter), by category, and aggregated by item
- **Expense Breakdown**: Direct + Indirect expenses (excluding Stock Expenses) by account
- **Purchase Cycle**: Create Purchase Order → Purchase Receipt → Purchase Invoice → Payment Entry in one flow
- **Amend/Cancel Purchase Cycle**: Update or reverse an entire purchase chain
- **Stock Tracking**: Current stock levels, average value per period, daily valuation with days-from-end
- **Item Management**: Create items with buying/selling price lists, search items
- **Lookup Data**: Search suppliers and non-group warehouses by company
- **Role-Based Permissions**: "Awesome Dashboard User" role with granular read access on core ERPNext doctypes (Account, Company, Item, Journal Entry, etc.)

---

### Installation

#### Via Bench CLI

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/Stelele/awesome_dashboard_scripts --branch version-16
# get-app clones into apps/awesome_dashboard_scripts — rename so bench finds the correct app name
mv apps/awesome_dashboard_scripts apps/awesome_dashboard
# ERPNext is a required dependency — ensure it is already installed on the site
bench --site <site_name> install-app erpnext
bench --site <site_name> install-app awesome_dashboard
```

#### Via Frappe Cloud

1. Log in to [Frappe Cloud](https://cloud.frappe.io)
2. Go to **Apps** → **Available Apps**
3. Search for `awesome_dashboard`
4. Click **Add** to install the app on your site
5. After installation, the **Awesome Dashboard User** role will be created automatically with permissions on core ERPNext doctypes

---

### Setup

After installation:

1. **Log in to the Desk** — the Dashboard menu item should appear under **Home** or **Reports**
2. **Role Setup**: The "Awesome Dashboard User" role is created automatically via fixtures. If you need to customize permissions, run:
   ```bash
   bench --site <site_name> execute "awesome_dashboard.installer.ensure_dashboard_permissions()"
   ```
3. **Grant Permissions**: The installer grants read/write/create permissions on core ERPNext doctypes (Account, Company, Item, Journal Entry, Purchase Invoice, etc.) to the "Awesome Dashboard User" role
4. **Configure Companies**: Ensure at least one Company is set up in ERPNext, as all dashboard metrics are company-scoped
5. **Set Date Ranges**: Use the dashboard picker to select current and previous period date ranges

---

### Usage Walkthrough

#### Viewing Dashboard Metrics

1. Navigate to **Home** → **Awesome Dashboard** (or find it in the Reports section)
2. The dashboard shows:
   - **Current vs Previous Period**: Sales, Purchases, Expenses, Gross Profit, Net Profit
   - **Gross Margin %**: `(Gross Profit / Sales) * 100`
   - **Net Margin %**: `(Net Profit / Sales) * 100`
   - **Sales by Month**: Last 6 months trend
   - **Sales by Item Group**: Top categories by total sales
   - **Expense Breakdown**: Direct vs Indirect expenses by account

#### Creating an Item

1. Go to **Awesome Dashboard** → **Create Item**
2. Enter:
   - **Company**: The company context
   - **Item Name**: Name and code for the new item
   - **Item Group**: Must already exist in ERPNext
   - **Buying Price** (optional): Sets the Standard Buying price list rate
   - **Selling Price** (optional): Sets the Standard Selling price list rate
3. Click **Create** — the item is created with stock tracking, and optional price entries are added

#### Full Purchase Cycle (PO → PR → PI → PE)

1. Go to **Awesome Dashboard** → **Create Full Purchase**
2. Enter:
   - **Company**: Company name
   - **Supplier**: Existing Supplier name
   - **Warehouse**: Receiving warehouse (non-group)
   - **Items**: List of `{item_code, qty, rate}` dicts
   - **Invoice Number** (optional): Supplier's invoice number
   - **Invoice Date** (optional):defaults to today
3. Click **Create Full Purchase** — the system creates:
   - Purchase Order (submitted)
   - Purchase Receipt (submitted)
   - Purchase Invoice (submitted)
   - Payment Entry (submitted) — pays the supplier
   - Item prices are updated if rates > 0

#### Amending a Purchase Cycle

1. Go to **Awesome Dashboard** → **Amend Full Purchase**
2. Enter the **Purchase Invoice** name to amend
3. Update **Company**, **Supplier**, **Warehouse**, and **Items** as needed
4. Click **Amend** — the old chain is cancelled and a new one is created with updated details

#### Cancelling a Purchase Cycle

1. Go to **Awesome Dashboard** → **Cancel Full Purchase**
2. Enter the **Purchase Invoice** name to cancel
3. Click **Cancel** — the entire chain (PE → PI → PR → PO) is cancelled in reverse order

#### Stock Level Check

1. Go to **Awesome Dashboard** → **Get Stock Levels**
2. Enter **Warehouse** and **Company**
3. View current stock levels with real-time quantities, selling/buying prices
4. Optionally provide a **pack_size_map** e.g. `{"Pint": 24, "Quart": 12}` to compute pack sizes

---

### Configuration Reference

| Setting | Description | Default / Notes |
|---------|-------------|-----------------|
| `DASHBOARD_ROLE` | Role name for dashboard access | `"Awesome Dashboard User"` |
| `DASHBOARD_PERMISSIONS` | Dict of `{doctype: {perm: 1}}` granting read/write/create access | See `installer.py` for full list |
| `after_install` | Grants dashboard permissions after app install | Automatically run |
| `after_migrate` | Keeps permissions in sync on every migrate | Idempotent, safe to repeat |

**`DASHBOARD_PERMISSIONS`** grants the following read/write/create access on core ERPNext doctypes:

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

### Troubleshooting / FAQ

**Q: I get "Company is required" error when accessing dashboard**
- A: Ensure a Company is set up in ERPNext (`Home` → **Company** → **New Company**). All dashboard metrics are scoped to a company.

**Q: Permission denied for dashboard role**
- A: The "Awesome Dashboard User" role must be created and permissions granted. Run:
  ```bash
  bench --site <site> execute "awesome_dashboard.installer.ensure_dashboard_permissions()"
  ```

**Q: Purchase cycle creation fails**
- A: Verify that:
  - The Supplier exists in ERPNext
  - The Warehouse exists and belongs to the specified Company
  - All Items in the list exist and are valid
  - The warehouse is a non-group warehouse (not a parent group)

**Q: Stock levels show 0 or incorrect values**
- A: Ensure Stock is enabled for the company and items. Bin records must exist (`Stock` → **Stock Entry** transactions have been processed).

**Q: How to customize the dashboard page**
- A: The dashboard is built from whitelisted API methods in `awesome_dashboard.api.dashboard`. To add new metrics, add a new function there and reference it in the dashboard page template.

---

### Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m "feat: add amazing feature"`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

**Development Setup:**

```bash
# In your bench directory
bench get-app https://github.com/Stelele/awesome_dashboard_scripts --branch version-16
mv apps/awesome_dashboard_scripts apps/awesome_dashboard
bench --site <site> install-app awesome_dashboard

# Run linting
cd apps/awesome_dashboard
pre-commit run --all-files

# Run tests (if any)
bench --site <site> run-tests --app awesome_dashboard
```

Pre-commit is configured with: ruff, eslint, prettier, pyupgrade

---

### License

MIT

Copyright (c) 2026 Gift Mugweni

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.