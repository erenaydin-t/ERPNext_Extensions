# erpnext_extensions 4.3.3 — Opening-import PDC workflow rollback blockers

## Summary

Opening-import Post Dated Cheque workflow rollback no longer treats historical
pre-baseline Journal Entries (often matched only by cheque number) as automatic
blockers when they sit outside the accounting edges being undone.

Example: Payable PDC imported at **Issued**, later cleared, rolling back
**Cleared → Issued** only undoes the linked Clear JE. A pre-import Issue JE with
the same cheque number is classified as historical baseline accounting and ignored.

## Safety

Fail-closed classification remains in force:

- Normal (non-import) PDCs: any discovered unlinked related JE still blocks.
- Extra unlinked Clear / Bounce / Return / Cancel-style accounting still blocks.
- Post-import manual JEs that name the PDC still block.
- Party / amount / ambiguous-shape mismatches still block.
- Rollback before `opening_import_workflow_state` remains unavailable.

## Technical

- New module: `accounting_rollback/pdc/blockers.py`
- `validate_rollback_blockers` in `accounting_rollback/pdc/plan.py` classifies
  candidates instead of blocking on first cheque_no match.
- Preview payload may include `ignored_historical_journal_entries` for support.

No schema migration or historical JE relinking is required.
