# Consignment Stock — Implementation Plan (3.8.0)

**Application:** `erpnext_extensions`  
**Target release:** `3.8.0`  
**Status:** Implementation planning only — **no code until final implementation approval**  
**Date:** 2026-07-31  
**Depends on:** Approved design docs in this folder

---

## 0. Locked decisions (final)

| # | Decision | Implementation implication |
| --- | --- | --- |
| L1 | Submitted Recognition JE **mandatory** before any Consignment Return Stock Entry | Hard validation on return `validate` / `before_submit`; Settings flag `require_recognition_before_return` becomes redundant (always enforced) or removed from Settings UI |
| L2 | Party account via `get_party_account(party_type, party, company)` | Supplier→Payable, Customer→Receivable; other Party Types only if resolution succeeds |
| L3 | `Difference = Actual Return Valuation − Original Receipt Settlement Amount` | Settlement JE builds Diff debit when `D > 0`, Diff credit when `D < 0` |
| L4 | No Additional Cost on consignment Stock Entries | Validate `additional_costs` empty; block UI add |
| L5 | Prefer hooks / doc_events / services / whitelisted methods | No broad monkey patches; GL override only if `expense_account` forcing fails |

Also locked from prior approval (unchanged):

- Recognition JE: Dr Temporary Clearing / Cr Party  
- Draft-first JE (`auto_submit_journal_entries` default 0)  
- Company-specific `Consignment Stock Settings`  
- Valuation Difference only on Settings  
- Open Party Type via Dynamic Link  
- Row-level receipt references when referenced  
- Receipt valuation via `basic_rate`  
- Force `expense_account` = Temporary Clearing  

---

## 1. Implementation strategy (accounting without GL monkey patch)

### Primary path (preferred)

1. **Receipt (Material Receipt):**  
   - User enters `basic_rate`.  
   - Set `set_basic_rate_manually = 1` on rows so ERPNext does not overwrite with `get_valuation_rate`.  
   - Force each row `expense_account` = Settings Temporary Clearing.  
   - Ensure target warehouse inventory account aligns with Settings Consignment Inventory (validate).  
   - Standard / iran_accounting SE GL → Dr Inventory / Cr Temp.

2. **Return (Material Issue):**  
   - Lock outgoing rates to warehouse valuation (read-only + server re-assert).  
   - Force `expense_account` = Temporary Clearing.  
   - Standard / iran_accounting SE GL → Dr Temp / Cr Inventory.

3. **Recognition / Settlement:** Separate Journal Entries via service layer (not SE GL).

### Fallback (only if primary fails ledger contract)

Isolated branch inside existing `iran_accounting.zero_value_transfer.get_gl_entries` gated by consignment flags — **not** a new global monkey patch. Requires explicit secondary approval if needed after P1 receipt GL tests.

---

## 2. Files to create

### 2.1 Package skeleton

```text
erpnext_extensions/consignment_stock/
    __init__.py
    constants.py
    custom_fields.py
    accounting.py
    party.py
    stock_entry_type.py
    stock_entry_hooks.py
    stock_entry_rates.py
    additional_costs.py
    returnable_qty.py
    recognition_service.py
    settlement_service.py
    journal_entry_hooks.py
    queries.py
    api.py                      # whitelisted entrypoints
    status.py
    permissions.py              # optional thin helpers
    dashboard.py
    install.py                  # after_migrate ensure custom fields
    public/js/
        stock_entry_consignment.js
        stock_entry_type_consignment.js
        consignment_stock_settings.js   # if needed for account filters
    doctype/
        consignment_stock_settings/
            consignment_stock_settings.json
            consignment_stock_settings.py
            consignment_stock_settings.js
            test_consignment_stock_settings.py
    tests/
        __init__.py
        test_consignment_config.py
        test_consignment_party.py
        test_consignment_receipt.py
        test_consignment_recognition.py
        test_consignment_return.py
        test_consignment_settlement.py
        test_consignment_cancellation.py
        test_consignment_regression.py
        test_consignment_permissions.py
        helpers.py                  # shared fixtures
```

