# Cheque Management — Developer Guide

English technical reference for **Post Dated Cheque (PDC)** and related modules. For full product and accounting design (Persian), see [`PDC_DESIGN_FINAL_FA.md`](./PDC_DESIGN_FINAL_FA.md).

## Source of truth (code)

| Topic | Where |
| ----- | ----- |
| Allowed `workflow_state` edges | `pdc_workflow_state_machine.py` — `RECEIVABLE_WORKFLOW_TRANSITIONS`, `PAYABLE_WORKFLOW_TRANSITIONS` |
| Save-time transition validation | `get_pdc_workflow_transition_validation_error` in `pdc_workflow_state_machine.py` (called from `post_dated_cheque.py`) |
| `workflow_state` → `cheque_status` | `pdc_workflow_to_cheque_status.py` — `map_workflow_state_to_cheque_status` |
| JE / `no_document` per edge | `get_pdc_accounting_decision` in `pdc_workflow_state_machine.py`; definitive action string `get_accounting_action` in `post_dated_cheque.py` |
| JE payload | `build_pdc_journal_entry_data` in `post_dated_cheque.py` |
| Submit JE + `journal_references` | `pdc_journal_entry_service.py` |
| ERPNext Workflow (Desk actions) | `erpnext_extensions/fixtures/workflow.json` — transition set = **union** of both machines; **no** transition `condition` (server validates `cheque_direction` and other rules) |
| Direct cancel vs rollback | `pdc_direct_cancel_policy.py` — block `doc.cancel()`; desk `can_cancel_document` override; see section below |

---

## Reporting model

How PDC relates to **reports** (cash flow, bank books, invoice linkage) is intentionally split into two ideas: **bank movement** vs **allocation intent**.

### Cash flow and bank movement

- **Cash-flow–relevant bank movement** for a PDC is recognized when the instrument **clears** (**workflow_state → Cleared**), **not** at **Registered** (Receivable) or **Issued** (Payable). Earlier journals reclassify between cheques in hand, clearing, notes-payable pool, and party AR/AP; they do **not** post to the company **Bank** GL as settlement at the bank.
- The **Journal Entry** created for **→ Cleared** — **Dr Bank** (Receivable clear) or **Cr Bank** (Payable clear), using the **Bank Account** on the PDC and its linked **Bank** chart account — is the **source of truth** for **bank ledger**, **bank reconciliation**, and any report that should reflect **actual movement on the bank account**.

### Invoice allocation

- **Allocation** rows (`Post Dated Cheque.allocations`) are treated as **effective** for receivable/payable allocation reporting at:
  - **Receivable:** from **Registered** onward (see `is_allocation_effective` / `get_allocation_effective_from_workflow_state` in `post_dated_cheque.py`).
  - **Payable:** from **Issued** onward.
- Allocation is a **separate layer** from bank movement: you can tie amounts to invoices or advances **without** implying the bank has paid or received cash until **Cleared**.

### No Payment Entry

- The PDC **lifecycle does not use Payment Entry**. All workflow posting, including **clear**, goes through **Journal Entry** (`pdc_journal_entry_service.py`).

---

## `workflow_state` vs `cheque_status`

| | **`workflow_state`** | **`cheque_status`** |
| -- | -------------------- | ------------------- |
| **Role** | Control / process stage: where the PDC is in the **workflow** (approvals, next actions, ERPNext Workflow). | Operational “reality”: how the physical cheque should be described in reports (in hand, at bank, cleared, …). |
| **Storage** | Link to **Workflow State** (same eleven labels for Receivable and Payable). | Read-only **Select** on the form; must stay in sync with control state. |
| **Direction** | Valid **next** states depend on `cheque_direction` (enforced in Python, not duplicated in Workflow conditions). | Each **mapped** value depends on **`cheque_direction` + `workflow_state`** (`RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS` vs `PAYABLE_WORKFLOW_TO_CHEQUE_STATUS`). |
| **Updates** | User/system via Workflow **Action** or valid save; validated in `validate()`. | Set in `before_save` / `validate()` via `_sync_cheque_status_from_workflow_state`; mismatch blocked by `_validate_cheque_status_matches_workflow_state`. |

**Why both:** One label in `workflow_state` can map to different `cheque_status` text by direction (e.g. **Registered** → “In Hand” for Receivable vs stays operationally “Draft” for Payable). The control field stays a single canonical workflow vocabulary; the operational field speaks the language of business users and reports.

