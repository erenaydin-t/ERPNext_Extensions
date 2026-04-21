# Post Dated Cheque — Implementation Summary

This document describes the **final behaviour** of the Cheque Management **Post Dated Cheque** implementation: accounting model, workflow, status mapping, allocations, parties, endorsement, and safeguards against duplicate GL posting.

**Code map**

| Concern | Primary module(s) |
|--------|---------------------|
| Workflow graph & accounting policy | `pdc_workflow_state_machine.py` |
| Operational `cheque_status` | `pdc_workflow_to_cheque_status.py` |
| JE payload building (no DB insert) | `doctype/post_dated_cheque/post_dated_cheque.py` (`build_pdc_journal_entry_data`) |
| Receivable clearing account selection | `pdc_receivable_accounting.py` |
| Allocation (planning / reporting) | `pdc_allocation.py` |
| Transition keys & idempotency | `pdc_accounting_idempotency.py` |
| Create/submit JE & link references | `pdc_journal_entry_service.py` |

---

## 1. Final accounting model

**Principle:** The PDC **lifecycle is Journal Entry–centric**. All automated workflow posting uses **Journal Entry** vouchers. **Payment Entry is not used** for lifecycle movement (see §7).

**Party timing**

| Direction | Party (AR/AP) is reflected in GL | Bank cash book |
|-----------|-----------------------------------|----------------|
| **Receivable** | Primarily at **Registered** (Draft → Registered): Dr Cheques in Hand, Cr party receivable. Returns and some other edges also touch party. | At **Cleared**: Dr **Bank** GL, Cr CIH / Clearing / Protested (path depends on prior state). **No party** on clear lines. |
| **Payable** | At **Registered → Issued**: Dr party payable, Cr notes-payable pool. Reversals (Returned, Cancelled, etc.) mirror that. | At **Issued → Cleared**: Dr notes-payable pool, Cr **Bank** GL. **No party** on clear lines. |

**Internal pool / intermediary accounts** (from PDC Settings + document fallbacks) include: Cheques in Hand, Cheques in Clearing, Protested, Default Payable Cheque Account (notes-payable pool), optional endorsement settlement GL.

**Allocation rows** (invoices, advances, payment requests) **do not** create additional movement journals by themselves; they are a separate reporting/planning layer (see §4).

**Accounting action** for an edge is either **`journal_entry`** or **`no_document`**, resolved via `get_pdc_accounting_decision` / `get_accounting_action` in `post_dated_cheque.py` (never Payment Entry for policy rows).

---

## 2. Workflow logic

**Control field:** `workflow_state` (shared ERPNext workflow vocabulary).

**Direction-specific graphs** are defined in `RECEIVABLE_WORKFLOW_TRANSITIONS` and `PAYABLE_WORKFLOW_TRANSITIONS` in `pdc_workflow_state_machine.py`. Validation runs from **Post Dated Cheque** `validate()` via `get_pdc_workflow_transition_validation_error`.

**High-level picture**

- **Receivable:** Draft → Registered → (Sent to Bank ↔ Cleared paths, Returned, Endorsed, …); **Sent to Bank** and **Bounced** are receivable-specific; **Endorsed** is a holding state with **no outgoing** bank/clear transitions from this company.
- **Payable:** Draft → Registered → Issued → Cleared / Returned / Replaced / Cancelled; **Issued** is payable-only.

**Terminal states** (no further workflow moves away except staying put): **Cleared**, **Cancelled**, **Replaced** (see `PDC_TERMINAL_WORKFLOW_STATES`).

**Invalid combinations** (e.g. **Issued** on Receivable, **Sent to Bank** on Payable) are rejected even if a generic Workflow would expose an action.

---

## 3. `cheque_status` logic

**Two fields:** `workflow_state` (control) vs `cheque_status` (operational label for users/reports). `cheque_status` is **system-maintained** from `workflow_state` + `cheque_direction` using `map_workflow_state_to_cheque_status` in `pdc_workflow_to_cheque_status.py`.

**Receivable mapping (examples)**

| workflow_state | cheque_status |
|----------------|-----------------|
| Draft | Draft |
| Registered | In Hand |
| Sent to Bank | In Clearing |
| Cleared | Cleared |
| Returned | Returned to Customer |
| Endorsed | Endorsed |
| … | … |

**Payable mapping (examples)**

| workflow_state | cheque_status |
|----------------|----------------|
| Draft | Draft |
| Registered | Draft *(workflow step “registered”; instrument not yet issued)* |
| Issued | Issued |
| Cleared | Cleared |
| Returned | Returned from Payee |
| … | … |

