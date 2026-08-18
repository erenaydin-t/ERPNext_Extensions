# erpnext_extensions 4.4.4

Event-based Post Dated Cheque rollback, Issued Cheque guarantee custody on Cheque Leaf, and PDC list Party display.

## PDC lifecycle events and rollback

- New child table `PDC Lifecycle Event` is the source of truth for rollback after this release.
- Every successful workflow transition appends an event (`accounting` or `workflow_only` from policy, not from JE presence).
- Latest-action rollback undoes only the newest active event (for example the second Send in Send → Return → Send).
- Deep rollback walks active events newest-first until the target state is reconstructed. It does not use the workflow-graph shortest path.
- Workflow-only events restore state and snapshots without searching for a Journal Entry.
- Accounting events without a submitted Journal Entry fail closed.
- Operational fields (`sent_to_bank_date`, `returned_from_bank_date`, `is_at_bank`, and related) restore from the pre-event snapshot, not from “target state ⇒ clear dates”.
- Existing PDCs are not auto-backfilled. Linear history still uses the previous graph/JE path. Repeated transitions reconstruct from ordered Journal References when the chain is continuous; otherwise rollback is blocked.
- Opening-import unlinked-JE classification from v4.3.3 is unchanged.

## Guarantee Document / Cheque Leaf

- Physical owner of company cheques remains `Cheque Leaf`.
- Issued + Cheque guarantees allocate a leaf (`Used for Guarantee`) when becoming Active.
- Received cheques, bank guarantees, and promissory notes are unchanged.
- A leaf cannot be an active Payable PDC and an active Guarantee at the same time (UI query + server validation + row lock).
- Draft does not lock the leaf. Released / Returned / Cancelled restore Available. Expired / Lost keep custody until an explicit release.

## PDC list

- Party Type and Party are list columns and standard filters.
- Party displays as `Customer - CUS-00003` / `Supplier - SUP-00724` from stored Dynamic Link fields. No duplicated party master data.
