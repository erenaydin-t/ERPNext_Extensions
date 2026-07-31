# Consignment Stock — Solution Design

**Application:** `erpnext_extensions`  
**Target release:** `3.8.0` (current codebase `__version__` = `3.7.6` at design update)  
**Target ERPNext:** 16.x  
**Status:** Design approved — see `CONSIGNMENT_STOCK_IMPLEMENTATION_PLAN.md` (no code until implementation approval)  
**Date:** 2026-07-31 (revision: locked decisions L1–L5)

Related documents:

- `CONSIGNMENT_STOCK_BUSINESS_FLOW.md`
- `CONSIGNMENT_STOCK_ACCOUNTING_MATRIX.md`
- `CONSIGNMENT_STOCK_TEST_MATRIX.md`

---

## 1. Architecture summary

Use **standard Stock Entry** (Material Receipt / Material Issue) for perpetual inventory, and **standard Journal Entry** for party recognition and return settlement.

Extensions in `erpnext_extensions` add:

- Stock Entry Type flags
- Party Type + Party Dynamic Link fields on Stock Entry, with accounting-flow validation
- Reference custom fields on Stock Entry / Detail
- Validations and rate policy
- Forced Difference Account (`expense_account`) = Temporary Clearing (from Settings)
- Buttons + whitelisted services to create draft JEs
- Per-company `Consignment Stock Settings`
- Dashboard / link tracking
- Cancellation guards

**Do not** invent a parallel inventory ledger. **Do not** post inventory via Journal Entry.

### Compatibility with existing iran_accounting

Cooperate with existing `StockEntry.get_gl_entries` monkey patch by forcing `expense_account` and receipt rates; extend patched GL only if forcing is insufficient.

---

## 2. Module placement

Create package `erpnext_extensions/consignment_stock/` (sibling to `iran_accounting`, not scattered into IRR-only files).

```text
erpnext_extensions/consignment_stock/
    __init__.py
    CONSIGNMENT_STOCK_*.md          # design docs
    constants.py
    stock_entry_type.py
    stock_entry_hooks.py
    stock_entry_rates.py
    accounting.py                   # Settings resolve + party account validation
    recognition_service.py
    settlement_service.py
    returnable_qty.py
    queries.py
    permissions.py
    dashboard.py
    custom_fields.py
    public/js/stock_entry_consignment.js
    public/js/stock_entry_type_consignment.js
    doctype/consignment_stock_settings/
    tests/
```

Optional Desk module `Consignment Stock` in `modules.txt` when shipping Settings UI.

---

## 3. Settings DocType (approved)

### Recommendation: `Consignment Stock Settings` (one document per company)

**Pattern:** Facility Settings / PDC Settings — company-keyed setup DocType.

| Option | Verdict |
| --- | --- |
| Stock Settings | **Rejected** for consignment accounts (no company dimension; Valuation Difference must not live here) |
| Company custom fields | **Rejected** for Valuation Difference and consignment account set |
| **Consignment Stock Settings (autoname by company)** | **Approved** |

### Required / approved Settings fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `company` | Link/Company | Yes | Unique |
| `consignment_inventory_account` | Link/Account | Yes | Validate vs warehouse usage |
| `consignment_temporary_clearing_account` | Link/Account | Yes | Not Stock; not group |
| `consignment_valuation_difference_account` | Link/Account | Yes | **Only** here — not Company, not Stock Settings |
| `default_cost_center` | Link/Cost Center | No | Optional default |
| `default_finance_book` | Link/Finance Book | No | Optional default |

### Additional policy fields (unchanged recommendations)

| Field | Default | Notes |
| --- | --- | --- |
| `allow_return_without_receipt_reference` | 0 | |
| `require_recognition_before_return` | 0 | |
| `require_recognition_before_settlement` | **1** | |
| `auto_submit_journal_entries` | **0** (draft-first) | |
| `allow_zero_receipt_rate` | 0 | |
| `default_consignment_warehouse` | — | Optional UX |

**Removed from earlier draft:** `allow_customer_consignment` gate (Customer is allowed via open Party Type policy).  
**Removed from earlier draft as Settings account:** dedicated `default_party_payable_account` — party account comes from ERPNext `get_party_account(party_type, party, company)`.

### Account validation rules

For every account field on Settings:

1. Account.company == Settings.company  
2. Account.is_group == 0  
3. Account.disabled == 0  
4. Currency compatible with company rules  
5. Temporary Clearing: `account_type` ≠ `Stock`; prefer Balance Sheet  
6. Valuation Difference: typically P&L; warn if Balance Sheet  
7. Inventory: Stock/Asset appropriate; consistent with consignment warehouse account  

