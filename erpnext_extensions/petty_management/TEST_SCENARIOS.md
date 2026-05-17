# Petty Management — manual test scenarios (release scope)

This module covers **only**:

1. **Funding** petty cash holders (**PM Request** → **Payment Entry**: Dr Petty Cash, Cr Bank).
2. **Settling submitted Purchase Invoices** or **Supplier Advances** from petty cash (**PM Clearance** → **Journal Entry**: Dr PI `credit_to` with Supplier + Purchase Invoice reference, or Dr supplier advance account, Cr Petty Cash), with **PM Request allocation** rows for traceability and per-advance caps.

Direct employee expense lines and non-invoice settlement are **out of scope**; use **ERPNext HRMS** **Employee Advance** and **Expense Claim** for those.

Use a development site with **Petty Management** installed and migrated. Figures are examples.

---

## PM Request vs PM Clearance (relationship)

| | **PM Request** | **PM Clearance** |
|---|----------------|------------------|
| **Purpose** | Fund the holder’s **Petty Cash Account** | **Settlement container**: which **Purchase Invoices** are cleared and which **PM Requests** fund that settlement (allocation lines) |
| **Posting** | **Payment Entry** (Dr Petty Cash, Cr Bank per PM Settings) | **Journal Entry** only from **Purchase Invoice** lines (Dr supplier payable / PI `credit_to`, Cr Petty Cash). PM Request lines do **not** post GL. |
| **How they connect** | Each funded request has a submitted **Payment Entry**. | **PM Clearance Request Allocation** child rows link to **PM Request**; sums must match PI line totals; availability excludes legacy migration rows and respects other submitted clearances. |

**Traceability rule:** **Purchase Invoice is not the source of PM settlement truth.** One PI can be partially settled by multiple PM Clearances, and one clearance can be funded by multiple PM Requests. Use **PM Clearance Detail** for business settlement lines, **PM Clearance Request Allocation** for funding/control, and **Journal Entry / Journal Entry Account** rows for accounting truth. Do not store or rely on scalar PM links on Purchase Invoice.

---

## Prerequisites

| Item | Notes |
|------|--------|
| **Company, Chart of Accounts** | Petty cash asset account on **PM Holder**. One GL account may be shared by multiple holders. |
| **PM Settings** | Default company (optional), **Default Bank Account**, **Default Cost Center** (optional), policies as needed. |
| **Supplier & items** | For **Purchase Invoice**. |

---

## Automated tests (PM Clearance)

Python tests live in ``erpnext_extensions/petty_management/tests/test_pm_clearance.py`` (cheque_management-style layout). A thin re-export exists at ``doctype/pm_clearance/test_pm_clearance.py`` for the same ``--module`` path as DocType tests.

```bash
bench --site development.localhost run-tests \
  --module erpnext_extensions.petty_management.tests.test_pm_clearance \
  --skip-before-tests
```

Use ``--lightmode`` only **without** ``--app`` (otherwise the runner loads every ``test_*.py`` in the app). Sites with overlapping **Fiscal Year** definitions may fail during ERPNext accounting setup until data is corrected.

---

## A. Create PM Holder

1. Create **PM Holder** for an **Employee** and **Company** with a **Petty Cash Account** (and optional max balance).
2. Save. Confirm the holder is selectable once **Employee** + **Company** match on **PM Request** / **PM Clearance**.
3. A second holder in the same company may use the same **Petty Cash Account**. In that case, the account GL balance is account-level only; holder availability comes from paid **PM Requests** minus **PM Clearance Request Allocation** rows.

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

## D. PM Clearance: PI lines + PM Request allocation + Journal Entry

1. Create **PM Clearance** (desk label **PM Clearance**): same employee/company as holder; **Pending Amount** reflects petty cash GL balance.
2. **Purchase Invoice lines**: add each PI, **Allocated Amount** (≤ outstanding, ≤ policy), optional cost center/project/bill/proof.
3. **PM Request allocation lines**: add one row per **PM Request** (submitted **Payment Entry** required). Set **Allocated Amount** so the **sum equals** the sum of PI allocated amounts. Use **Preview Settlement Entry** (Actions) to review the future JE **before** submit/approval.
4. **Submit** the clearance. Submitted clearances **without** a settlement JE **reserve** PM Request available balance (other clearances cannot over-allocate).
5. Move workflow to **Approved** (finance approval).
6. Click **Settle Petty Cash** to create the settlement **Journal Entry** and set status **Settled** (workflow remains **Approved**).
7. Open generated **Journal Entry**:
   - For each PI line: **Debit** = Purchase Invoice **credit_to**, **Party Type** = Supplier, **Party** = supplier, **Reference Type** = Purchase Invoice, **Reference Name** = PI.
   - **Credit** = petty cash account for the **total** of allocated amounts (single credit line).
8. Confirm Purchase Invoice **outstanding** reduced by allocated amount.
9. Use **PM Settlement Ledger** to review settlement rows and funding allocation rows without multiplying PI lines by PM Request allocations.

---

## E. Multi-request allocation example

1. Fund two **PM Requests** (A and B) for the same holder so both have paid, submitted **Payment Entries**.
2. On one **PM Clearance**, allocate PI totals across A and B such that **sum(PI) = sum(PM Request allocation)** (e.g. 40,000 + 5,440 = 45,440).
3. Submit and settle; confirm JE still has **only** PI debit lines + one petty credit.

---

## F. Partial settlement

1. Use a PI with outstanding **greater** than the petty balance or greater than the amount you wish to clear.
2. On **PM Clearance**, set **Allocated Amount** on PI lines to **less than** full outstanding (but ≤ petty balance and ≤ PI outstanding). Match the same total on **PM Request allocation** lines.
3. **Submit**, approve workflow to **Approved**, then **Settle Petty Cash**; verify JE amounts and PI outstanding reduction match the **partial** allocation.

---

## G. Cancel PM Clearance and verify Purchase Invoice outstanding reverts

1. **Cancel** the submitted **PM Clearance** (linked **Journal Entry** must cancel first if present).
2. Confirm Purchase Invoice **outstanding** returns to the value **before** that clearance (same as standard ERPNext behaviour when PI-referenced JE is cancelled).

---

## H. Legacy migration row

1. After migrate, old **PM Clearance** documents without allocation children receive **one** row: **Legacy**, empty **PM Request**, **allocated_amount** = clearance total.
2. That row does **not** affect PM Request availability math; new clearances must use real **PM Request** links (no mixing legacy + standard rows).

---

## Regression checks

| Check | Expected |
|--------|-----------|
| **PM Clearance** posting | **Journal Entry** only; debits are Purchase Invoice payable (`credit_to`), not PM Request accounts. |
| **Workspace** | Setup: PM Settings, PM Holder. Transactions: PM Request, **PM Clearance**, Purchase Invoice, Payment Entry, Journal Entry. |
| **PM Holder / PM Balance Report** | **Settled Amount** = clearances with **Journal Entry**; **Pending Settlement** = submitted clearances **without** JE (not cancelled), regardless of workflow state. |
| **Shared petty account** | **Account GL Balance** is shared at account level. **Holder Available** and **PM Request Availability Report** are request/allocation based and must not divide or infer holder balances from GL alone. |