Design markdown files already present stay as documentation (not runtime).

### 2.2 Patches / wiring files to create or edit

| Path | Action |
| --- | --- |
| `patches/post_model_sync/add_consignment_stock_custom_fields.py` | **Create** — calls `custom_fields.ensure_custom_fields()` |
| `patches.txt` | **Edit** — append patch under `[post_model_sync]` |
| `hooks.py` | **Edit** — doc_events, doctype_js, after_migrate, optional dashboard |
| `modules.txt` | **Edit** — add `Consignment Stock` |
| `erpnext_extensions/__init__.py` | **Edit** — `__version__ = "3.8.0"` at release cut |
| `pyproject.toml` | **Edit** only if version/description needs sync at release |

### 2.3 Files intentionally not created (v3.8.0)

- No Company custom fields for consignment accounts  
- No Stock Settings custom fields  
- No new monkey_patches module  
- No `override_doctype_class` for Stock Entry  
- No new Role fixtures unless permissions phase requires them  

---

## 3. DocTypes

### 3.1 New: `Consignment Stock Settings`

| Attribute | Value |
| --- | --- |
| Module | Consignment Stock |
| Naming | `autoname: field:company` (one per company) |
| Type | Setup |
| Permissions | System Manager, Accounts Manager (write); Accounts User / Stock Manager (read) |

**Fields:**

| Fieldname | Type | Req | Notes |
| --- | --- | --- | --- |
| `company` | Link/Company | Y | Unique |
| `consignment_inventory_account` | Link/Account | Y | Filter company, non-group |
| `consignment_temporary_clearing_account` | Link/Account | Y | Not Stock |
| `consignment_valuation_difference_account` | Link/Account | Y | Diff JE only |
| `default_cost_center` | Link/Cost Center | N | |
| `default_finance_book` | Link/Finance Book | N | |
| `allow_return_without_receipt_reference` | Check | N | Default 0 |
| `auto_submit_journal_entries` | Check | N | Default 0 |
| `allow_zero_receipt_rate` | Check | N | Default 0 |
| `default_consignment_warehouse` | Link/Warehouse | N | UX |

**Removed vs earlier draft:** `require_recognition_before_return` / `require_recognition_before_settlement` as optional toggles — recognition-before-return is **hard-coded mandatory** (L1). Settlement still requires recognition implicitly because returns cannot exist without it.

**Controller validations:** account company, non-group, not disabled, Temporary Clearing ≠ Stock, inventory consistency helpers.

### 3.2 Custom fields (via `create_custom_fields`, not new child DocTypes)

Defined in `custom_fields.py`, applied by patch + `after_migrate`.

**Stock Entry Type**

- `custom_is_consignment_receipt` (Check)  
- `custom_is_consignment_return` (Check)  

**Stock Entry**

- `custom_is_consignment_receipt` / `custom_is_consignment_return` (Check, fetch from type, read-only)  
- `custom_consignment_party_type` (Link/Party Type)  
- `custom_consignment_party` (Dynamic Link)  
- `custom_has_consignment_receipt_reference` (Check)  
- `custom_consignment_receipt_reference` (Link/Stock Entry)  
- `custom_consignment_recognition_je` (Link/Journal Entry, read-only)  
- `custom_consignment_settlement_je` (Link/Journal Entry, read-only)  
- `custom_consignment_status` (Select, read-only)  
- `custom_consignment_external_reference` (Data)  

**Stock Entry Detail**

- `custom_consignment_receipt_stock_entry` (Link/Stock Entry)  
- `custom_consignment_receipt_detail` (Data)  
- `custom_original_receipt_rate` (Currency)  
- `custom_external_settlement_rate` (Currency)  
- `custom_original_receipt_qty` (Float)  
- `custom_previously_returned_qty` (Float)  
- `custom_remaining_returnable_qty` (Float)  
- `custom_consignment_settlement_amount` (Currency)  

**Journal Entry**

