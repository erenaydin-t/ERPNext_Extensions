# ERPNext Extensions v4.7.0

Focused fix for Post Dated Cheque workflow rollback when undoing an accounting transition.

## Fix — rollback-owned Journal Entry cancellation

- Fixed PDC rollback failure:
  `Cannot delete or cancel because Journal Entry … is linked with Post Dated Cheque …`
- Root cause (v4.4.4+): `PDC Lifecycle Event.journal_entry` was a hard **Link**. When the
  lifecycle child row had `docstatus=1`, Frappe blocked `je.cancel()` even after the
  operational `PDC Journal Reference` was removed.
- `PDC Lifecycle Event.journal_entry` is now **Data** (audit-only). Historical `ACC-JV-*`
  names remain on the event; they no longer create a Frappe hard-link dependency.
- Operational `PDC Journal Reference` rows for the undone occurrence are still removed
  before JE cancellation. Stale/missing `journal_reference_name` falls back to resolving
  exactly one JR by PDC + JE (ambiguous matches fail closed).
- Payable Registered → Draft continues to restore Cheque Leaf **Used → Reserved**
  (`reserved_by_pdc` set; `linked_post_dated_cheque` / `used_on` cleared). Leaf is not
  made Available.
- External blockers remain fail-closed: Payment Reconciliation, Bank Transaction,
  submitted PDC Invoice Applications, unlinked/manual related JEs, opening-import rules.
- No broad `ignore_links` / `ignore_linked_doctypes` bypass was introduced. Normal Desk
  Journal Entry cancellation outside PDC rollback remains Link-protected.

## Schema / migration

- DocType change only: `PDC Lifecycle Event.journal_entry` fieldtype Link → Data.
- Existing string values are preserved. No accounting rewrite, no JE cancel/delete during
  migrate, no lifecycle backfill.

## Out of scope

- No change to JE posting, workflow graphs, Guarantee custody, or Petty Management.
