# Material Loan — Accounting Matrix (Revised)

**Application:** `erpnext_extensions`  
**Target release:** `3.8.1`  
**Status:** Design revised — Party JE model; **Party account mapping decision pending approval**  
**Date:** 2026-08-01  

---

## 1. Accounting principle

Material Loan is **not** a sale or purchase.

- Stock movements reclassify inventory through **Material Loan Temporary Clearing**.  
- Party monetary exposure is created/cleared only via **Recognition** and **Settlement** Journal Entries.  
- Party accounts are **dedicated Material Loan mappings**, not default Debtors/Creditors.  
- Cost center / finance book: from source Stock Entry only (same as inbound 3.8.0).  
- Warehouse accounts: standard ERPNext warehouse-map (`enable_item_wise_inventory_account = 0`).

---

## 2. Required lifecycle (GL)

| Step | Document | Debit | Credit | Amount |
| --- | --- | --- | --- | --- |
| A | Material Loan Issue SE | Material Loan Temporary Clearing | Source Warehouse Stock | Actual outgoing SLE valuation |
| B | Recognition JE | Material Loan Party Account + Party | Temporary Clearing | Full submitted Issue value |
| C | Material Loan Return SE | Target Warehouse Stock | Temporary Clearing | Frozen issue rate × returned qty (= A_return) |
| D | Settlement JE | Temporary Clearing (A) ± Diff | Party (R) | R = frozen settlement value; D = A − R |

After full issue + full return + all JEs submitted with A = R:

- Warehouse restored  
- Temporary Clearing = 0  
- Party Material Loan balance = 0  
- No income/expense residual  

---

## 3. Stock Entry GL mechanism (no SE class override)

| Document | Force `expense_account` | Resulting perpetual pair |
| --- | --- | --- |
| Issue (Material Issue) | Material Loan Temporary Clearing | Dr Temp / Cr Warehouse |
| Return (Material Receipt) | Material Loan Temporary Clearing | Dr Warehouse / Cr Temp |

Same safe pattern as inbound Temporary Clearing force. No new GL monkey patch.

---

## 4. Journal Entry design

### 4.1 Recognition (draft-first)

```text
Dr Material Loan Party Account     Issue value   (party_type, party)
Cr Material Loan Temporary Clearing  Issue value
```

- Created from submitted Issue; linked on Issue `custom_material_loan_recognition_je`.  
- JE `custom_material_loan_je_role = Recognition`.  
- **Never** set `reference_type = Stock Entry` on party (or any) JE lines → avoids PLE `against_voucher = Stock Entry` cancel locks (proven inbound 3.8.0).  
- Traceability: `user_remark`, custom SE↔JE links only.

### 4.2 Settlement (draft-first, per Return)

```text
Dr Temporary Clearing     A     (actual return stock value from Return SE)
Cr Party Account          R     (frozen issue settlement for returned qty)
± Diff Account            D     where D = A − R
```

Balanced forms:

| Case | Settlement lines |
| --- | --- |
| D = 0 | Dr Temp A / Cr Party R (A = R) |
| D > 0 | Dr Temp A / Cr Party R / Cr Diff D *(wait — need balance)* |

Correct balanced settlement (mirror inbound structure, signs flipped for outbound party direction):

Inbound settlement clears a **credit** party balance with Dr Party.  
Outbound settlement clears a **debit** party balance with Cr Party.

**Recommended Settlement JE (Material Loan):**

| Line | Account | Debit | Credit |
| --- | --- | --- | --- |
| 1 | Temporary Clearing | A | |
| 2 | Party Material Loan Account | | R |
| 3a | Valuation Difference (if D > 0) | | D |
| 3b | Valuation Difference (if D < 0) | \|D\| | |

Check: A = R + D, so Dr A = Cr R + Cr D (or Dr A + Dr \|D\| = Cr R when D < 0).

When D < 0 (A < R):

| Line | Debit | Credit |
| --- | --- | --- |
| Temporary Clearing | A | |
| Valuation Difference | \|D\| | |
| Party | | R |

When D > 0 (A > R):

| Line | Debit | Credit |
| --- | --- | --- |
| Temporary Clearing | A | |
| Party | | R |
| Valuation Difference | | D |

### 4.3 Gates