---

## **Returned** vs **Bounced**

These are **not** interchangeable.

| | **Returned** | **Bounced** |
| -- | -------------- | ----------- |
| **Meaning** | **Business** return: cheque comes back in the operational path without a bank dishonour event on an in-clearing item (e.g. return to customer while still in hand / after internal handling). | **Bank** dishonour: cheque was **Sent to Bank**, bank rejects it. |
| **Receivable routing** | Allowed from **Registered** (and from **Bounced** / **Under Legal Action** per state machine). `cheque_status` → **Returned to Customer**. | Allowed only from **Sent to Bank** (see `get_pdc_workflow_transition_validation_error`). `cheque_status` → **Bounced**. |
| **Payable** | Used (**Issued** → **Returned**, etc.). `cheque_status` → **Returned from Payee**. | **Not** a Payable workflow state in `PAYABLE_WORKFLOW_TRANSITIONS`. |
| **Accounting snapshot** | Registered→Returned = **Journal Entry**. Bounced→Returned = **`no_document`** (policy: workflow/customer follow-up only). | Sent to Bank→Bounced = **Journal Entry**. |

Use **`return_reason`** (and related date fields) for **Returned**; do not use them to mean bank bounce — use **Bounced** for that scenario on Receivable.

---

## State machines

Terminal states (no transition **to a different** state after that): **Cleared**, **Cancelled**, **Replaced**.

### Receivable

| From | To (any of) |
| ---- | ----------- |
| Draft | Registered, Cancelled |
| Registered | Sent to Bank, Cleared, Returned, Endorsed, Replaced, Under Legal Action, Cancelled |
| Sent to Bank | Cleared, Bounced, Registered (Return from Bank) |
| Bounced | Returned, Replaced, Under Legal Action |
| Returned | Replaced, Cancelled |
| Under Legal Action | Cleared, Returned |

**Endorsed:** Explicit entry `Endorsed -> {}` in `RECEIVABLE_WORKFLOW_TRANSITIONS` — **no** further workflow moves (including **Sent to Bank** and **Cleared**). Use **`holder_history`** for the handover audit row when entering **Endorsed**; see `PDC_VALIDATION_ENDORSED_NO_BANK_CLEAR` in `pdc_workflow_state_machine.py`.

### Payable

| From | To (any of) |
| ---- | ----------- |
| Draft | Registered, Cancelled |
| Registered | Issued, Cancelled |
| Issued | Cleared, Returned, Replaced, Cancelled |
| Returned | Replaced, Cancelled |

---

## Transitions that create a **Journal Entry**

Determined by `get_pdc_accounting_decision(...) == "journal_entry"`. Orchestration after save: `_pdc_post_save_accounting_sequence` → `post_pdc_transition_journal_entry`.

### Receivable

| From | To |
| ---- | -- |
| Draft | Registered |
| Registered | Sent to Bank |
| Registered | Cleared |
| Sent to Bank | Cleared |
| Under Legal Action | Cleared |
| Sent to Bank | Bounced |
| Registered | Returned |
| Registered | Endorsed |
| Bounced | Replaced |
| Returned | Replaced |

### Payable

| From | To |
| ---- | -- |
| Registered | Issued |
| Issued | Cleared |
| Issued | Returned |
| Issued | Replaced |
| Issued | Cancelled |
| Returned | Replaced |

