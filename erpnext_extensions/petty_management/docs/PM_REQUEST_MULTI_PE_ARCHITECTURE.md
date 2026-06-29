# PM Request — Multiple Payment Entries (Architecture v2.1)

**Status:** Approved design. **Do not implement** until unit, integration, backend smoke, and Playwright E2E tests are written and pass per §10.

---

## 1. Source of truth

- **Funded amount** = sum of **submitted** Payment Entries only:
  - `docstatus = 1`
  - `payment_type = 'Pay'`
  - `paid_amount > 0` (fallback `received_amount` only if ERPNext leaves `paid_amount` zero — document in code)
  - Linked via `reference_no = PM Request.name` OR `custom_pm_request = PM Request.name` (if field exists)
  - Same company; Employee party matches request
- **Draft PE** = reservation only. **Not** in funded totals, holder balances, or Remaining To Pay.
- **No child ledger table** on PM Request.

### Latest Payment Entry (`payment_entry` field)

- **Kept.** Label: **Latest Payment Entry**.
- **Not** source of truth. Updated on PE create/submit for navigation (recommend: latest **submitted** PE, else latest linked draft).
- Uses: Open PE shortcut, list view, PM Funding History link.

---

## 2. Computed fields (SQL aggregates; sync on validate + PE hooks)

| Field | Formula |
|--------|---------|
| `total_paid_amount` | Σ submitted PE (rules above) |
| `remaining_to_pay` / `unpaid_amount` | `max(0, total_requested_amount − total_paid_amount)` |
| `total_draft_pe_amount` | Σ draft PE (Desk / validation only) |
| `allocated_amount` | Sum of reserving PM Clearance allocations (existing SQL) |
| `available_for_clearance` | `total_paid_amount − allocated_amount` |
| `payment_status` | **Not Paid \| Partially Paid \| Paid** only (derived from paid vs requested) |

**Remaining To Pay** = Requested − **Submitted only** (drafts do **not** reduce Remaining).

**Create Payment Entry validation:**

```text
total_submitted + total_draft + new_paid_amount <= total_requested_amount + ε
```

Default new PE amount = `remaining_to_pay`.

---

## 3. Payment status

| Value | When |
|--------|------|
| Not Paid | paid ≈ 0 |
| Partially Paid | 0 < paid < requested |
| Paid | paid ≥ requested |

**Closed is not a payment status.** UI/reports show **Closed** when `is_closed = 1`.

---

## 4. Workflow

- Unchanged: Draft → Pending Approval → Approved / Rejected.
- **Close is not a workflow state** and must never set `workflow_state`.

---

## 5. Operational Close (`close_pm_request`)

### 5.1 What Close sets (only)

- `is_closed = 1`
- `closed_on`, `closed_by`
- `close_reason`, `close_reason_detail` (when applicable)

### 5.2 What Close must NEVER modify

- `total_paid_amount`
- `allocated_amount`
- `available_for_clearance`
- Holder balance / funded available
- `payment_status`
- `workflow_state`

Close **only blocks future** `create_payment_entry`. It does **not** recalculate financial fields.

### 5.3 Close availability

Available when **all** of:

- Workflow **Approved** (not Rejected)
- `is_closed = 0`
- **No** active **draft** Payment Entry for this request (see §5.5)

**Do not hide Close when fully paid.** Close remains available at `remaining_to_pay = 0`.

| Remaining To Pay | Close allowed | Close Reason |
|------------------|---------------|--------------|
| > 0 | Yes | **Mandatory** |
| = 0 | Yes | **Optional** |

If fully paid and user closes without reason, all financial fields unchanged.

### 5.4 Close Reason

Select (when required or provided):

1. Budget Limitation  
2. Partial Approval  
3. Cancelled by Requester  
4. Other  

If **Other** → `close_reason_detail` **mandatory**.

When `remaining_to_pay > 0` and close attempted without reason → validation error.

### 5.5 Draft Payment Entry guard

If any **draft** PE exists for the request:

- **Block Close**
- Message: *Cannot close PM Request. Please submit or cancel all draft Payment Entries first.*

---

## 6. PM Clearance independence (mandatory)

- Allocation and settlement use **`available_for_clearance` only**.
- **`is_closed` must not appear** in clearance validation, picker filters, or allocation guards.

**Prohibited:**

```python
if request.is_closed:
    reject allocation
```

Closing freezes **funding** only, not **settlement**.

---

## 7. Payment Entry cancel policy

Before cancel of a funding PE linked to a PM Request:

```text
paid_after_cancel = total_submitted excluding this PE
if reserved_allocations > paid_after_cancel + ε:
    block cancel
```