- Duplicate active Recognition JE blocked.  
- Duplicate active Settlement JE per Return blocked.  
- Return SE blocked until Issue Recognition JE is **submitted**.  
- Return is “settled” only when its Settlement JE is **submitted**.  
- Physical Fully Returned ≠ accounting Settled until all return Settlements submitted.

---

## 5. Party account model — ERPNext 16 findings

### 5.1 Hard platform rules

1. `Journal Entry.validate_party`: for Receivable/Payable accounts, `Party Type.account_type` **must equal** `Account.account_type` (Employee exempt).  
2. Error: `Account {1} and Party Type {2} have different account types`.  
3. Fixtures: Customer → Receivable; Supplier → Payable.  
4. `get_party_account(Supplier)` → default **Payable** (Creditors) — unsuitable as Material Loan default.  
5. PLE is created for every Receivable/Payable GL line on JE submit; if JE party line has `reference_type=Stock Entry`, PLE points at SE and **blocks SE cancel**.

### 5.2 Option comparison (Supplier owes us for loaned materials)

| Option | GL | Party Ledger | PLE | AR/AP reports | Complexity | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| **A. Supplier on dedicated Receivable** | Blocked by JE validate | — | — | — | Low but invalid | **Reject** |
| **B. Common Party Accounting** | SI/PI offset only | Needs Customer mirror | Normal JE PLE | Mixes with trade via CPA | High | **Reject as primary** |
| **C. Custom Party Type + DocType (Receivable)** | Valid if PT=Receivable | Separate master | PLE on JE | Not in standard Customer AR | High / upgrade risk | **Possible future** |
| **D. Operational only** | No party GL | — | None | — | Low | **Business-rejected** |
| **E. Party Type → Account map; account_type matches Party Type** | Valid | Customer on Receivable; Supplier on Payable (dedicated) | PLE against **JE** only | Separate Material Loan reports | Medium | **Recommend** |

### 5.3 Recommended model (E) — child table mapping

**Settings child table: Material Loan Party Account**

| Field | Rule |
| --- | --- |
| Party Type | Unique per Settings (company) |
| Account | Same company; enabled; not group; currency OK |
| Account.account_type | **Must equal** Party Type.account_type |

**Customer handling**

- Map Customer → dedicated **Receivable** account, e.g. `Material Loan Receivable - Customer`.  
- **Do not** use Company `default_receivable_account` / Customer Debtors.  
- Recognition: Dr this account + Customer / Cr Temp.  
- Appears on Customer Party Ledger and AR tools for that account only — isolate via dedicated account + Material Loan reports.

**Supplier handling**

- Map Supplier → dedicated **Payable** account, e.g. `Material Loan with Suppliers` (account_type = Payable).  
- **Do not** use Company `default_payable_account` / trade Creditors.  
- Recognition: **Dr** this Payable account + Supplier / Cr Temp → debit balance = materials held by supplier (ERPNext-native “supplier owes us / advance-like” presentation).  
- Settlement: Cr Party R (clears debit).  
- Appears on Supplier Party Ledger under the dedicated Payable account — **not** mixed with trade AP if mapping is enforced.  
- UI label: “Material Loan Party Account” (not forced “Receivable” for Supplier).

**Other Party Types**

- Same rule: account_type must match Party Type (Receivable or Payable).  
- One mapping row per Party Type per company.

**Why not one common Receivable for Customer and Supplier?**  
ERPNext forbids Supplier on Receivable. One account cannot serve both Party Types.

### 5.4 Explicit answers to design questions

| # | Question | Answer |
| --- | --- | --- |
| 1 | One Receivable for Customer + Supplier? | **No** — platform forbids Supplier on Receivable |
| 2 | Supplier on Receivable account? | **No** — JE throws account type mismatch |
| 3 | Separate accounts by Party Type? | **Yes** — required |
| 4 | Child table Party Type → Account? | **Yes — preferred** |
| 5 | PLE behavior | PLE created on JE submit for party lines; against_voucher = JE if no reference |
| 6 | Avoid invalid SE refs | Never set `reference_type=Stock Entry` on JE lines; use custom links + remarks |
| 7 | Distinguish from commercial invoices | Dedicated accounts + JE role + Material Loan reports; never use default trade AR/AP |

---

## 6. Valuation and Difference

### 6.1 Base rule

Return SE forces frozen original issue rate → intended **A = R**.

### 6.2 Is Difference Account still required?

