# Petty Management — manual test scenarios (release scope)

This module covers **only**:

1. **Funding** petty cash holders (**PM Request** → **Payment Entry**: Dr Petty Cash, Cr Bank).
2. **Settling submitted Purchase Invoices** from petty cash (**PM Clearance** → **Journal Entry**: Dr PI `credit_to` with Supplier + Purchase Invoice reference, Cr Petty Cash).

Direct employee expense lines and non-invoice settlement are **out of scope**; use **ERPNext HRMS** **Employee Advance** and **Expense Claim** for those.

Use a development site with **Petty Management** installed and migrated. Figures are examples.

---

## PM Request vs PM Clearance (relationship)

| | **PM Request** | **PM Clearance** |
|---|----------------|------------------|
| **Purpose** | Fund the holder’s **Petty Cash Account** | Consume that same account to **settle submitted Purchase Invoices** |
| **Posting** | **Payment Entry** (Dr Petty Cash, Cr Bank per PM Settings) | **Journal Entry** (Dr supplier payable / PI `credit_to`, Cr Petty Cash) |
| **How they connect** | **Not** linked by a child table or dynamic link on the documents. They share the same **PM Holder** and the same **Petty Cash Account** (and thus the same GL balance). | Same |
| **Future** | — | Optional: allow referencing one or more **PM Request** names for audit; **not required** for correct accounting today. |

---

## Prerequisites

| Item | Notes |
|------|--------|
| **Company, Chart of Accounts** | Petty cash asset account on **PM Holder**. |
| **PM Settings** | Default company (optional), **Default Bank Account**, **Default Cost Center** (optional), policies as needed. |
| **Supplier & items** | For **Purchase Invoice**. |

---

## A. Create PM Holder

1. Create **PM Holder** for an **Employee** and **Company** with a **Petty Cash Account** (and optional max balance).
2. Save. Confirm the holder is selectable once **Employee** + **Company** match on **PM Request** / **PM Clearance**.

---

## B. PM Request funds petty cash via Payment Entry

1. Create **PM Request**: choose employee, company, add line(s) with **Advance Amount** only (no expense category required).
2. Approve per workflow (if used).
3. **Create Payment Entry** from the request.
4. Confirm **Payment Entry**: **Paid From** = bank (from PM Settings), **Paid To** = holder petty cash; amounts match **Total Requested Amount**.
5. Confirm petty cash **GL** balance increased.

---

## C. Create Purchase Invoice

1. Create and **submit** a **Purchase Invoice** for the same **Company** (supplier bill you will settle from petty cash).
2. Note **Outstanding Amount** and **Credit To** (payable account).

---

## D. PM Clearance settles Purchase Invoice via Journal Entry reference

1. Create **PM Clearance** (desk label may show **Petty Invoice Settlement**): same employee/company as holder; **Pending Amount** reflects petty cash balance.
2. Add a child line: **Purchase Invoice**, **Allocated Amount** (defaults from PI outstanding), optional **Cost Center**, **Project**, **Bill No**, **Proof**.
3. **Submit** the clearance (this is the settlement request).
4. Move workflow to **Approved** (finance approval).
5. Click **Settle Petty Cash** to create the settlement **Journal Entry** and mark the clearance **Settled**.
6. Open generated **Journal Entry**:
   - For each line: **Debit** = Purchase Invoice **credit_to**, **Party Type** = Supplier, **Party** = supplier, **Reference Type** = Purchase Invoice, **Reference Name** = PI.
   - **Credit** = petty cash account for the sum of allocated amounts.
7. Confirm Purchase Invoice **outstanding** reduced by allocated amount.

---

## E. Partial settlement

1. Use a PI with outstanding **greater** than the petty balance or greater than the amount you wish to clear.
2. On **PM Clearance**, set **Allocated Amount** to **less than** full outstanding (but ≤ petty balance and ≤ PI outstanding).
3. **Submit**, approve workflow to **Approved**, then **Settle Petty Cash**; verify JE amounts and PI outstanding reduction match the **partial** allocation.

---

## F. Cancel PM Clearance and verify Purchase Invoice outstanding reverts

1. **Cancel** the submitted **PM Clearance** (linked **Journal Entry** must cancel).
2. Confirm Purchase Invoice **outstanding** returns to the value **before** that clearance (same as standard ERPNext behaviour when PI-referenced JE is cancelled).

---

## Regression checks

| Check | Expected |
|--------|-----------|
| **PM Clearance** posting | **Journal Entry** only; debits are Purchase Invoice payable (`credit_to`), not arbitrary expense accounts. |
| **Workspace** | Setup: PM Settings, PM Holder. Transactions: PM Request, PM Clearance (Petty Invoice Settlement), Purchase Invoice, Payment Entry, Journal Entry. |