On Stock Entry validate: load Settings for `doc.company`; throw if Temporary Clearing / Valuation Difference missing when consignment type requires them (settlement creation also re-validates Diff account).

---

## 4. Stock Entry Type configuration

| DocType | Field name | Label | Type | Validation |
| --- | --- | --- | --- | --- |
| Stock Entry Type | `custom_is_consignment_receipt` | Consignment Receipt | Check | Only if purpose=`Material Receipt`; exclusive vs return |
| Stock Entry Type | `custom_is_consignment_return` | Consignment Return | Check | Only if purpose=`Material Issue`; exclusive vs receipt |

---

## 5. Stock Entry / Detail custom fields

### 5.1 Reuse standard fields

| Need | Standard field |
| --- | --- |
| Rates | `basic_rate`, `valuation_rate`, amounts |
| Clearing account | `expense_account` → Temporary Clearing from Settings |
| Warehouses | `t_warehouse` / `s_warehouse` |
| Cost center | `cost_center` (fallback Settings default) |

Do **not** use header `supplier` alone — always Party Type + Party Dynamic Link.

### 5.2 Header fields (Stock Entry)

| Field name | Label | Type | Options | Mandatory when | Notes |
| --- | --- | --- | --- | --- | --- |
| `custom_is_consignment_receipt` | Is Consignment Receipt | Check | — | — | Fetched from type; read-only |
| `custom_is_consignment_return` | Is Consignment Return | Check | — | — | Fetched from type; read-only |
| `custom_consignment_party_type` | Party Type | Link | Party Type | Receipt or Return | Not limited to Supplier |
| `custom_consignment_party` | Party | Dynamic Link | `custom_consignment_party_type` | Receipt or Return | Accounting-flow validated |
| `custom_has_consignment_receipt_reference` | Has Receipt Reference | Check | — | — | Default 1 |
| `custom_consignment_receipt_reference` | Default Receipt Reference | Link | Stock Entry | Optional | UX default for rows |
| `custom_consignment_recognition_je` | Recognition Journal Entry | Link | Journal Entry | — | Read-only; set by service |
| `custom_consignment_settlement_je` | Settlement Journal Entry | Link | Journal Entry | — | Read-only; set by service |
| `custom_consignment_status` | Consignment Status | Select | (status list) | — | Read-only |
| `custom_consignment_external_reference` | External Reference | Data | — | Return without receipt ref | Audit |

### 5.3 Party validation (approved)

On validate / before_submit for consignment SE:

1. Party Type and Party mandatory.  
2. Party Type.account_type in (`Payable`, `Receivable`).  
3. Resolve `party_account = get_party_account(party_type, party, company)`.  
4. Fail if missing, wrong company, group, disabled, or account_type mismatch.  
5. On return with receipt reference: Party Type + Party must equal receipt’s party fields.  

Allowed examples: Supplier, Customer, Employee (if Party Type exists), other site Party Types with valid accounts.

### 5.4 Detail fields (Stock Entry Detail)

| Field name | Label | Type | Mandatory when | Notes |
| --- | --- | --- | --- | --- |
| `custom_consignment_receipt_stock_entry` | Consignment Receipt | Link/Stock Entry | Return + has_ref | Row-level required model |
| `custom_consignment_receipt_detail` | Consignment Receipt Row | Data | Return + has_ref | Detail name |
| `custom_original_receipt_rate` | Original Receipt Rate | Currency | Return + has_ref | Stock UOM rate snapshot |
| `custom_external_settlement_rate` | External Settlement Rate | Currency | Return without ref | Must be defined |
| `custom_original_receipt_qty` | Original Receipt Qty | Float | — | Snapshot |
| `custom_previously_returned_qty` | Previously Returned Qty | Float | — | Snapshot at save |
| `custom_remaining_returnable_qty` | Remaining Returnable Qty | Float | — | Calculated snapshot |
| `custom_consignment_settlement_amount` | Settlement Amount | Currency | — | qty × settlement rate |

**Reference model:** row-level required when `has_ref`; header link is UX default only.

---

## 6. Item valuation rate (receipt) — unchanged

- Use `basic_rate` / `valuation_rate`.  
- Prefer `set_basic_rate_manually = 1` on consignment receipt rows to skip auto `get_valuation_rate`.  
- Reject zero unless Settings allow.  
- Preserve UOM via `transfer_qty`; store stock-UOM rate on return snapshots.  
- Repost: keep Temporary Clearing on rows; block/guard if settlement JE exists.

---

## 7. Return valuation — unchanged

System warehouse rate only; force Temporary Clearing; settlement `A` from submitted outgoing value.

---

## 8. Document relationships — unchanged