Unmapped pairs for a direction return `None` and saves that would imply them are blocked.

---

## 4. Allocation model

**Purpose:** Child table **`allocations`** (DocType **PDC Allocation**) ties amounts to **Sales Invoice**, **Purchase Invoice**, **Payment Request**, **Advance**, or **Other Settlement** for analysis and planning.

**Rules** (implemented in `pdc_allocation.py` and wired from `PostDatedCheque.validate`):

- `allocated_amount` = sum of row amounts; `unallocated_amount` = `cheque_amount - allocated_amount`; total allocated cannot exceed `cheque_amount`.
- Row-level validation: positive amounts, reference DocType/Name pairs (except **Advance** may omit both), type-specific rules (e.g. Receivable **Against Invoice** → **Sales Invoice**; Payable → **Purchase Invoice**; **Payment Request** → `Payment Request` doctype).

**Effective vs planning**

- **Receivable:** Allocations are **effective** from **Registered** onward (not while still **Draft**-only in terms of milestone helpers).
- **Payable:** **Draft** and **Registered** are **planning-only**; **Issued** onward are **effective**.

Changing allocations **does not** alter workflow JE payloads; movement remains in `build_pdc_journal_entry_data` only.

---

## 5. Supported party types

**DocType Select** (`party_type` / `holder_party_type`): **Customer**, **Supplier**, **Employee**, **Shareholder**.

**Validation guidance** (non-blocking `msgprint` in `_validate_party`):

- **Receivable:** typically **Customer** (also allows Employee, Shareholder per options).
- **Payable:** typically **Supplier** (Employee, Shareholder allowed).

**After submit:** `party_type` and `party` are **immutable** (drawer / payee). **Holder** fields can change when rules allow (e.g. endorsement).

---

## 6. Endorsement logic

**Scope:** **Receivable only.** **Endorsed** is not a valid payable workflow state.

**Behaviour**

- Transition **Registered → Endorsed** with a Journal Entry: **Dr** endorsement settlement GL (PDC Settings `default_endorsement_account`, or per-PDC `endorsement_settlement_account`, or endorsed holder’s receivable when no GL), **Cr** Cheques in Hand. The **drawer (original party)** must **not** appear on lines for endorsement (party was credited at registration).
- **`holder_party_type` / `holder_party`** are **required** when `workflow_state` is **Endorsed** (endorsed holder).
- **PDC Holder History** can record the handover when entering **Endorsed**.
- **Endorsed** cheques do not proceed to **Sent to Bank** / **Cleared** in this company’s workflow (instrument left to the endorsed holder; see workflow validation messages in code).

---

## 7. Why Payment Entry is not used

1. **Single, explicit GL story:** Every lifecycle step is expressed as **Journal Entry** lines (bank vs pool/intermediary, party only where policy allows). This matches the design doc and avoids mixing PE semantics with PDC-specific pools.
2. **Clearing without party on bank:** **Cleared** must post **Bank** vs internal accounts **without** forcing Party on receivable/payable GL types (ERPNext `Journal Entry.validate_party` would otherwise require party on AR/AP accounts or create inconsistent double party effects). A plain JE payload controls exactly which lines carry `party_type`/`party`.

---

## 8. How duplicate accounting is prevented

**Transition key**

- Canonical: `{cheque_name}|{cheque_direction}|{from_state}|{to_state}` with normalized states (blank → Draft) and canonical direction (`pdc_accounting_idempotency.py`).
- Legacy suffix still matched: `{cheque_direction}|{from_state}|{to_state}`.

**Before creating a new JE**

- `get_existing_journal_entry_for_transition` looks up **PDC Journal Reference** rows by `pdc_transition_key` (full or legacy) or scans rows with `stored_transition_key_matches`.

**Concurrency**

- `create_and_submit_journal_entry_from_payload` uses a **per-PDC file lock** (`pdc_accounting_je_{pdc.name}`) so two requests cannot post the same transition simultaneously.

**After posting**

- A **PDC Journal Reference** child row stores `journal_entry`, `pdc_transition_key`, purpose, dates, and amount for audit and idempotent retries.

**Document flags**

- Nested saves from posting set `skip_pdc_accounting_orchestration` to avoid recursion.

Together, these guarantee **at most one submitted Journal Entry per PDC per workflow edge** under normal operation.

---

*For day-to-day developer notes and file references, see `DEVELOPER.md` in this folder. Design narrative (FA): `PDC_DESIGN_FINAL_FA.md`.*