| Source of A ≠ R | Likelihood if freeze enforced |
| --- | --- |
| User rate override | Blocked |
| Current warehouse MA | Not used |
| Rounding / currency precision | Possible (small) |
| Batch/serial SLE vs forced basic_rate edge | Possible |
| Repost after returns | Blocked by policy; if bypassed, A may drift |

**Recommendation:** Keep **Material Loan Valuation Difference Account** as a **required** Settings field (same pragmatism as inbound 3.8.0). Settlement always computes D = A − R and posts Diff only when D ≠ 0. When freeze works, D = 0 and Diff lines are omitted.

If product owners prefer fewer accounts: make Diff **optional** and **block Settlement** when D ≠ 0 beyond precision — stricter, more support tickets. Prefer required Diff account.

### 6.3 Reposting (unchanged intent)

- No submitted returns: refresh frozen issue rates after allowed RIV.  
- Any submitted return: block Issue valuation mutation / RIV until returns (+ their Settlements) cancelled per § Cancellation.

---

## 7. Numerical examples

### Example 1 — Full issue and return (A = R)

**Issue SE:** 100 × 10,000 = 1,000,000  

| Account | Dr | Cr |
| --- | --- | --- |
| Temporary Clearing | 1,000,000 | |
| Warehouse | | 1,000,000 |

**Recognition JE:**

| Account | Dr | Cr |
| --- | --- | --- |
| Party Material Loan Account | 1,000,000 | |
| Temporary Clearing | | 1,000,000 |

Balances after Recognition: Warehouse −1M inventory; Party loan +1M; Temp 0.

**Return SE:** 100 × 10,000 frozen  

| Account | Dr | Cr |
| --- | --- | --- |
| Warehouse | 1,000,000 | |
| Temporary Clearing | | 1,000,000 |

**Settlement JE (D = 0):**

| Account | Dr | Cr |
| --- | --- | --- |
| Temporary Clearing | 1,000,000 | |
| Party Material Loan Account | | 1,000,000 |

**Final:** Warehouse restored; Temp 0; Party 0; Diff unused.

### Example 2 — Partial returns

Issue 100 × 10,000; Recognition 1,000,000 on Party.

| Event | Qty | Party after Settlement | Temp after full JE cycle for that return | Physical remaining |
| --- | --- | --- | --- | --- |
| After Recognition | — | 1,000,000 Dr | 0 | 100 |
| Return1 + Settlement | 40 | 600,000 Dr | 0 | 60 |
| Return2 + Settlement | 30 | 300,000 Dr | 0 | 30 |

Remaining Party balance = 300,000; remaining qty = 30; warehouse has received 70 × 10,000 back.

### Example 3 — Customer Party

Mapping: Customer → `Material Loan Receivable - Customer` (Receivable).

Recognition: Dr Material Loan Receivable - Customer (Customer X) / Cr Temp.  
Settlement: Dr Temp / Cr Material Loan Receivable - Customer (Customer X).

Standard Customer Debtors unchanged.

### Example 4 — Supplier Party

Mapping: Supplier → `Material Loan with Suppliers` (Payable) — **not** trade Creditors.

Recognition: Dr Material Loan with Suppliers (Supplier Y) / Cr Temp.  
→ Supplier Party Ledger shows **debit** on dedicated Payable account = value of our materials held by Y.

Settlement: Dr Temp / Cr Material Loan with Suppliers (Supplier Y).

**ERPNext validation:** Valid because Party Type Supplier (Payable) matches account_type Payable.  
**Invalid:** Supplier + any Receivable account → `Account … and Party Type Supplier have different account types`.

### Example 5 — D ≠ 0 (illustrative)

Return posts A = 1,000,100; R = 1,000,000; D = 100.

Settlement:

| Account | Dr | Cr |
| --- | --- | --- |
| Temporary Clearing | 1,000,100 | |
| Party | | 1,000,000 |
| Valuation Difference | | 100 |

If A = 999,900; R = 1,000,000; D = −100:

| Account | Dr | Cr |
| --- | --- | --- |
| Temporary Clearing | 999,900 | |
| Valuation Difference | 100 | |
| Party | | 1,000,000 |

---

## 8. Cancellation accounting order

See Solution Design. After full reverse cancel: Party 0, Temp 0, warehouse restored, no orphan PLE against Stock Entry.

---

## 9. Compatibility assumption

`Company.enable_item_wise_inventory_account = 0` — unchanged.