- `custom_consignment_stock_entry` (Link/Stock Entry) — source SE  
- `custom_consignment_receipt_stock_entry` (Link/Stock Entry) — optional original receipt  
- `custom_consignment_je_role` (Select: `Recognition` / `Settlement` / empty) — idempotency aid  

No new transactional DocTypes beyond Settings.

---

## 4. Patches

| Order | Patch | Purpose |
| --- | --- | --- |
| 1 | DocType migrate for `Consignment Stock Settings` | Automatic via Frappe sync |
| 2 | `add_consignment_stock_custom_fields` | Idempotent `create_custom_fields(..., update=True)` |

`after_migrate`: `stock_consignment.install.after_migrate` → re-ensure custom fields (same pattern as other modules).

No data backfill patch (greenfield feature).

---

## 5. Hooks registration (`hooks.py`)

### 5.1 `doctype_js`

```text
"Stock Entry": ["consignment_stock/public/js/stock_entry_consignment.js"]
"Stock Entry Type": ["consignment_stock/public/js/stock_entry_type_consignment.js"]
"Consignment Stock Settings": ["consignment_stock/public/js/consignment_stock_settings.js"]  # optional
```

Append to existing Stock Entry list if other JS is later added; currently none for Stock Entry.

### 5.2 `doc_events` (additive lists)

| DocType | Event | Handler |
| --- | --- | --- |
| Stock Entry Type | `validate` | `stock_consignment.stock_entry_type.validate` |
| Stock Entry | `validate` | `stock_consignment.stock_entry_hooks.validate` |
| Stock Entry | `before_submit` | `stock_consignment.stock_entry_hooks.before_submit` |
| Stock Entry | `on_submit` | `stock_consignment.stock_entry_hooks.on_submit` |
| Stock Entry | `before_cancel` | `stock_consignment.stock_entry_hooks.before_cancel` |
| Stock Entry | `on_cancel` | `stock_consignment.stock_entry_hooks.on_cancel` |
| Journal Entry | `before_cancel` | `stock_consignment.journal_entry_hooks.before_cancel` |
| Journal Entry | `on_cancel` | `stock_consignment.journal_entry_hooks.on_cancel` |

Keep existing `iran_accounting.stock_entry.*` hooks; consignment hooks must be **side-effect safe** when not consignment (early return).

### 5.3 `after_migrate`

Append `erpnext_extensions.consignment_stock.install.after_migrate`.

### 5.4 Optional

```text
override_doctype_dashboards = {
  "Stock Entry": "erpnext_extensions.consignment_stock.dashboard.get_stock_entry_dashboard_data",
  "Journal Entry": "erpnext_extensions.consignment_stock.dashboard.get_journal_entry_dashboard_data",
}
```

### 5.5 Explicitly not registering

- `override_doctype_class` for Stock Entry / Stock Entry Type  
- New monkey patches in `iran_accounting.integration`  
- `override_whitelisted_methods` for stock rate APIs unless client-only approach fails  

---

## 6. Methods / module responsibilities

### 6.1 `constants.py`

Fieldnames, status values, JE role labels, allowed purposes.

### 6.2 `accounting.py`

- `get_consignment_settings(company)`  
- `validate_settings_accounts(settings)`  
- `get_temporary_clearing_account(company)`  
- `get_valuation_difference_account(company)`  
- `get_inventory_account(company)`  
- `apply_default_cost_center(doc)` / finance book helpers  
- `force_expense_account_on_items(doc, account)`  

### 6.3 `party.py`

- `validate_consignment_party(party_type, party, company)`  
- `resolve_party_account(party_type, party, company)` → wraps `get_party_account`  
- Reject if empty / type mismatch / disabled  

### 6.4 `stock_entry_type.py`

- Mutual exclusion of receipt/return flags  
- Purpose compatibility  

### 6.5 `stock_entry_hooks.py`

Orchestrates:

| Hook | Consignment receipt | Consignment return |
| --- | --- | --- |
| validate | party; rates; force expense; no additional costs; fetch type flags | party; recognition exists (**L1**); refs/qty; force expense; no additional costs; lock rates |
| before_submit | re-assert rates/accounts; zero-rate policy | re-assert; remaining qty; recognition still submitted |
| on_submit | status → Receipt Submitted | status → Return Submitted; update receipt return progress |
| before_cancel | block if recognition JE / returns exist | block if settlement JE exists |
| on_cancel | status Cancelled | restore returnable qty side-effects via recalc |

Non-consignment: immediate return.

### 6.6 `stock_entry_rates.py`

- Receipt: ensure manual `basic_rate` > 0 (unless allow zero); set `set_basic_rate_manually`  
- Return: clear user overrides; rely on ERPNext outgoing rate; read-only enforcement server-side  

### 6.7 `additional_costs.py`

- `validate_no_additional_costs(doc)` — throw if any `additional_costs` rows or allocated amounts  

### 6.8 `returnable_qty.py`

- `get_returned_qty(receipt_detail_name)` excluding cancelled  
- `get_remaining_returnable_qty(...)`  
- `validate_return_row_qty(row)`  
- Populate snapshot fields on validate  

### 6.9 `recognition_service.py`

- `can_create_recognition(stock_entry_name)`  
- `create_recognition_journal_entry(stock_entry_name)` → draft JE (or submit if Settings)  
  - Dr Temp = receipt value  
  - Cr Party account = same  
  - Link fields + remarks  
- Duplicate guard on active JE  

### 6.10 `settlement_service.py`

- `compute_settlement_amounts(return_se)` → `R`, `A`, `D` with `D = A - R`  
- `create_settlement_journal_entry(return_se_name)`  
  - Dr Party `R`  
  - if `D > 0`: Dr Diff `D`  
  - if `D < 0`: Cr Diff `|D|`  
  - Cr Temp `A`  
- Require no active settlement; return must be submitted consignment return  

### 6.11 `journal_entry_hooks.py`

- On cancel of Recognition/Settlement JE: clear SE link fields; reset status  
- before_cancel: allow (does not auto-cancel SE)  

### 6.12 `api.py` (whitelisted)

| Method | Purpose |
| --- | --- |
| `create_consignment_recognition_entry(stock_entry)` | Button |
| `create_consignment_return_settlement(stock_entry)` | Button |
| `get_eligible_consignment_receipts(...)` | Link query helper |
| `get_receipt_row_returnable_qty(...)` | Client fetch |
| `make_consignment_return_from_receipt(source_name)` | Optional mapped return |

Permissions: `frappe.has_permission` on Stock Entry / Journal Entry as appropriate.

### 6.13 `queries.py`

- `consignment_receipt_query` for Link field filters (company, party, submitted, remaining qty > 0, consignment receipt flag)  

### 6.14 `status.py`

- Central status transitions for receipt/return lifecycle  

### 6.15 `dashboard.py`

- Links: Recognition JE, Settlement JE, Returns from Receipt, Source SE from JE  

### 6.16 Client JS

**stock_entry_type_consignment.js:** toggle/enable checks by purpose.  
**stock_entry_consignment.js:**

- Show party / consignment sections when flags set  
- Buttons: Create Recognition / View JE / Create Settlement / View Settlement / Create Return  
- `set_query` for receipt links  
- Read-only `basic_rate` on return  
- Hide/disable Additional Cost section for consignment  
- Fetch Settings default warehouse / cost center  

---

## 7. Recognition-before-return enforcement (L1)

On Consignment Return `validate` / `before_submit`:

1. If `has_receipt_reference`: every referenced receipt must have `custom_consignment_recognition_je` pointing to a **submitted** (`docstatus=1`) Journal Entry with role Recognition (or verified link).  
2. If return without reference (policy allowed): still require…  
   - **Locked decision L1 says any Consignment Return requires a submitted Recognition JE.**  
   - Therefore returns without receipt reference are either:  
     - **Disallowed in 3.8.0**, or  
     - Allowed only if a recognition path exists (contradiction).  

