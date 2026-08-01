# Material Loan — Test Matrix (Revised)

**Application:** `erpnext_extensions`  
**Target release:** `3.8.1`  
**Status:** Design revised for JE + Party model  
**Date:** 2026-08-01  
**Regression baseline:** Inbound Consignment Stock **43** tests must remain green  

---

## 1. Strategy

| Layer | Scope |
| --- | --- |
| Config / mapping | Settings, Party Type → Account, flag exclusion |
| Stock | Issue / Return qty, freeze, warehouses, batch/serial |
| Journal | Recognition / Settlement draft-first, D = A − R |
| Ledgers | Party GL, PLE against JE not SE, no trade AR/AP defaults |
| Cancellation | Ordered reverse; orphan links |
| Regression | Inbound 43 + standard SE purposes |

---

## 2. Configuration

| ID | Case | Expect |
| --- | --- | --- |
| ML-CFG-01 | Missing Temporary Clearing | Error on loan SE |
| ML-CFG-02 | Temp account is Stock / warehouse-linked | Error |
| ML-CFG-03 | Missing Party Type mapping | Error on Recognition |
| ML-CFG-04 | Mapping account wrong company / group / disabled | Error |
| ML-CFG-05 | Mapping account_type ≠ Party Type.account_type | Error |
| ML-CFG-06 | Map Customer to company default Debtors | Rejected |
| ML-CFG-07 | Map Supplier to company default Creditors | Rejected |
| ML-CFG-08 | Duplicate Party Type rows | Error |
| ML-CFG-09 | SET loan + inbound flags together | Error |
| ML-CFG-10 | Missing Diff account when required | Error on Settlement if policy requires |

---

## 3. Issue

| ID | Case | Expect |
| --- | --- | --- |
| ML-ISS-01 | Single item Issue GL | Dr Temp / Cr Warehouse |
| ML-ISS-02 | Multi item / multi warehouse | Correct accounts |
| ML-ISS-03 | Freeze rate from SLE | Stored on detail |
| ML-ISS-04 | Additional Costs | Blocked |
| ML-ISS-05 | Missing party | Error |
| ML-ISS-06 | Batch / serial | OK |
| ML-ISS-07 | Cancel Issue before Recognition | Allowed |

---

## 4. Recognition JE

| ID | Case | Expect |
| --- | --- | --- |
| ML-REC-01 | Customer Recognition | Dr mapped Receivable + Customer / Cr Temp |
| ML-REC-02 | Supplier Recognition | Dr mapped Payable + Supplier / Cr Temp |
| ML-REC-03 | Draft-first | docstatus 0 on create |
| ML-REC-04 | Duplicate active Recognition | Blocked |
| ML-REC-05 | Amount = Issue frozen value | Match |
| ML-REC-06 | No reference_type Stock Entry on lines | Assert empty |
| ML-REC-07 | After submit: recognition_status Recognized | OK |
| ML-REC-08 | PLE exists against JE not SE | Assert |
| ML-REC-09 | Reject creating Recognition with Supplier mapped to Receivable | Mapping/validate error |

---

## 5. Return

| ID | Case | Expect |
| --- | --- | --- |
| ML-RET-01 | Return before Recognition submitted | Blocked |
| ML-RET-02 | Full return | Remaining 0 |
| ML-RET-03 | Partial + multi partial | Remaining correct |
| ML-RET-04 | Over-return | Blocked |
| ML-RET-05 | Wrong party / company / item | Blocked |
| ML-RET-06 | Frozen rate forced | A based on freeze |
| ML-RET-07 | Different warehouse policy | Allow/block per setting |
| ML-RET-08 | Return without row reference | Blocked |

---

## 6. Settlement JE

| ID | Case | Expect |
| --- | --- | --- |
| ML-SET-01 | Customer Settlement D = 0 | Dr Temp A / Cr Party R |
| ML-SET-02 | Supplier Settlement D = 0 | Same structure on Payable map |
| ML-SET-03 | Partial Party settlement | Party outstanding decreases by R |
| ML-SET-04 | Multiple returns → multiple Settlements | Independent links |
| ML-SET-05 | Duplicate Settlement | Blocked |
| ML-SET-06 | D &gt; 0 | Cr Diff D; balanced |
| ML-SET-07 | D &lt; 0 | Dr Diff \|D\|; balanced |
| ML-SET-08 | D = 0 | No Diff line |
| ML-SET-09 | No SE reference on party lines | Assert |
| ML-SET-10 | PLE against JE | Assert; SE cancellable after JE cancel |

---

## 7. Party balances

| ID | Case | Expect |
| --- | --- | --- |
| ML-PAR-01 | After full cycle Customer | Party loan account 0 |
| ML-PAR-02 | After partial Customer | Outstanding = remaining × rate |
| ML-PAR-03 | After full cycle Supplier | Dedicated Payable debit cleared |
| ML-PAR-04 | Trade Debtors/Creditors unchanged | No GL on defaults |
| ML-PAR-05 | Invalid use of get_party_account defaults | Not used by services |

---

## 8. Payment Ledger

| ID | Case | Expect |
| --- | --- | --- |
| ML-PLE-01 | Recognition submit creates PLE | against_voucher_type = Journal Entry |
| ML-PLE-02 | Settlement submit creates PLE | against JE |
| ML-PLE-03 | No PLE against Stock Entry | Query empty |
| ML-PLE-04 | SE cancel not blocked by PLE when JE cancelled first | Per cancellation order |

---

## 9. Cancellation

| ID | Case | Expect |
| --- | --- | --- |
| ML-CAN-01 | Cancel Return before Settlement JE | Blocked |
| ML-CAN-02 | Cancel Settlement then Return | OK |
| ML-CAN-03 | Cancel Recognition while Returns exist | Blocked |
| ML-CAN-04 | Full reverse order | Party 0 Temp 0 |
| ML-CAN-05 | Multi partial: each Settlement before its Return | Enforced |
| ML-CAN-06 | No orphan JE links | Cleared |

---

## 10. Valuation / repost

| ID | Case | Expect |
| --- | --- | --- |
| ML-VAL-01 | Freeze refresh without returns | OK |
| ML-VAL-02 | RIV blocked with returns | Error |
| ML-VAL-03 | Example MA change after issue | Return still frozen |

---

## 11. Regression

| ID | Case | Expect |
| --- | --- | --- |
| ML-REG-01 | Inbound 43 tests | All green |
| ML-REG-02 | Standard Material Issue/Receipt | Unchanged |
| ML-REG-03 | Manufacture / Repack | Unchanged |
| ML-REG-04 | iran_accounting non-loan SE | Compatible |
| ML-REG-05 | Migration idempotent | Safe re-run |

---

## 12. Suggested modules

```text
test_material_loan_config.py
test_material_loan_issue.py
test_material_loan_recognition.py
test_material_loan_return.py
test_material_loan_settlement.py
test_material_loan_party_account.py
test_material_loan_ple.py
test_material_loan_cancellation.py
test_material_loan_repost.py
test_material_loan_regression.py
```