*(Exact accounts and remarks: `build_pdc_journal_entry_data` and `PDC_DESIGN_FINAL_FA.md` §9.1. **→ Cleared** rows post the bank-facing JE; see [Reporting model](#reporting-model).)*

### Receivable endorsement (before clearing)

Single **Journal Entry** — **no** bank line, **no** Payment Entry, **no** duplicate effect on the **drawer** (original `party`): registration already **credited** that party’s receivable.

| Leg | Account | Party on line |
| --- | ------- | ------------- |
| Dr | **Endorsement settlement** — `Post Dated Cheque.endorsement_settlement_account` if set, else `PDC Settings.default_endorsement_account` | No |
| Dr (fallback) | Endorsed **holder** receivable (resolved like other party AR) | Yes — **holder only** (`holder_party_type` / `holder_party`) |
| Cr | Cheques in Hand (`account_paid_to` or PDC default) | No |

If the endorsed holder is the **same** as `party`, a GL settlement account **must** be configured (per-PDC or company settings); the builder does not debit/credit the same customer twice via CIH vs AR.

---

## Payment Entry (not used)

**Clear** and all other PDC workflow posting use **Journal Entry** only (see [Reporting model](#reporting-model)). `get_accounting_action` returns **`journal_entry`** or **`no_document`** only; `get_pdc_accounting_decision` never assigns any Payment Entry action to lifecycle edges.

---

## Transitions with **no** automatic accounting document

`get_pdc_accounting_decision` returns `None` for some **allowed** edges (e.g. Receivable **Registered → Replaced**, **Registered → Under Legal Action**, **Returned → Cancelled**); `get_accounting_action` then returns **`no_document`**. Explicit `no_document` rows in the receivable/payable tables include:

- **Receivable:** Registered→Cancelled, Bounced→Returned, Bounced→Under Legal Action  
- **Payable:** Draft→Registered, Draft→Cancelled, Registered→Cancelled, Returned→Cancelled  

*(Full tables: `\_RECEIVABLE_ACCOUNTING_DECISIONS`, `\_PAYABLE_ACCOUNTING_DECISIONS` in `pdc_workflow_state_machine.py`.)*

---

## Direct cancel vs workflow rollback

Users must **not** cancel a submitted PDC with the standard Frappe **Cancel** button or
`doc.cancel()`. Reversals use **Rollback Workflow State** (`pdc_workflow_rollback.py`).

| Layer | Role |
| ----- | ---- |
| `hooks.py` → `can_cancel_document` override | Desk: workflow toolbar asks Frappe whether to show standard Cancel. Global registration required; logic returns `False` only for PDC and delegates other doctypes to native Frappe. |
| `PostDatedCheque.before_cancel` | **Security:** blocks all direct cancel paths unless an approved `frappe.flags` bypass is set (`pdc_direct_cancel_policy.py`). |
| `hide_standard_cancel_for_pdc` (JS) | **UX:** hides Cancel if the toolbar paints it anyway; not authoritative. |

Approved bypass flags (server-only, via `pdc_internal_direct_cancel`): `in_cheque_opening_import_delete` (Delete Imported PDC cleanup), `allow_pdc_direct_cancel` (controlled fixtures/E2E), `in_pdc_workflow_rollback` (reserved).

Tests: `tests/test_pdc_direct_cancel.py`, `tests/test_pdc_can_cancel_cross_doctype_regression.py`.

---

## `journal_references` (child table)

- **DocType:** PDC Journal Reference (`pdc_journal_reference`).
- **Purpose:** Persist a **link and metadata** for each **Journal Entry** the system posts for a PDC transition (audit + idempotency).
- **Typical fields:** `journal_entry`, `purpose` (canonical tag aligned with transition), `pdc_transition_key` (`ChequeDirection|from_state|to_state`), `posting_date`, `amount`.
- **Lifecycle:** Inserted when `pdc_journal_entry_service.create_and_submit_journal_entry_from_payload` successfully submits a JE; **one JE per** `pdc_transition_key` for that PDC.

---

## `holder_history` (child table)

- **DocType:** PDC Holder History (`pdc_holder_history`).
- **Purpose:** Audit trail when the **holder** of an instrument changes (Receivable **endorsement**).
- **When populated:** On transition **into** **Endorsed**, `_append_holder_history_on_endorsement` appends a row (`date`, previous/new holder type & party, `reason` = endorsement constant) if transitioning into Endorsed.
- **Related validation:** `_validate_endorsed_workflow_state` (holder fields required when state is Endorsed); `_sync_holder_fields_for_endorsement` in `before_save`.

---

## Tests (quick reference)

| Area | Module path |
| ---- | ----------- |
| Transition validation | `tests/test_pdc_workflow_transition_validation.py` |
| Status mapping | `tests/test_pdc_workflow_to_cheque_status.py` |
| Accounting action | `tests/test_pdc_accounting_action_selection.py` |
| JE/PE payloads | `tests/test_pdc_payload_builders.py` (requires bench Python) |

Run from bench root (examples):

```bash
PYTHONPATH=apps/erpnext_extensions python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_workflow_transition_validation -v
./env/bin/python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_payload_builders -v
```
