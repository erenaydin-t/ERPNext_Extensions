# Consignment Stock — Accounting Matrix

**Application:** `erpnext_extensions`  
**Target release:** `3.8.0`  
**Status:** Design only — **accounting must be approved before implementation**  
**Date:** 2026-07-31 (revision: open party types + Settings accounts; L1 recognition-before-return locked)

---

## 1. Accounting analysis (contradiction resolution)

### 1.1 Initially requested recognition direction (rejected — unchanged)

| Event | Debit | Credit |
| --- | --- | --- |
| Receipt SE | Consignment Inventory | Temporary Clearing |
| Recognition JE (initial request) | Party | Temporary Clearing |

**Problems:** Temporary Clearing credited twice; party debited incorrectly for “goods held”; settlement cannot clear cleanly.

### 1.2 Recommended recognition direction (unchanged, approved candidate)

| Event | Debit | Credit |
| --- | --- | --- |
| Receipt SE | Consignment Inventory | Temporary Clearing |
| Recognition JE | Temporary Clearing | Party account |

**Rationale:**

- Receipt SE uses **standard ERPNext Material Receipt perpetual inventory pairing**: Debit warehouse inventory account / Credit Difference Account (`items.expense_account`).
- For consignment, Difference Account is forced to **Temporary Clearing** from Consignment Stock Settings.
- Recognition reclassifies the Temporary Clearing credit into a **party balance** so party ledgers show the obligation.
- ERPNext Journal Entry rules: Receivable/Payable accounts require `party_type` + `party`; Party Type’s `account_type` must match the account.

### 1.3 Party types (approved — not Supplier-only)

Use ERPNext Dynamic Link: **Party Type + Party**.

| Party Type (examples) | Typical Party Type `account_type` | Recognition credit effect |
| --- | --- | --- |
| Supplier | Payable | Increases payable (credit balance) — goods held for supplier |
| Customer | Receivable | Creates/increases credit balance on AR — obligation to customer-owner |
| Employee / other configured Party Types | Payable or Receivable per Party Type | Same rule: credit party account of matching type |

**Account resolution:**

```text
party_account = get_party_account(party_type, party, company)
```

Must succeed and match Party Type `account_type`. No restriction that Party Type must be Supplier.

**Validation of “valid accounting flow”:**

1. Party Type has `account_type` ∈ {Payable, Receivable}.
2. Party document exists.
3. Party account resolvable for company.
4. Account.company = transaction company; not group; not disabled.
5. Account.account_type matches Party Type.account_type.
6. JE lines on recognition/settlement set `party_type` and `party`.

**Company as party:** Only if registered as a Party Type with a resolvable account; otherwise reject at validate.

**`reference_type` / `reference_name`:** Stock Entry is not relied on for invoice outstanding allocation. Use custom Link fields on JE + remarks.

**Dedicated party control account:** Optional future enhancement. v3.8.0 resolves the party’s default account via ERPNext; Settings do **not** store a separate default party payable/receivable override unless later approved. Core Settings accounts remain inventory / temporary / valuation difference only (plus cost center / finance book defaults).

---

## 2. Variables and formulas (unchanged)

```text
R  = receipt_settlement_amount
     = Σ (settlement_qty_in_stock_uom × original_receipt_rate_per_stock_uom)
       for referenced returns
     OR Σ (settlement_qty × external_settlement_rate) when no receipt reference

A  = actual_return_valuation_amount
     = absolute value of Stock Entry outgoing stock value for consignment return rows
     (company currency)

D  = valuation_difference
     = A - R
```

**Settlement Journal Entry (always balances):**

```text
Debit  Party account                         = R
Debit  Valuation Difference account          = D    if D > 0
Credit Valuation Difference account          = -D   if D < 0   (i.e. credit |D|)
Credit Temporary Clearing account            = A

Check: R + max(D,0) = A + max(-D,0)
```

When `D = 0`: two-line JE (Party Dr R / Temp Cr A).

Valuation Difference Account is always taken from **Consignment Stock Settings** for the company — never from Company DocType custom fields or Stock Settings.

---

## 3. Event matrix

