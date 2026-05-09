# Petty Management — manual test scenarios (RC)

Use a development site with **Petty Management** installed and migrated. Numbers are examples; adjust for your chart of accounts.

---

## Scenario A — Basic petty advance (Payment Entry)

1. Create **PM Holder** for an employee and company (dedicated petty cash GL account).
2. Create **PM Request** for **2,000,000** (company currency).
3. Move workflow to **Approved** (per your PM Request workflow).
4. Run **Create Payment Entry** from the request.

**Expected**

- **Payment Entry** only (no Journal Entry fallback).
- **GL:** Dr **Petty Cash Account**, Cr **Bank / Default Bank Account** (standard Pay entry from bank to petty cash).

---

## Scenario B — Expense clearance without invoice (Journal Entry)

1. Create **PM Clearance** with one non-invoice line (e.g. hospitality) for **500,000**.
2. Workflow to **Approved**, then **Submit** clearance.

**Expected GL (single clearance Journal Entry)**

- Dr **Expense Account** (from PM Expense Type) 500,000  
- Cr **Petty Cash Account** 500,000  

**Remaining petty balance** (conceptually): prior balance minus clearance (e.g. if advance was 2,000,000 only, remaining petty cash **1,500,000**).

---

## Scenario C — Purchase Invoice settlement via Journal Entry reference allocation

1. Create **Purchase Invoice** for a supplier with **outstanding 700,000** (submitted, unpaid).
2. Add a **PM Clearance** line with **Purchase Invoice** set to that document.
3. **Allocated Amount** = **700,000** (defaults from line amount / amount plus tax if left blank).
4. **Submit** PM Clearance.

**Expected Journal Entry (same document as other clearance lines)**

- **Debit row:** account = Purchase Invoice **Credit To** (supplier payable), **party_type** = Supplier, **party** = supplier, **reference_type** = Purchase Invoice, **reference_name** = invoice name, debit = allocated amount.
- **Credit row(s):** Cr **Petty Cash Account** for the **total** clearance (expense + tax + all PI allocations combined when mixed).

**Expected result**

- **No Payment Entry** from PM Clearance.
- Purchase Invoice **outstanding reduced** via ERPNext standard Journal Entry invoice reference allocation on the payable line.

---

## Scenario D — Partial Purchase Invoice allocation

1. **Purchase Invoice** outstanding **1,000,000**.
2. **PM Clearance** line: same PI, **Allocated Amount** **400,000**.
3. **Submit** clearance.

**Expected**

- One payable debit line on the clearance **Journal Entry** with reference to the PI for **400,000**.
- Purchase Invoice **outstanding becomes 600,000** (after JE submit if auto-submit is on).

---

## Scenario E — Cancel clearance

1. Open a submitted **PM Clearance** that created a **Journal Entry** (expense-only, PI-only, or mixed).
2. **Cancel** the clearance.

**Expected**

- Linked **Journal Entry** is cancelled.
- **Purchase Invoice** document is **not** cancelled.
- Purchase Invoice **outstanding restored** per ERPNext rules when the JE that referenced the invoice is cancelled.

---

## Scenario F — Control tests

| Check | Expected |
|--------|-----------|
| Submit PM Clearance when **Require Workflow Approval** is enabled | Only when workflow state title is **Approved** (non-empty state). |
| Two active **PM Holders** same company | Cannot share the same **Petty Cash Account**. |
| Request above **Max Balance** | Blocked unless **Allow Negative Balance** in PM Settings is enabled (where applicable). |
| PI line allocation | **Allocated Amount** ≤ **Purchase Invoice** outstanding; outstanding **> 0** at validation time. |
| Duplicate PI on two lines | Same **Purchase Invoice** cannot appear on two lines in one clearance. |
| PM Request funding | **Payment Entry** only; failures surface as errors (no silent JE). |
| PM Clearance posting | **Journal Entry** only (no Payment Entry from clearance). |

---

## Required setup

Prepare the following master data before deep testing:

| Item | Notes |
|------|--------|
| **Company** | Same company on holder, request, clearance, PI. |
| **Default Bank Account** | PM Settings — **Payment Entry** paid-from account for advances. |
| **Petty Cash Account** | Per holder; typically **Current Asset** / Cash-like account. |
| **Expense Accounts** | On **PM Expense Type** (non-invoice clearance lines). |
| **Tax Account** | On expense type if tax lines are used. |
| **Cost Center** | Holder default / expense type / line level as needed. |
| **Supplier** | For PI-backed lines and Purchase Invoices. |
| **Purchase Invoice** | Submitted, correct **Credit To** (payable), outstanding > 0 for settlement tests. |
| **Employee** | Linked to **User** where workflow tests require it. |
| **PM Holder** | Employee + company + petty cash account. |
| **PM Expense Type** | Non-stock, company-valid accounts. |
| **PM Settings** | Bank account, workflow approval, optional auto-submit for JE / PE. |

---

## Out of scope for this RC

Stock item receipt, asset capitalization, multi-currency, advanced tax templates, OCR, BI dashboards, and concurrency locking are **not** part of this release scope.

---

## Notes

- **Architecture:** **PM Request** → **Payment Entry** only for funding. **PM Clearance** → **Journal Entry** only (including Purchase Invoice settlement via **reference_type** / **reference_name** on payable rows, same pattern as **cheque_management** payable / Purchase Invoice lines).
- **Mixed clearance:** One **Journal Entry** combines grouped expense/tax debits, Purchase Invoice payable debits (with invoice references), and **one** petty cash credit for the grand total.
