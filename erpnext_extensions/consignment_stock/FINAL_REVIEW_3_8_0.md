# Final Accounting & Migration Review — erpnext_extensions 3.8.0

**Status:** Review completed — **do not commit until stakeholders acknowledge findings**  
**Date:** 2026-07-31  
**Evidence artifact:** `FINAL_REVIEW_3_8_0_EVIDENCE.json` (live site run)  
**Evidence runner:** `final_review_evidence.py`

---

## Finding that required a fix before commit

### Payment Ledger vs `reference_type = Stock Entry`

**Problem (observed):** Putting `reference_type=Stock Entry` / `reference_name=<SE>` on **party** Journal Entry Account rows caused ERPNext to create `Payment Ledger Entry` rows with `against_voucher_type=Stock Entry`. After JE cancel, Stock Entry cancel still failed with “linked with Payment Ledger Entry”.

**Fix applied (pre-commit):** Recognition and Settlement builders **no longer set** `reference_type` / `reference_name` on any JE account row. Links are preserved via:

- Stock Entry → `custom_consignment_recognition_je` / `custom_consignment_settlement_je`
- Journal Entry → `custom_consignment_je_role` + `user_remark` containing SE name

**Property Setter** that adds Stock Entry to `Journal Entry Account.reference_type` options remains (patch + after_migrate) for optional non-party use, but **must not** be used on Receivable/Payable party lines.

**Re-test:** Cancellation reverse order now succeeds; `ple_clean=true` (no active PLE against Stock Entry for the review JEs).

---

## 1. GL Entry evidence (live)

Accounts used on site `development.localhost` (company `test`):

| Role | Account | Source |
| --- | --- | --- |
| Warehouse / Inventory | Resolved from Consignment Warehouse (`Warehouse.account`) | Standard ERPNext |
| Temporary Clearing | Configured on Consignment Stock Settings | Settings |
| Valuation Difference | Configured on Consignment Stock Settings | Settings |
| Party (Supplier) | `get_party_account` | ERPNext party |

**Settings fields (approved):** Temporary Clearing, Valuation Difference, Default Consignment Warehouse, Allow Zero Receipt Rate.  
**Removed from Settings:** `consignment_inventory_account`, `default_cost_center`, `default_finance_book`.

### 1.1 Consignment Receipt — 100 × 10,000 = 1,000,000

**Document:** Stock Entry (Material Receipt, consignment)

| Account | Debit | Credit |
| --- | --- | --- |
| Consignment Inventory | 1,000,000 | |
| Temporary Clearing | | 1,000,000 |

**Balances after receipt**

| Account | Net |
| --- | --- |
| Inventory | Dr 1,000,000 |
| Temporary Clearing | Cr 1,000,000 |
| Party | 0 |

### 1.2 Recognition Journal Entry — draft then submitted

| Account | Debit | Credit | Party |
| --- | --- | --- | --- |
| Temporary Clearing | 1,000,000 | | |
| Creditors (Payable) | | 1,000,000 | Supplier |

`reference_type` on lines: **empty** (by design after PLE fix).  
`custom_consignment_je_role` = `Recognition`.

**Balances after recognition**

| Account | Net |
| --- | --- |
| Inventory | Dr 1,000,000 |
| Temporary Clearing | **0** |
| Party Payable | Cr 1,000,000 |

### 1.3 Scenario A — Return valuation higher (A = 1,200,000)

Setup: same item, Moving Average; second consignment receipt 100 × 14,000 into same warehouse → MA = 12,000. Return 100 against original receipt (R = 1,000,000).

**Return Stock Entry GL**

| Account | Debit | Credit |
| --- | --- | --- |
| Temporary Clearing | 1,200,000 | |
| Consignment Inventory | | 1,200,000 |

**Settlement JE** (`D = A − R = 200,000`)

| Account | Debit | Credit |
| --- | --- | --- |
| Party Payable | 1,000,000 | |
| Valuation Difference | 200,000 | |
| Temporary Clearing | | 1,200,000 |

**Balances of settlement voucher**

| Account | Net on JE |
| --- | --- |
| Party | Dr 1,000,000 (clears Cr 1,000,000 from recognition for this receipt) |
| Diff | Dr 200,000 |
| Temp | Cr 1,200,000 (clears Dr 1,200,000 from return SE) |

### 1.4 Scenario B — Return valuation lower (A = 800,000)

Setup: MA pulled to 8,000 via second receipt 100 × 6,000. Return 100; R = 1,000,000; D = −200,000.

**Return Stock Entry GL**

| Account | Debit | Credit |
| --- | --- | --- |
| Temporary Clearing | 800,000 | |
| Consignment Inventory | | 800,000 |

**Settlement JE**

| Account | Debit | Credit |
| --- | --- | --- |
| Party Payable | 1,000,000 | |
| Temporary Clearing | | 800,000 |
| Valuation Difference | | 200,000 |

Formula verified live: `valuation_difference = actual_return_valuation_amount - receipt_settlement_amount`.

### 1.5 Lifecycle clearing (conceptual for one receipt fully returned)

After receipt + recognition + return + settlement for that receipt’s qty:

| Account | Residual for that receipt’s R/A |
| --- | --- |
| Inventory (that qty) | Cleared by return SE |
| Temporary Clearing | Cleared by recognition then return/settlement pairing |
| Party | Cleared by settlement debit at R |
| Valuation Difference | Holds only `A − R` |