| Event | Document | Debit Account | Credit Account | Valuation Basis | Party | Reference |
| --- | --- | --- | --- | --- | --- | --- |
| Consignment receipt | Stock Entry (Material Receipt, consignment) | Consignment Inventory (warehouse account) | Consignment Temporary Clearing (`expense_account`) | User-entered receipt rate × qty | Header Party Type + Party (not on SE GL rows) | SE name; warehouse; item rows |
| Party balance recognition | Journal Entry | Consignment Temporary Clearing | Party account (Payable or Receivable per Party Type) | Same as receipt SE total value | Yes — credit party | Link → source Receipt SE |
| Full return (stock) | Stock Entry (Material Issue, consignment) | Consignment Temporary Clearing | Consignment Inventory | Warehouse Moving Average / SLE outgoing rate | Header Party Type + Party | Row → Receipt SE + row |
| Partial return (stock) | Stock Entry (Material Issue, consignment) | Temporary Clearing | Consignment Inventory | Warehouse rate × returned qty only | Header party | Row → Receipt SE + row |
| Return settlement — A > R | Journal Entry | Party (R) + Valuation Difference (D) | Temporary Clearing (A) | Party@receipt rate; Temp@actual | Debit party | Return SE + original Receipt |
| Return settlement — A < R | Journal Entry | Party (R) | Temporary Clearing (A) + Valuation Difference (\|D\|) | Party@receipt rate; Temp@actual | Debit party | Return SE + original Receipt |
| Return settlement — A = R | Journal Entry | Party (R) | Temporary Clearing (A) | Equal amounts | Debit party | Return SE + Receipt |
| Receipt cancellation (no recognition JE) | Cancel Stock Entry | Reverse SE GL (Dr Temp / Cr Inventory) | — | Original receipt amounts | — | Cancelled SE |
| Receipt cancellation (after submitted recognition) | **Blocked** until recognition JE cancelled | — | — | — | — | — |
| Recognition JE cancellation | Cancel Journal Entry | Reverse recognition | — | Original recognition amounts | Cleared | Receipt SE remains submitted |
| Return cancellation (no settlement) | Cancel Stock Entry | Reverse return GL | — | Original return amounts | — | — |
| Return cancellation (after settlement) | **Blocked** until settlement JE cancelled | — | — | — | — | — |
| Settlement JE cancellation | Cancel Journal Entry | Reverse settlement | — | Original settlement amounts | Restores party / temp / diff | Return SE remains submitted |
| Return without receipt ref (stock) | Stock Entry Issue | Temporary Clearing | Inventory | Warehouse rate | Header party | External rate stored on rows |
| Settlement without receipt ref | Journal Entry | Party (R from external rate) ± Diff | Temporary Clearing (A) | External rate vs actual | Debit party | Return SE + external remark |

---

## 4. Numerical lifecycle examples

Assumptions: company currency amounts use ERPNext precision APIs (IRR sites often precision 0). Examples use Party Type = Supplier **or** Customer interchangeably for amounts; only the party account type changes.

### 4.1 Full cycle — return valuation higher than receipt (Scenario A)

**Receipt:** 10 kg @ 100 = **1,000**  
**Party:** any valid accounting party (e.g. Supplier *or* Customer)

| Step | Dr | Cr | Amount |
| --- | --- | --- | --- |
| Receipt SE | Inventory | Temporary Clearing | 1,000 |
| Recognition JE | Temporary Clearing | Party account | 1,000 |

Balances after recognition:

| Account | Balance |
| --- | --- |
| Inventory | Dr 1,000 |
| Temporary Clearing | 0 |
| Party account | Cr 1,000 |

**Return:** 10 kg; warehouse MA rate 120 → **A = 1,200**; **R = 1,000**; **D = 200**

| Step | Dr | Cr | Amount |
| --- | --- | --- | --- |
| Return SE | Temporary Clearing | Inventory | 1,200 |
| Settlement JE | Party account |  | 1,000 |
| Settlement JE | Valuation Difference (from Settings) |  | 200 |
| Settlement JE |  | Temporary Clearing | 1,200 |

Final balances:

| Account | Balance |
| --- | --- |
| Inventory | 0 |
| Temporary Clearing | 0 |
| Party account | 0 |
| Valuation Difference | Dr 200 |

### 4.2 Full cycle — return valuation lower than receipt (Scenario B)

**Receipt:** same 10 @ 100 = 1,000; recognized against party account.

**Return:** warehouse rate 80 → **A = 800**; **R = 1,000**; **D = -200**

| Step | Dr | Cr | Amount |
| --- | --- | --- | --- |
| Return SE | Temporary Clearing | Inventory | 800 |
| Settlement JE | Party account |  | 1,000 |
| Settlement JE |  | Temporary Clearing | 800 |
| Settlement JE |  | Valuation Difference (from Settings) | 200 |

Final balances:

| Account | Balance |
| --- | --- |
| Inventory | 0 |
| Temporary Clearing | 0 |
| Party account | 0 |
| Valuation Difference | Cr 200 |

### 4.3 Same lifecycle with Customer as owner

Amounts identical to §4.1 / §4.2.

