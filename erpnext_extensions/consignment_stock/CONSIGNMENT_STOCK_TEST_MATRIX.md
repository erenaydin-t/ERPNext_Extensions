# Consignment Stock — Test Matrix

**Application:** `erpnext_extensions`  
**Target release:** `3.8.0`  
**Status:** Design only — implement tests with feature phases  
**Date:** 2026-07-31 (revision: open party types + Settings accounts + 3.8.0)

Legend: **P** = pytest/unit integration · **UI** = desk/JS · **E2E** = optional Playwright later

---

## 1. Configuration tests

| ID | Case | Expected | Type |
| --- | --- | --- | --- |
| CFG-01 | Valid Settings accounts for company | Save OK | P |
| CFG-02 | Temporary Clearing from another company | Throw | P |
| CFG-03 | Group account selected | Throw | P |
| CFG-04 | Disabled account | Throw | P |
| CFG-05 | Missing Temporary Clearing on consignment submit | Throw | P |
| CFG-06 | Missing Valuation Difference on settlement create | Throw | P |
| CFG-07 | Inventory account valid | Save OK | P |
| CFG-08 | Temporary Clearing with account_type Stock | Throw / warn per policy | P |
| CFG-09 | Valuation Difference only on Settings (not read from Company/Stock Settings) | Resolve from Settings | P |
| CFG-10 | Default Cost Center / Finance Book optional save | OK | P |
| CFG-11 | SET: `is_consignment_receipt` on Material Issue | Throw | P |
| CFG-12 | SET: `is_consignment_return` on Material Receipt | Throw | P |
| CFG-13 | SET: both consignment checks | Throw | P |
| CFG-14 | SET: valid receipt / return flags | Save OK | P |
| CFG-15 | Warehouse account mismatches Settings inventory (if enforced) | Throw / warn | P |

---

## 2. Party accounting-flow tests

| ID | Case | Expected | Type |
| --- | --- | --- | --- |
| PTY-01 | Supplier with resolvable Payable account | Receipt OK | P |
| PTY-02 | Customer with resolvable Receivable account | Receipt OK | P |
| PTY-03 | Other Party Type with valid account_type + account | Receipt OK | P |
| PTY-04 | Party Type without Payable/Receivable account_type | Throw | P |
| PTY-05 | Party missing company party account | Throw | P |
| PTY-06 | Party account wrong company | Throw | P |
| PTY-07 | Disabled party account | Throw | P |
| PTY-08 | account_type mismatch vs Party Type | Throw | P |
| PTY-09 | Missing Party Type or Party on consignment SE | Throw | P |
| PTY-10 | Return party differs from receipt party | Throw | P |
| PTY-11 | Recognition JE sets party_type + party on party line | Present | P |
| PTY-12 | Settlement JE debits same party | Clears credit | P |
| PTY-13 | Customer recognition creates Receivable credit balance | Party Cr | P |
| PTY-14 | Supplier recognition creates Payable credit balance | Party Cr | P |

---

## 3. Receipt tests

| ID | Case | Expected | Type |
| --- | --- | --- | --- |
| RCV-01 | Single item receipt | SLE in; GL Dr Inv / Cr Temp | P |
| RCV-02 | Multiple items | Per-row rates; summed GL | P |
| RCV-03 | Multiple warehouses | Per warehouse inventory | P |
| RCV-04 | Manual rates preserved | `basic_rate` unchanged | P |
| RCV-05 | Missing rate | Throw | P |
| RCV-06 | Zero rate (allow_zero=0) | Throw | P |
| RCV-07 | Zero rate (allow_zero=1) | Allow | P |
| RCV-08 | UOM conversion | Correct stock UOM rate snapshot | P |
| RCV-09 | Batch item | Standard batch rules | P |
| RCV-10 | Serial item | Standard serial rules | P |
| RCV-11 | expense_account forced to Temp from Settings | Equals Settings | P |
| RCV-12 | User tries stock_adjustment as difference | Overwritten or throw | P |
| RCV-13 | Receipt cancellation without JE | Reversed | P |
| RCV-14 | Backdated receipt | Correct posting_date / MA | P |
| RCV-15 | Additional costs present | Throw | P |
| RCV-16 | Auto valuation did not overwrite user rate | P+UI | P+UI |
| RCV-17 | Dimensions / cost centers; Settings default CC applied when empty | Present | P |
| RCV-18 | Status = Receipt Submitted | After submit | P |

---

## 4. Recognition Journal Entry tests

| ID | Case | Expected | Type |
| --- | --- | --- | --- |
| REC-01 | Correct party_type, party, amount | Match receipt total | P |
| REC-02 | Dr Temp / Cr Party | Directions correct | P |
| REC-03 | Duplicate while draft exists | Throw | P |
| REC-04 | Duplicate while submitted exists | Throw | P |
| REC-05 | Draft-first | docstatus 0 | P |
| REC-06 | Auto-submit setting | docstatus 1 | P |
| REC-07 | Cancel recognition JE | Link cleared | P |
| REC-08 | Cancel receipt while submitted recognition | Blocked | P |
| REC-09 | Cancel receipt while draft recognition | Blocked | P |
| REC-10 | Dimensions / Finance Book from Settings default | Copied when applicable | P |
| REC-11 | Supplier party line account_type Payable | OK | P |
| REC-12 | Customer party line account_type Receivable | OK | P |
| REC-13 | Button hidden when JE exists | UI | UI |
| REC-14 | Recreate after cancel JE | Allowed once | P |

---

## 5. Return tests