Message:

> This Payment Entry cannot be cancelled because allocated petty cash settlements exceed the remaining funded amount. Please cancel or reduce PM Clearance allocations first.

---

## 8. API (whitelisted)

| Method | Notes |
|--------|--------|
| `create_payment_entry(pm_request, paid_amount=None)` | Row lock; cap validation |
| `close_pm_request(pm_request, close_reason=None, close_reason_detail=None)` | §5 |
| `get_pm_request_action_flags` | can_create_pe, can_close, remaining, paid, draft, latest PE, … |
| `get_pm_request_allocation_context` | paid = aggregate submitted; available = paid − allocated |

---

## 9. UI

- Form: Requested, Paid, Remaining, Draft (info), Allocated, Available, payment_status, **Closed** badge if `is_closed`.
- **Create Payment Entry** — hidden/blocked when closed, fully paid (no remaining **and** policy), or not approved.
- **Close PM Request** — dialog with reason rules §5.3–5.4; blocked if draft PE §5.5.
- PM Clearance: picker by **available > 0**; never by `is_closed`.

---

## 10. Report: PM Funding History

### Summary (per PM Request)

- Requested Amount  
- Total Paid  
- Remaining To Pay  
- Allocated Amount  
- Available for Clearance  
- Payment Status  
- Is Closed  
- Closed By, Closed On  
- Close Reason, Close Reason Detail  
- Latest Payment Entry  

**Summary block:** Requested, Paid, Remaining, Allocated, Available, **count of Payment Entries**.

### Detail (per PE)

- Payment Entry  
- Posting Date  
- Amount  
- Bank Account (paid_from)  
- Submitted By  
- Status (Draft / Submitted / Cancelled)  

---

## 11. Reconciliation (extend)

| Code | Condition | Severity |
|------|-----------|----------|
| PAID_EXCEEDS_REQUESTED | paid > requested | ERROR |
| SUBMITTED_PLUS_DRAFT_EXCEEDS_REQUEST | submitted + draft > requested | ERROR |
| AVAILABLE_NEGATIVE | available_for_clearance < 0 | ERROR |
| RESERVED_EXCEEDS_FUNDED | reserved > paid | ERROR (existing) |

All must surface in reconciliation report output.

---

## 12. Migration

- Backfill PE links (`reference_no` / `custom_pm_request`).
- Recompute `total_paid_amount`, `payment_status` from aggregates.
- Keep `payment_entry` as latest submitted PE.
- Remap obsolete payment_status values to three-value enum.
- `is_closed` default 0.

---

## 13. Automated tests (write before feature code)

### Unit

- Multiple PE; partial/full funding; over-funding blocked  
- Close: fully paid, partially paid, unpaid (if allowed)  
- Close with draft PE → blocked  
- Close without reason when unpaid → blocked  
- Close Other without detail → blocked  
- Fully paid close without reason → OK; balances unchanged  
- Close never changes paid / allocated / available / holder  
- PE cancel blocked when allocated > paid after  
- Reconciliation rules §11  
- `is_closed` not referenced in allocation_service clearance paths (grep test or explicit)

### Integration

100k → PE 40k → PE 30k → **Close** (balances unchanged) → clearance → settle → cancel JE → cancel clearance → balances restored.

### Backend smoke

`pm_multi_pe_e2e.execute` (or equivalent).

### Playwright E2E

- Close visible after approval; visible when fully paid  
- Reason required only when unpaid  
- Close blocked with draft PE  
- After close, Create PE gone; clearance still allocates  
- Balances unchanged by close; screenshots before/after close  

### Manual UAT

Accounting checklist with expected values per step (including close at remaining = 0 with optional reason).

---

## 14. Final acceptance criteria

Implementation accepted only if:

1. Accounting balances unchanged by Close.  
2. Funding freezes correctly (`is_closed` blocks PE only).  
3. Settlement continues via `available_for_clearance`.  
4. Multiple PE works with caps and concurrency safety.  
5. Reconciliation passes (§11).  
6. Unit, integration, backend smoke, Playwright E2E pass.  
7. Manual UAT signed off.  
8. This document matches shipped behavior.

---

## 15. Implementation order

1. Tests (failing skeletons)  
2. `funding_queries` + sync  
3. `create_payment_entry` refactor  
4. `close_pm_request`  
5. PE hooks + cancel guard  
6. Allocation / holder / picker (no `is_closed`)  
7. Reconciliation  
8. PM Funding History report  
9. Desk UI  
10. Playwright + UAT  

---

*Document version: 2.1 — incorporates operational close policy, close availability at full pay, draft PE guard, clearance independence, report and reconciliation extensions.*
