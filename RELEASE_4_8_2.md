# ERPNext Extensions v4.8.2

ERPNext 16.33 review for the manufacturing flow (Daily Production Log / semi-finished goods)
and one compatibility fix.

## Fix — 3.8.8 process-loss patch stands down on ERPNext 16.33+

- `stock_extensions/job_card_process_loss.py` (3.8.8) replaced `StockEntry.set_process_loss_qty`
  to stop the Work-Order-wide `MAX(operation loss)` reset from being re-applied to Job Card
  Manufacture entries.
- ERPNext 16.33 (frappe/erpnext#58262, backport of #58256) rewrote that method around
  `get_pending_process_loss_qty`: a Job Card entry books the card's **own unbooked** loss, and a
  Work Order level entry books only the **portion of the largest operation loss not yet booked**
  on the Work Order — loss is booked once across partial entries.
- Our override kept the old logic for Work Order level entries (full `MAX` reset every time),
  which on 16.33 undoes that upstream fix for legacy (non semi-finished) Work Orders.
- `apply_patch` now detects the upstream method and leaves upstream in charge; on older 16.x
  the override is installed as before. Job Card entries behave the same either way.

## ERPNext 16.33 review — what changed around the Daily Production Log runner

| Upstream change | Effect on the runner |
| --- | --- |
| #58262 Job Card completed qty capped by the minimum qty the previous operations manufactured (`get_max_completable_qty`); WO finish dialog shows operation process loss | Same rule the runner enforces up front (check 4: previous operation's output of **this** Work Order must be available). No change needed. |
| #58115 Material Transfer for Manufacture `fg_completed_qty` capped by the raw-material coverage of the entry (`_cap_completed_qty_to_material_coverage`) | Explicitly **skipped** for Work Orders with operations that transfer against Job Cards — exactly our flow. No change. |
| #58237 Item-group default warehouse as a further fallback for component source warehouse / Work Order target warehouse | Only fills a source warehouse that is empty on the BOM row; the Alcarisa BOM rows all carry explicit warehouses. The 4.7.4 card → BOM warehouse fallback in the runner is unchanged. |
| #58245 Work Order stays *Not Started* with only *Skip Material Transfer to WIP* until material is transferred | Runner does not depend on the Not Started / In Process transition. |
| `secondary_item_type` / `bom_secondary_item` scrap rows on Stock Entry rows, `set_secondary_items_from_job_card` on the Job Card Manufacture entry | Scrap rows are not finished items; the runner's finished-good lookup (`is_finished_item`) and the difference-account stamping on every row keep working. |
| `Job Card.start_timer` / `complete_job_card` now `**kwargs` with `validate_transfer_qty` | Runner keyword calls are compatible; cards with a Finished Good are exempt from the transfer-before-timer rule. |

## Staging validation (erpstage, 2026-08-28, ERPNext 16.33.0 / Frappe 16.31.0, app 4.8.1)

`MFG-WO-2026-00442` (BOM-20100067-017, 2756 units) ran end to end through Daily Production
Logs only on the upgraded site: Work Order **Completed / 2756 produced**, **12 Job Cards**, every
card `for_quantity == completed`, `semi_fg_bom` on all cards, booked operating cost == Work Order
actual on all five operations; all failure cases (now with the 4.8.1 messages), the
cross-operator timer guard, concurrency, re-run of a Failed log and idempotency passed. Timing:
op 5 (packaging, 21 materials) 11.3–16.9 s and one op-1 cycle 10.6 s against the 10 s budget —
the only failed expectations. Fixture for the run: packaging materials moved from the secondary
store (`MAT-STE-2026-08789`) and a Material Receipt of 5,456 × `13200504` @ 10,000
(`MAT-STE-2026-08790`) — that item had no stock anywhere on staging.

Test plan: each test Work Order now carries its own GMP number (`DPLTEST-<WO suffix>`), so
placeholder lots are created per run instead of reusing an earlier run's lots.

## Unchanged

- No schema change; no patch. `bench migrate` + restart.