| ID | Case | Expected | Type |
| --- | --- | --- | --- |
| RET-01 | Full return with reference | GL Dr Temp / Cr Inv @ warehouse rate | P |
| RET-02 | Partial return | Remaining reduced | P |
| RET-03 | Multiple partial returns | Sum ≤ original | P |
| RET-04 | Over-return | Throw | P |
| RET-05 | Multiple receipt rows | Row-level refs | P |
| RET-06 | Without reference (policy off) | Throw | P |
| RET-07 | Without reference (policy on) | External rate required | P |
| RET-08 | Party mismatch | Throw | P |
| RET-09 | Company mismatch | Throw | P |
| RET-10 | Non-consignment / draft / cancelled receipt | Throw | P |
| RET-11 | User cannot edit outgoing basic_rate | Locked | P+UI |
| RET-12 | Warehouse rate = / > / < receipt rate | A vs R cases | P |
| RET-13 | Batch / serial validation | Enforce | P |
| RET-14 | Cancelled prior return excluded | Remaining restored | P |
| RET-15 | expense_account = Temp | Forced | P |
| RET-16 | Consignment Return without submitted Recognition JE | **Always throw (L1)** | P |
| RET-16b | Return when recognition is draft only | Throw | P |
| RET-17 | UOM vs remaining | Stock UOM compare | P |

---

## 6. Settlement tests

| ID | Case | Expected | Type |
| --- | --- | --- | --- |
| SET-01 | Party settlement uses original receipt rate | R correct | P |
| SET-02 | Temp credit uses actual outgoing value | A correct | P |
| SET-03 | A > R → Diff debited from Settings account | Balances | P |
| SET-04 | A < R → Diff credited to Settings account | Balances | P |
| SET-05 | A = R → no Diff (or omitted zero) | Balances | P |
| SET-06 | Diff account never sourced from Company/Stock Settings | Settings only | P |
| SET-07 | Duplicate settlement prevention | Throw | P |
| SET-08 | Cancel settlement then recreate | OK | P |
| SET-09 | Cancel return while settlement submitted | Blocked | P |
| SET-10 | Multiple receipt rates in one return | Σ R_i | P |
| SET-11 | Rounding: JE balanced | debit==credit | P |
| SET-12 | Without recognition when required | Throw | P |
| SET-13 | Without reference uses external rate | R from external | P |
| SET-14 | Supplier and Customer settlement clear party credit | Party 0 | P |
| SET-15 | Numerical Scenario A / B (matrix) | Exact amounts | P |
| SET-16 | Default Finance Book on JE when set | Present | P |

---

## 7. Cancellation / amendment / repost

| ID | Case | Expected | Type |
| --- | --- | --- | --- |
| CXL-01 | Receipt cancel no deps | OK | P |
| CXL-02 | Receipt cancel after returns | Blocked | P |
| CXL-03 | Return cancel no settlement | OK | P |
| CXL-04 | JE cancel only | SE remains | P |
| CXL-05 | Amend receipt with returns | Blocked | P |
| CXL-06 | Repost with active settlement | Blocked / fail | P |
| CXL-07 | Full undo order | settle→return→recog→receipt | P |

---

## 8. Regression tests

| ID | Case | Expected | Type |
| --- | --- | --- | --- |
| REG-01 | Standard Material Receipt | Unchanged | P |
| REG-02 | Standard Material Issue | Unchanged | P |
| REG-03 | Material Transfer / ZVT path | Intact | P |
| REG-04 | Manufacture / Repack | Unchanged | P |
| REG-05 | Purchase Receipt / Stock Reconciliation | Unchanged | P |
| REG-06 | iran_accounting SLE↔GL contract normal SE | Passes | P |
| REG-07 | iran_accounting contract consignment SE | Passes with Temp | P |
| REG-08 | Company DocType has no consignment Valuation Diff custom field dependency | N/A / assert absent usage | P |
| REG-09 | Stock Settings has no consignment account fields dependency | N/A / assert absent usage | P |
| REG-10 | Facility/PDC JE services unaffected | Pass | P |

---

## 9. Permissions / query / UI

| ID | Case | Expected | Type |
| --- | --- | --- | --- |
| PRM-01 | Stock User creates receipt (Supplier or Customer party) | OK | P |
| PRM-02 | Stock User creates recognition | Denied if policy | P |
| PRM-03 | Accounts User creates recognition/settlement | OK | P |
| PRM-04 | Return without ref without manager | Denied | P |
| PRM-05 | Settings write as Stock User | Denied | P |
| QRY-01 | Eligible receipt query: company + party | Filtered | P |
| QRY-02 | Fully returned excluded | Not listed | P |
| QRY-03 | Buttons visibility matrix | Per status | UI |

---

## 10. Suggested automation layout

```text
consignment_stock/tests/
    test_consignment_config.py
    test_consignment_party.py
    test_consignment_receipt.py
    test_consignment_recognition.py
    test_consignment_return.py
    test_consignment_settlement.py
    test_consignment_cancellation.py
    test_consignment_regression.py
    test_consignment_permissions.py
```

Shared fixtures: company with perpetual inventory; Settings accounts; consignment warehouse; Supplier **and** Customer with party accounts; items; Stock Entry Types.

Priority for first merge: CFG-*, PTY-01..09, RCV-01/04/05/11, REC-01/02/03/11/12, RET-01/04/11, SET-03/04/06/11, REG-01/02/03/06.

---

## 11. Exit criteria for 3.8.0

1. P0–P4 automated tests green on ERPNext 16.  
2. Scenario A/B amounts asserted for Supplier and at least one Customer path.  
3. Regression REG-01..03 and REG-06 green.  
4. Manual UI smoke: receipt (Customer) → recognize → partial return → settle.  
5. Release notes include Settings COA checklist, party Dynamic Link, cancellation order.  
6. Confirm Valuation Difference is not introduced on Company or Stock Settings.