Receipt ↔ Recognition JE; Return ↔ Settlement JE; Return row → Receipt row; JE custom links to source SE; dashboards both ways. Prefer custom Link fields over JE `reference_type` Select expansion.

---

## 9. Buttons and UI — unchanged

Draft-first JE creation (`auto_submit_journal_entries = 0`). Buttons gated on submit status, Settings accounts present, no active linked JE, party valid.

---

## 10. Cancellation and amendment — unchanged

Block receipt cancel if recognition submitted or returns exist; block return cancel if settlement submitted; JE-only cancel clears links; block amend receipt with returns; guard repost when settlement active.

---

## 11. Permissions — unchanged intent

Map to Stock User / Stock Manager / Accounts User / Accounts Manager; optional Consignment roles. Creating recognition/settlement is accounting-side. Return-without-reference manager-gated.

---

## 12. ERPNext extension points — unchanged

| Concern | Mechanism |
| --- | --- |
| Validation / cancel | `doc_events` |
| UI | `doctype_js` |
| JE create | Whitelisted services |
| GL | Prefer expense_account forcing; extend iran_accounting patch only if needed |
| Fields | `create_custom_fields` patches + after_migrate |
| Queries | Whitelisted + set_query |
| Dashboard | `override_doctype_dashboards` |

Avoid new Stock Entry `override_doctype_class`.

---

## 13. Rounding — unchanged

Use ERPNext precision APIs; aggregate `R`, `A`, `D` at settlement header level; no hardcoded IRR=0 in reusable logic.

---

## 14. Migration and release (3.8.0)

1. New DocType `Consignment Stock Settings` with approved account + default fields.  
2. Custom fields patch `patches/post_model_sync/add_consignment_stock_custom_fields.py`.  
3. Optional after_migrate ensure.  
4. No Company custom fields for Valuation Difference (or other consignment accounts).  
5. No Stock Settings fields for consignment accounts.  
6. Greenfield — no historical data migration.  
7. Version bump `__init__.py` → `3.8.0` **only at implementation**.  
8. `patches.txt` entry; release notes covering party Dynamic Link, Settings COA, accounting lifecycle.  

Commands (implementation phase only):

```bash
bench --site <site> migrate
bench --site <site> clear-cache
bench --site <site> run-tests --app erpnext_extensions --module erpnext_extensions.consignment_stock.tests
```

---

## 15. Implementation phases — unchanged order

P0 Settings/fields/flags → P1 Receipt (+ party validation) → P2 Recognition → P3 Return → P4 Settlement → P5 no-reference returns → P6 polish/release **3.8.0**.

---

## 16. Risks and upgrade concerns

1. iran_accounting owns `get_gl_entries`.  
2. MA pollution without dedicated warehouse.  
3. Repost vs settlement drift.  
4. Customer Receivable credit balances need accountant training / reports clarity.  
5. Additional costs disallowed on consignment types.  
6. Dual Stock Entry hooks ordering.

---

## 17. Approval decisions

### Approved in this revision

| # | Decision |
| --- | --- |
| A1 | Target release **3.8.0** |
| A2 | Party Type **not** restricted to Supplier; Dynamic Link; Supplier, Customer, and other accounting Party Types with valid flow |
| A3 | Company-specific **Consignment Stock Settings** |
| A4 | Settings stores Inventory, Temporary Clearing, Valuation Difference, Default Cost Center, Default Finance Book |
| A5 | Valuation Difference Account **not** on Company or Stock Settings |

### Locked for implementation (2026-07-31)

| # | Decision |
| --- | --- |
| L1 | Submitted Recognition JE is **mandatory** before any Consignment Return Stock Entry |
| L2 | Party account via standard `get_party_account` (Supplier→Payable, Customer→Receivable, others if resolvable) |
| L3 | `Difference = Actual Return Valuation − Original Receipt Settlement Amount`; Settlement JE handles `D>0` and `D<0` |
| L4 | Consignment Stock Entries must not allow Additional Cost allocation |
| L5 | Prefer hooks / doc_events / services / whitelisted methods; GL override only if no supported extension point works |

### Other approved decisions (unchanged)

| # | Decision |
| --- | --- |
| U1 | Recognition JE: **Dr Temp / Cr Party** |
| U2 | Draft-first JE creation |
| U3 | Settlement implicitly requires recognition (via L1) |
| U4 | Return without receipt reference **out of scope for 3.8.0** under L1 |
| U5 | Row-level receipt references required when referenced |
| U6 | Use `basic_rate` for receipt valuation |
| U7 | Force `expense_account` = Temporary Clearing |
| U8 | Block Item Repost when settlement exists |
| U9 | `custom_*` field naming |
| U10 | Module package `stock_consignment` |
