# erpnext_extensions v4.4.6 — Release Notes

**Target:** Petty Management — Payment Entry cancellation funding recalculation

## Bug fix

**Stale `payment_entry` pointer after all Payment Entries cancelled**

`sync_pm_request_funding_fields` used a conditional assignment (`if latest:`)
when resolving the latest active Payment Entry. When all PEs were cancelled,
`resolve_latest_payment_entry` returned `None` but the stale pointer was
never cleared — it was written back to DB unchanged.

**Fix:** Unconditional assignment:

```python
doc.payment_entry = resolve_latest_payment_entry(doc.name, exclude_pe=exclude_payment_entry)
```

One production line changed (`funding_service.py`).

## Guarantees

- PM Request is **never** cancelled during Payment Entry cancellation.
- `workflow_state` is **never** modified by PE cancel hooks.
- Approval fields (`manager_approver`, `ceo_approver`, `finance_approver`) are preserved.
- PM Request `docstatus` remains `1` (submitted) throughout.

## Funding recalculation after PE cancel

| Field | Behaviour |
|---|---|
| `total_paid_amount` | Sum of submitted PEs (`docstatus=1`) |
| `remaining_to_pay` | `requested - total_paid_amount` |
| `payment_status` | Not Paid / Partially Paid / Paid |
| `status` | Derived from workflow + payment_status via `sync_pm_request_business_status` |
| `payment_entry` | Latest active submitted PE, or `None` |

## Allocation guard (unchanged)

If PM Clearance allocations exceed the post-cancel funded amount, PE
cancellation is blocked with:

> "This Payment Entry cannot be cancelled because allocated petty cash
> settlements exceed the remaining funded amount."

## Tests (v4.4.6)

| Suite | Count | Result |
|---|---|---|
| `test_pm_pe_cancel_funding` | 10 | OK |
| `test_pm_request_multi_pe` | 20 | OK |
| `test_pm_request_multi_pe_integration` | 3 | OK |
| `test_pm_request_funding_status_ux` | 6 | OK |
| `smoke/run_pm_regression.sh` (full) | all | **exit=0** |

### New test coverage

| Test | Validates |
|---|---|
| `test_cancel_one_pe_partial_funding` | Multi-PE partial cancel → Partially Paid |
| `test_cancel_all_pes_not_paid` | All PEs cancelled → Not Paid, pointer=None |
| `test_workflow_unchanged_after_cancel` | workflow_state before == after |
| `test_pm_request_docstatus_unchanged` | docstatus stays 1 |
| `test_create_pe_available_after_cancel` | New PE can be created after cancel |
| `test_allocation_guard_blocks_cancel` | Clearance allocations block cancel |
| `test_cancel_single_pe_business_status` | Business status → Waiting for Payment |
| `test_approval_fields_unchanged_after_cancel` | Approver stamps preserved |
| `test_pe_docstatus_is_2_after_cancel` | PE docstatus=2 confirmed |
| `test_audit_event_emitted_on_cancel` | `pm_payment_entry_cancelled` audit log |

## Files changed

| File | Change |
|---|---|
| `__init__.py` | Version 4.4.5 → 4.4.6 |
| `petty_management/services/funding_service.py` | 1-line pointer fix |
| `petty_management/tests/test_pm_pe_cancel_funding.py` | New (10 tests) |
| `petty_management/RELEASE_4_4_6.md` | This file |