**Plan resolution for 3.8.0:**  
Because L1 requires recognition before **any** return, **return without receipt reference is deferred / disabled** unless product later defines how recognition works without a receipt. Keep Settings checkbox hidden/unused or force `allow_return_without_receipt_reference = 0` and validate always off.

Document this explicitly in release notes.

---

## 8. Implementation phases (code order)

| Phase | Deliverable | Exit gate |
| --- | --- | --- |
| **P0** | Module + Settings DocType + custom fields patch + hooks wiring (no-op early returns) + `modules.txt` | migrate OK; Settings save validations |
| **P1** | Stock Entry Type flags + receipt validate (party, rates, expense_account, no additional costs) + status | Receipt GL = Dr Inv / Cr Temp; tests CFG/RCV/PTY |
| **P2** | Recognition service + buttons + JE links + cancel guards on receipt | REC tests; cancel matrix start |
| **P3** | Return with reference + L1 recognition check + returnable qty + rate lock + no additional costs | RET tests including block without recognition |
| **P4** | Settlement service (`D = A - R` both signs) + buttons + cancel guards | SET Scenario A/B |
| **P5** | Dashboard, permissions polish, regression vs iran_accounting | REG suite |
| **P6** | Version `3.8.0`, release notes, final migrate dry-run | Release checklist |

Do not enable “return without reference” in P3–P6 under L1.

---

## 9. Test sequence

Run after each phase; full suite before release.

### 9.1 Order

1. `test_consignment_config.py` — Settings accounts, SET flags  
2. `test_consignment_party.py` — Supplier/Customer/invalid flows  
3. `test_consignment_receipt.py` — rates, GL pairing, additional costs blocked  
4. `test_consignment_recognition.py` — JE directions, duplicates, draft  
5. `test_consignment_return.py` — **must fail without recognition**; qty; rate lock  
6. `test_consignment_settlement.py` — `D>0`, `D<0`, `D=0`, balance  
7. `test_consignment_cancellation.py` — dependency order  
8. `test_consignment_regression.py` — standard SE + iran_accounting contract  
9. `test_consignment_permissions.py` — role gates  

### 9.2 Critical assertions (must not skip)

| ID | Assertion |
| --- | --- |
| L1-T | Creating/submitting Consignment Return without submitted Recognition JE → throw |
| L2-T | Customer uses Receivable; Supplier uses Payable on JE party line |
| L3-T | `D = A - R`; Diff Dr when A>R; Diff Cr when A<R |
| L4-T | Consignment SE with `additional_costs` → throw |
| GL-T | Receipt/Return GL via expense_account forcing; no duplicate inventory JE |
| REG-T | Non-consignment Material Receipt/Issue/Transfer unchanged |

### 9.3 Suggested command

```bash
bench --site <site> run-tests --app erpnext_extensions \
  --module erpnext_extensions.consignment_stock.tests
```

---

## 10. Release checklist (3.8.0)

- [ ] Design docs unchanged in intent; this plan approved  
- [ ] P0–P5 merged with tests green  
- [ ] `__version__ = "3.8.0"`  
- [ ] `patches.txt` includes custom fields patch  
- [ ] `modules.txt` includes Consignment Stock  
- [ ] Release notes: Settings COA, party Dynamic Link, recognition-before-return, no additional costs, settlement formula, cancellation order  
- [ ] Confirm no Company/Stock Settings consignment account fields  
- [ ] Confirm no new broad monkey patch shipped  
- [ ] Manual smoke: Receipt → Recognition (submit) → Return → Settlement (A≠R both ways)  

---

## 11. Open points for final implementation approval

1. Confirm **return without receipt reference is out of scope for 3.8.0** under L1 (recommended).  
2. Confirm draft-first JE remains default.  
3. Confirm Dashboard overrides in 3.8.0 vs follow-up.  
4. Confirm whether Finance Book default is written onto JE header when set.  
5. Approve P0→P6 sequencing and file list above.  

**Stop — wait for final implementation approval before writing production code.**