---

## 2. Property Setter verification

| Check | Result |
| --- | --- |
| Created how? | `ensure_stock_entry_reference_type_option()` via `make_property_setter` inside `ensure_custom_fields()` |
| Patch? | Yes — `patches/post_model_sync/add_consignment_stock_custom_fields.py` (Patch Log present, skipped=0) |
| Fixture? | **No** exported Property Setter fixture; code/patch driven |
| after_migrate? | Yes — `consignment_stock.install.after_migrate` re-runs `ensure_custom_fields()` |
| Meta contains Stock Entry? | **Yes** |
| Migration safe? | **Yes** — `create_custom_fields(..., update=True)` + Property Setter upsert are idempotent |
| New site install? | `bench migrate` → DocType sync (Settings) → post_model_sync patch → after_migrate ensure |

**Operational rule:** Option exists, but consignment JE builders must **not** set Stock Entry on party lines (PLE risk). Documented above.

---

## 3. `custom_consignment_je_role`

| Attribute | Value |
| --- | --- |
| Fieldtype | Select |
| Allowed values | blank, `Recognition`, `Settlement` |
| Mandatory | **No** |
| Read-only | **Yes** |
| no_copy | **Yes** |
| Set by | recognition/settlement services only |

**Why standard `reference_type` / `reference_name` are not enough**

1. They identify a related voucher, not whether the JE is Recognition vs Settlement.  
2. Both JE types would reference Stock Entry → ambiguous for duplicate checks / cancel hooks.  
3. Using them on party lines creates Payment Ledger against Stock Entry (unsafe).  
4. `user_remark` is free text — unsuitable as the only idempotency key.

SE header Link fields remain the primary navigable document relationship.

---

## 4. Cancellation sequence (live)

Documents under test: Receipt → Recognition JE → Return → Settlement JE.

| Attempt | Result |
| --- | --- |
| Cancel Receipt while deps exist | **Blocked** — must cancel Recognition JE first |
| Cancel Return while Settlement submitted | **Blocked** — must cancel Settlement JE first |
| Cancel Settlement JE | **OK** |
| Cancel Return after Settlement cancelled | **OK** |
| Cancel Recognition JE | **OK** |
| Cancel Receipt after deps cleared | **OK** |
| Active PLE against Stock Entry | **None** (`ple_clean=true`) |

**Required reverse order:** Settlement JE → Return SE → Recognition JE → Receipt SE.

---

## 5. Permissions verification

### DocType role matrix (site DocPerm / Custom DocPerm)

| Role | Stock Entry | Journal Entry | Consignment Stock Settings |
| --- | --- | --- | --- |
| Stock User | create/write/submit/cancel | **none** | none |
| Stock Manager | create/write/submit/cancel | none | read |
| Accounts User | none | create/write/submit/cancel | **read** |
| Accounts Manager | none | create/write/submit/cancel | create/write |
| System Manager | (via other perms) | | create/write/delete |

### API gates (`api.py`)

`create_consignment_recognition_entry` / `create_consignment_return_settlement` require:

- `Stock Entry` **write**
- `Journal Entry` **create**

**Implication:** A pure Stock User cannot create recognition/settlement JEs. A pure Accounts User cannot write Stock Entry. Practical desk use needs a user with **both** (e.g. Accounts User + Stock User, or System Manager), matching the intended split of stock ops vs accounting submit of draft JEs.

Settings write: Accounts Manager / System Manager only.

---

## 6. Upgrade migration to 3.8.0

| Check | Evidence |
| --- | --- |
| App version | `3.8.0` |
| Module Def `Consignment Stock` | exists |
| DocType `Consignment Stock Settings` | exists |
| Patch executed | `add_consignment_stock_custom_fields` in Patch Log |
| Custom fields (`custom_consignment%`) | 13 |
| Re-run `ensure_custom_fields()` | count stays 13 — **idempotent** |
| Data migration | None required (greenfield process) |

**Upgrade steps for existing sites on prior erpnext_extensions:**

1. Deploy 3.8.0 code  
2. `bench migrate` (runs custom-field ensure + obsolete Settings field cleanup)  
3. Configure Consignment Stock Settings (Temporary Clearing, Valuation Difference, optional default warehouse)  
4. Ensure Consignment Warehouse has a resolvable Warehouse Account  
5. Create Stock Entry Types with consignment flags  

---

## 7. Review verdict

| Topic | Verdict |
| --- | --- |
| Accounting directions | **Pass** — Receipt / Recognition / Return / Settlement match approved matrix |
| A > R and A < R | **Pass** — live MA evidence 1.2M and 0.8M |
| Property Setter | **Pass** — patch + after_migrate; safe/idempotent |
| JE role field | **Pass** — justified; standard refs insufficient alone |
| Cancellation order | **Pass** after PLE fix |
| Permissions | **Pass** with documented dual-permission API requirement |
| Upgrade | **Pass** — additive, idempotent |

### Residual notes (non-blocking)

1. Default company valuation method on this site is **FIFO**; Moving Average must be set on consignment items (or company) for A≠R scenarios — design already assumes MA support.  
2. Property Setter for Stock Entry in `reference_type` is retained but unused by builders after PLE fix — acceptable; optional cleanup in a later release.  
3. No Desk dashboard in 3.8.0 (locked).  

**Ready for commit after stakeholder acknowledgment of this review and the PLE-related JE reference change.**