| Step | Party account behavior |
| --- | --- |
| Recognition Cr Customer Receivable | Credit balance on AR (obligation to customer-owner) |
| Settlement Dr Customer Receivable | Clears that credit balance |

No change to Inventory / Temporary Clearing / Valuation Difference postings.

### 4.4 Partial return then remainder

Receipt 10 @ 100 = 1,000; recognized for party (Supplier or Customer).

**Partial return 4 kg**, warehouse rate 110 → A₁ = 440; R₁ = 400; D₁ = 40

| Settlement 1 | Dr Party 400 | Dr Diff 40 | Cr Temp 440 |

**Final return 6 kg**, suppose MA 105 → A₂ = 630; R₂ = 600; D₂ = 30 → settle similarly until party balance is zero.

**Note:** Dedicated consignment warehouse recommended so Moving Average is not polluted by owned stock.

### 4.5 Why recognition must precede return and settlement (locked)

**L1:** A submitted Recognition JE is mandatory before any Consignment Return Stock Entry. Without recognition, return SE + settlement template leave Temporary Clearing and Party uncleared/inverted.

Return without receipt reference is **out of scope for 3.8.0** under L1.

---

## 5. Integration with standard ERPNext Stock Entry GL

### 5.1 Material Receipt / Issue (core)

Unchanged: inventory ↔ `expense_account` pairing from SLE / iran_accounting row movement.

### 5.2 Consignment strategy (no duplicate GL)

1. Warehouse → Consignment Inventory (aligned with Settings inventory account validation).
2. Force `items.expense_account` = Settings Temporary Clearing.
3. Manual `basic_rate` drives receipt valuation.
4. Recognition / settlement are **separate JEs**, not SE GL.

### 5.3 Avoid

| Anti-pattern | Why |
| --- | --- |
| Leaving Difference Account as Company `stock_adjustment_account` | Incorrect P&L |
| Storing Valuation Difference on Company or Stock Settings | Violates approved configuration boundary |
| Restricting Party Type to Supplier only | Rejected — owners may be Customer or other accounting parties |
| Posting party on Stock Entry GL rows | Not standard SE GL |
| Double-posting inventory via JE | Duplicates perpetual inventory |

---

## 6. Resulting balances after receipt + recognition

| Account | After receipt SE | After recognition JE |
| --- | --- | --- |
| Consignment Inventory | Debit R | Debit R |
| Temporary Clearing | Credit R | **Zero** |
| Party account | — | **Credit R** |

**Party balance:** Credit obligation regardless of Supplier vs Customer (Payable credit or Receivable credit balance).

**Initial recognition:** Party is **credited** (not debited).

---

## 7. Clearing on return + settlement

| Account | Cleared by |
| --- | --- |
| Consignment Inventory | Return Stock Entry credit |
| Temporary Clearing | Return SE debit + Settlement JE credit |
| Party account | Settlement JE debit at receipt/external rate |
| Residual economics | Valuation Difference (Settings) only |

---

## 8. Cancellation GL effects

Unchanged dependency order: cancel settlement before return; cancel recognition before receipt; cancel returns before receipt when qty consumed; JE-only cancel allowed with link clear.

---

## 9. Multi-company, dimensions, currency

| Topic | Rule |
| --- | --- |
| Company | SE company owns Settings row and all accounts |
| Cost centers | Default from Settings when missing; copy to JE when required |
| Finance Book | Optional default from Settings onto JE |
| Accounting dimensions | Copy from SE |
| Currency | v1: company currency; party account currency per ERPNext JE rules |

---

## 10. Explicit answers to design questions

1. **Recommended entries:** Receipt Dr Inv / Cr Temp; Recognition Dr Temp / Cr Party; Return Dr Temp / Cr Inv; Settlement Dr Party (± Diff) / Cr Temp.  
2. **Balances after receipt+recognition:** Inventory Dr, Temp 0, Party Cr.  
3. **Party balance:** Credit obligation (Payable or Receivable credit).  
4. **Cleared on return:** Inventory by SE; Temp & Party by settlement; Diff retains economic difference.  
5. **Initial recognition:** Party **credited**.  
6. **Dedicated payable/receivable control account:** Not required in Settings for v3.8.0; use party’s resolved account.  
7. **ERPNext party fields:** `party_type` + `party` mandatory on Receivable/Payable JE lines; Dynamic Link on Stock Entry; validate resolvable accounting flow.

---

## 11. Approval-needed remaining points

1. Exact COA roots for Temporary Clearing and Valuation Difference.  
2. Whether `require_recognition_before_return` is hard-block (default still 0 unless approved otherwise).  
3. Rounding aggregation (header-level R/A/D — recommended).  
4. Block Item Repost when settlement exists (recommended).
