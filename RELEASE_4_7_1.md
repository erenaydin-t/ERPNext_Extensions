# ERPNext Extensions v4.7.1

Cheque Leaf reservation integrity for Draft Post Dated Cheque deletion.

## Fix — Draft PDC deletion releases owned leaf

- Deleting a **Draft Payable** Post Dated Cheque now releases its owned temporary
  Cheque Leaf reservation in the same transaction (`on_trash`).
- Release is ownership-safe under row lock:
  - `status == Reserved`
  - `reserved_by_pdc ==` deleting PDC
  - no `linked_post_dated_cheque`
  - no Guarantee allocation
- Conflicting ownership/state **fails closed** and blocks deletion with a clear
  message (PDC, leaf, status, reservation/link owners).
- **Registered → Draft** workflow rollback still leaves the leaf **Reserved**
  while the Draft PDC exists (v4.7.0 semantics unchanged).
- Deleting that Draft afterward returns the leaf to **Available**.

## Historical orphan repair

- Added idempotent patch
  `release_orphaned_pdc_cheque_leaf_reservations_v471`.
- Automatically releases only proven orphans:
  Reserved + `reserved_by_pdc` set + referenced PDC missing + no linked PDC /
  Guarantee / Used / Void conflicts.
- Leaves whose PDC still exists (including submitted-PDC reservation smells) are
  **not** modified.
- Ambiguous candidates are skipped and logged for manual review.

## Unchanged

- Guarantee Document cheque-leaf custody (v4.4.4)
- PDC accounting / Journal Entry rollback (v4.7.0 Link→Data fix)
- Opening-import cleanup paths
- No schema change; no JE/GL rewrite
