# PDC Accounting Transition Matrix & Debt Purchase Extension

**Status:** Design review only — **no implementation**
**Date:** 2026-07-26 (rev: multi-method Facility Repayment)
**Scope:** Existing PDC accounting engine (complete) + Debt Purchase as the same transition family

---

## How to read this document

Account **roles** are keys resolved from **PDC Settings** (and occasional per-PDC overrides). They are **not** hard-coded GLs.

| Role key (code) | Typical Settings field | Meaning |
|-----------------|------------------------|---------|
| `cheques_in_hand` | Cheques in Hand Account | Receivable instrument pool |
| `cheques_in_clearing` | Cheques in Clearing Account | Bank collection intermediary |
| `protested` | Protested Cheques Account | After bounce / legal path |
| `endorsement_account` | Endorsement Account | Preferred Dr for endorsement |
| `payable_cheque` | Payable Cheque Account | Notes payable / issued pool |
| `party_receivable` | *(resolved)* Party default AR | Customer receivable |
| `party_payable` | *(resolved)* Party default AP | Supplier payable |
| `bank_gl` | *(from)* PDC Bank Account → GL | Bank COA (account_type Bank) |
| `advance_paid` | Company default / override | Payable advance recognition |
| `debt_purchase_in_collection` | **NEW** proposed Settings field | Debt-purchase collection pool |

There is **no** workflow state named **Deposited** in this codebase.

---

# Part 1 — Existing Accounting Matrix

## 1.1 Receivable — complete transition inventory

### A. Edges with Journal Entry

| # | Source | Destination | Decision | Purpose (`PDC Journal Reference`) | Builder branch (`build_pdc_journal_entry_data`) | Account roles used | Debit role | Credit role | Remark template (Settings) | Journal ref | Rollback | Cancel PDC | Reversible? |
|---|--------|-------------|----------|-------------------------------------|------------------------------------------------|---------------------|------------|-------------|----------------------------|-------------|----------|------------|-------------|
| R1 | Draft | Registered | JE | Receive | Receivable Draft→Registered | `cheques_in_hand`, `party_receivable` (+ optional SI refs) | `cheques_in_hand` (or `account_paid_to`) | `party_receivable` (or SI against accounts) | `je_remark_register_receivable_template` | Yes — key `PDC\|Receivable\|Draft\|Registered` | Cancel JE → back to Draft (if allowed) | Blocked while JE refs exist | Yes (via rollback engine) |
| R2 | Registered | Sent to Bank | JE | Under Collection | Registered→Sent to Bank | `cheques_in_clearing`, `cheques_in_hand` | `cheques_in_clearing` | `cheques_in_hand` | `je_remark_send_receivable_to_bank_template` | Yes | Cancel JE → Registered | Blocked | Yes |
| R3 | Registered | Cleared | JE (Bank Entry voucher type) | Collected | →Cleared from Registered | `bank_gl`, `cheques_in_hand` | `bank_gl` | `cheques_in_hand` | `je_remark_clear_receivable_registered_template` | Yes | Cleared is **terminal** — no further workflow; rollback to prior may cancel clear JE if engine allows path | Blocked | Rollback only (not forward reverse) |
| R4 | Sent to Bank | Cleared | JE (Bank Entry) | Collected | →Cleared from Sent to Bank | `bank_gl`, `cheques_in_clearing` | `bank_gl` | `cheques_in_clearing` | `je_remark_clear_receivable_clearing_template` | Yes | Same as R3 | Blocked | Rollback only |
| R5 | Under Legal Action | Cleared | JE (Bank Entry) | Collected | →Cleared from Under Legal Action | `bank_gl`, `protested` else `cheques_in_clearing` else `cheques_in_hand` | `bank_gl` | protested / clearing / in-hand | `je_remark_clear_receivable_legal_template` | Yes | Same | Blocked | Rollback only |
| R6 | Sent to Bank | Bounced | JE | Returned | Sent to Bank→Bounced | `protested` or `cheques_in_hand`, `cheques_in_clearing` | `protested` **else** `cheques_in_hand` | `cheques_in_clearing` | `je_remark_receivable_bounced_template` | Yes | Cancel JE → Sent to Bank | Blocked | Yes |
| R7 | Registered | Returned | JE | Returned | Registered→Returned | `party_receivable`, `cheques_in_hand` | `party_receivable` | `cheques_in_hand` | `je_remark_return_receivable_to_party_template` | Yes | Cancel JE → Registered | Blocked | Yes |
| R8 | Registered | Endorsed | JE | Endorsement | Registered→Endorsed | `endorsement_account` **or** holder AR, `cheques_in_hand` | `endorsement_account` (preferred) **or** holder `party_receivable` | `cheques_in_hand` | `je_remark_endorse_receivable_template` | Yes | Endorsed has **no outgoing** edges; rollback to Registered cancels endorsement JE | Blocked | Rollback only |
| R9 | Bounced | Replaced | JE | Receive | Bounced→Replaced | `cheques_in_hand`, `protested` else clearing else in-hand | `cheques_in_hand` | protested / clearing / in-hand | `je_remark_replace_receivable_after_bounce_template` | Yes | Replaced is **terminal** | Blocked | Rollback only |
| R10 | Returned | Replaced | JE | Receive | Returned→Replaced | `cheques_in_hand`, `party_receivable` | `cheques_in_hand` | `party_receivable` | `je_remark_replace_receivable_after_return_template` | Yes | Terminal | Blocked | Rollback only |

Helper for clear credit leg: `receivable_intermediary_account_for_bank_clear()` in `pdc_receivable_accounting.py`.

### B. Edges with No Document (workflow / ops only)

| # | Source | Destination | Decision | Purpose | Builder | Debit / Credit | Remark | Journal ref | Rollback | Reversible? |
|---|--------|-------------|----------|---------|---------|----------------|--------|-------------|----------|-------------|
| R11 | Bounced | Returned | `no_document` | — | None | — | — | No new JE | Workflow-only reverse if allowed by graph + history | Graph: Returned→Replaced only; not back to Bounced |
| R12 | Bounced | Under Legal Action | `no_document` | — | None | — | — | No | Via rollback if JE history empty on that edge | Limited |
| R13 | Registered | Replaced | implied `no_document` (allowed edge, no decision row) | — | None | — | — | No | Terminal | No forward accounting |
| R14 | Registered | Under Legal Action | implied `no_document` | — | None | — | — | No | Possible | Yes (workflow) |
| R15 | Under Legal Action | Returned | implied `no_document` | — | None | — | — | No | Limited | Limited |
| R16 | Registered | Cancelled | `no_document` (explicit) | — | None | — | — | No | Terminal | N/A |
| R17 | Endorsed | *(none)* | — | Terminal empty set | — | — | — | — | Rollback to Registered if JE cancelled | Outgoing forbidden |

**Note:** Edges absent from `_RECEIVABLE_ACCOUNTING_DECISIONS` default to `no_document` via `get_pdc_accounting_decision()`.

### C. Not implemented / not present

| Concept | Status |
|---------|--------|
| **Deposited** | **Does not exist** as workflow state or accounting edge |
| Cleared → *any* | Forbidden (terminal) |
| Endorsed → Sent to Bank / Cleared | Forbidden |
| Bounced without Sent to Bank | Forbidden by validation |

---

## 1.2 Payable — complete transition inventory

### A. Edges with Journal Entry

| # | Source | Destination | Decision | Purpose | Builder | Roles | Debit | Credit | Remark template | Journal ref | Rollback | Cancel PDC | Reversible? |
|---|--------|-------------|----------|---------|---------|-------|-------|--------|-----------------|-------------|----------|------------|-------------|
| P1 | Draft | Registered | JE | Payable Issue | Payable Draft→Registered | `party_payable` / PI refs, `payable_cheque` | `party_payable` (or PI) **or** advance path: `advance_paid` | `payable_cheque` | `je_remark_register_payable_template` | Yes | Yes | Blocked | Yes |
| P2 | Registered | Cancelled | JE | Cancel | Registered→Cancelled | `payable_cheque`, `party_payable` | `payable_cheque` | `party_payable` | `je_remark_cancel_registered_payable_template` | Yes | Terminal | N/A | Terminal |
| P3 | Issued | Cleared | JE (Bank Entry) | Payable Clear | Issued→Cleared | `payable_cheque`, `bank_gl` | `payable_cheque` | `bank_gl` | `je_remark_clear_payable_template` | Yes | Terminal clear | Blocked | Rollback only |
| P4 | Issued | Returned | JE | Returned | Issued→Returned | `party_payable`, `payable_cheque` | `party_payable` | `payable_cheque` | `je_remark_returned_payable_from_payee_template` | Yes | Yes | Blocked | Yes |
| P5 | Issued | Replaced | JE | Returned | Issued→Replaced | same shape as return | `party_payable` | `payable_cheque` | `je_remark_replace_issued_payable_template` | Yes | Terminal | Blocked | Rollback only |
| P6 | Returned | Replaced | JE | Payable Issue | Returned→Replaced | `payable_cheque`, `party_payable` | `payable_cheque` | `party_payable` | `je_remark_replace_returned_payable_template` | Yes | Terminal | Blocked | Rollback only |
| P7 | Issued | Cancelled | JE *(decision table)* | Cancel | Issued→Cancelled | `payable_cheque`, `party_payable` | `payable_cheque` | `party_payable` | `je_remark_cancel_issued_payable_template` | Yes | — | — | **Edge may be stale vs current `PAYABLE_WORKFLOW_TRANSITIONS`** (Issued→Cancelled not in current graph) |

### B. Edges with No Document

| # | Source | Destination | Decision | Notes |
|---|--------|-------------|----------|-------|
| P8 | Registered | Issued | `no_document` | Operational handover; **exception:** may still build JE if advance recognition stage = `issue` (conditional builder, not standard settlement) |
| P9 | Returned | Cancelled | `no_document` | |
| P10 | Draft | Cancelled | `no_document` | |

### C. Conditional / special builder

| Edge | When JE builds | Debit | Credit |
|------|----------------|-------|--------|
| Registered → Issued | Only if `allocation_mode=Advance` and `effective_stage_for_advance_recognition=issue` and recognition not yet posted | `advance_paid` | `payable_cheque` | Purpose still falls through default mapping |

---

## 1.3 Rollback & cancel behavior (engine-wide)

| Mechanism | Behavior |
|-----------|----------|
| **Rollback** | `pdc_workflow_rollback.rollback_workflow_state` → BFS prior states → `accounting_rollback` cancels JE for reversed edge(s) via `PDC Journal Reference` keys |
| **Opening import** | Separate baseline; cannot roll below import baseline |
| **Cancel PDC document** | Blocked when submitted JE references exist (`ensure_pdc_has_no_submitted_journal_references`) |
| **Idempotency** | Same transition key → reuse existing JE; no double post |
| **Terminal states** | Cleared, Cancelled, Replaced — no outgoing workflow |

---

# Part 2 — Template Architecture (internal engine)

```
Workflow State Machine
        ↓
Accounting Decision
        ↓
Transition Registry
        ↓
Account Role Resolver
        ↓
JE Builder
        ↓
Remark Template
        ↓
Journal Entry
        ↓
PDC Journal Reference
        ↓
Rollback Engine
```

### Layer detail

| Layer | File(s) | Class / function | Responsibility |
|-------|---------|------------------|----------------|
| **1. Workflow State Machine** | `pdc_workflow_state_machine.py` | `RECEIVABLE_WORKFLOW_TRANSITIONS`, `PAYABLE_WORKFLOW_TRANSITIONS`, `get_pdc_workflow_transition_validation_error`, `is_pdc_workflow_transition_allowed` | Legal `from → to` edges; terminal rules; bounced/endorsed/issued guards |
| **2. Accounting Decision** | same | `_RECEIVABLE_ACCOUNTING_DECISIONS`, `_PAYABLE_ACCOUNTING_DECISIONS`, `get_pdc_accounting_decision` | `journal_entry` vs `no_document` |
| **3. Transition Registry** | `pdc_transition_accounting_registry.py` | `PdcTransitionAccountingSpec`, `get_pdc_transition_accounting_spec`, `iter_pdc_transition_accounting_specs` | Declarative edge specs (roles, party policy, bank requirement) — documentation + validation aid |
| **4. Account Role Resolver** | `post_dated_cheque.py` | `resolve_pdc_accounts_for_journal(doc)` | Maps Settings → `{cheques_in_hand, cheques_in_clearing, payable_cheque, protested, endorsement_account}` + party/bank helpers |
| **5. JE Builder** | `post_dated_cheque.py` | `build_pdc_journal_entry_data(doc, from_state, to_state, …)` | Per-edge Dr/Cr rows; returns payload or `None` |
| **5b. Clear credit helper** | `pdc_receivable_accounting.py` | `receivable_intermediary_account_for_bank_clear` | Which pool to credit on →Cleared |
| **6. Remark Template** | `utils/descriptions.py` + PDC Settings | `render_pdc_je_text`, `PDCDescriptionContext`, Settings `je_remark_*_template` | Placeholder substitution (`{cheque_no}`, `{cheque_purpose}`, …) |
| **7. Journal Entry** | `pdc_journal_entry_service.py` | `create_and_submit_journal_entry_from_payload`, `_purpose_for_transition` | Create/submit ERPNext JE; purpose label |
| **8. PDC Journal Reference** | child DocType `PDC Journal Reference` | Appended on PDC | `journal_entry`, `purpose`, `amount`, `pdc_transition_key` |
| **9. Rollback Engine** | `pdc_workflow_rollback.py` + `accounting_rollback/` | `rollback_workflow_state`, `get_rollback_target_states`, cancel JE by transition key | Reverse state + cancel accounting |

**Orchestration:** Post Dated Cheque `on_update` / workflow hooks call decision → builder → service when state changes.

**There is no editable “Accounting Template” DocType of Dr/Cr rows.** Templates = code branches + Settings account links + Settings remark strings.

---

# Part 3 — Debt Purchase Extension (same architecture)

Debt Purchase is **another transition family** inside the same stack — not a parallel GL engine.

### New workflow (Receivable only)

```
Registered
    ↓
Assigned to Bank for Debt Purchase
    ↓
    ├── Bounce Cheque → Bounced   ← Dr Protested / Cr DPIC (not CIH)
    └── Debt Purchase Settled   ← ONLY via Facility Repayment
                                    (repayment_method = Debt Purchase Cheque)
```

### Forbidden

```
Assigned to Bank for Debt Purchase  →  Cleared   ✗
Assigned …  →  Returned / Registered (desk)   ✗
Assigned …  →  Sent to Bank / Endorsed   ✗
```

> **Accounting note (approved):** Assigned → Bounced is **bank dishonour**, not reverse-assignment.
> JE: **Dr `protested`** (`default_protested_account`, required — no CIH fallback) / **Cr `debt_purchase_in_collection`**.
> Do **not** Dr `cheques_in_hand` (cheque is not returned to cashier).
### Architecture reuse map

| Layer | Change |
|-------|--------|
| State machine | Add two states; add edges Registered→Assigned, Assigned→Bounced, Assigned→Settled; **do not** add Assigned→Cleared / Returned |
| Accounting decision | JE for assign, bounce-from-assigned, settle |
| Registry | Three new `PdcTransitionAccountingSpec` rows (assign, bounce, settle metadata) |
| Role resolver | New key `debt_purchase_in_collection` from Settings |
| Builder | Three new branches in `build_pdc_journal_entry_data` |
| Remark | Three new Settings templates |
| Purpose | Extend `_purpose_for_transition` + Journal Reference Select |
| Journal ref | Same child table / key pattern |
| Rollback | Assigned DP has no rollback transition; cancel-JE-by-key remains for allowed non-DP rollback paths |

Closest existing analogue for assignment: **Registered → Sent to Bank** (pool reclass with drawer Party on both rows).

Closest existing analogue for bounce-from-assigned: **Sent to Bank → Bounced** (Dr protested / Cr collection pool, Party on both) — with **DPIC** replacing clearing as the credit role.

Settlement is **hybrid trigger**: Facility Repayment posts **one** JE (Cr DPIC + Facility debit legs) and drives PDC `Assigned → Settled` with a Journal Reference to that same JE (see Part 6).

---

# Part 4 — New Account Roles

### Required new role

| Role key | PDC Settings field (proposed) | Why |
|----------|-------------------------------|-----|
| `debt_purchase_in_collection` | Link → Account, e.g. “Debt Purchase In Collection Account” | Distinct pool from `cheques_in_clearing`. Clearing is for normal bank presentation; DP collection must not be clearable via Sent-to-Bank→Cleared path |

### Existing roles reused

| Role | Used in DP |
|------|------------|
| `cheques_in_hand` | Cr on assignment only; **not** used on Assigned→Bounced |
| `protested` | Dr on Assigned→Bounced (required; no CIH fallback) |
| `party_receivable` | Drawer Party mirrored onto DPIC / Protested / CIH lines (not an AR settlement debit on bounce) |
| Facility-side accounts | From Facility Type / Facility Repayment builders (`facility_loan_receivable`, interest income, bank) — **not** PDC Settings roles |

### Optional additional configurable roles (only if product needs them)

| Role | When needed |
|------|-------------|
| Per-bank override of DP collection | If each Bank Account needs different DP GL — else company-level Settings role is enough |
| Separate DP settlement contra | **Not needed** — settlement **credits** `debt_purchase_in_collection` on the Facility Repayment JE (bank credit swap) |

**Do not hardcode account names in builders** — only resolve via `resolve_pdc_accounts_for_journal`.

---

# Part 5 — Debt Purchase Transition Matrix

| # | Source | Destination | Decision | Purpose (proposed) | Builder (proposed) | Debit role | Credit role | Remark template (proposed) | Journal reference | Rollback | Cancel | Facility impact |
|---|--------|-------------|---------|---------------------|-------------------|------------|-------------|---------------------------|-------------------|----------|--------|-----------------|
| DP1 | Registered | Assigned to Bank for Debt Purchase | JE | Debt Purchase Assignment | `build_…` branch assign | `debt_purchase_in_collection` | `cheques_in_hand` | `je_remark_debt_purchase_assign_template` | Yes — `…\|Registered\|Assigned to Bank for Debt Purchase` | Cancel JE → Registered; clear bank/date fields | Blocked if JE exists | **None** — no Facility link |
| DP2 | Assigned… | Registered | *(rollback blocked)* | — | No desk rollback from Assigned | — | — | — | — | N/A | — | None |
| DP3 | Assigned… | Bounced | JE | Returned *(canonical purpose)* | DP bounce branch | `protested`, `debt_purchase_in_collection` | `protested` (**required**, no CIH fallback) | `debt_purchase_in_collection` | `je_remark_receivable_bounced_template` | Yes | **No workflow rollback** (terminal business transition). Any reversal requires approved recovery/accounting correction path. | Blocked | **None** |
| DP3-legacy | Assigned… | Returned | ~~JE~~ | — | **Superseded** — Return from Assigned forbidden | ~~`party_receivable`~~ | ~~`debt_purchase_in_collection`~~ | — | — | — | — | — |
| DP4 | Assigned… | Debt Purchase Settled | **One JE** (Facility-owned) | Debt Purchase Settlement | Extend `build_repayment_je_plan` — same Facility debit roles; **credit** `debt_purchase_in_collection` instead of bank | See Part 7 (code-backed) | `debt_purchase_in_collection` (total) | Facility repayment remarks (+ optional DP settle template) | PDC Journal Reference → **same** Facility Repayment `journal_entry` | Cancel Facility Repayment → cancels JE → restore Assigned | Blocked | **Links** `debt_purchase_facility`, `debt_purchase_repayment`; repayment.`post_dated_cheque` |
| DP5 | Assigned… | Cleared | **Forbidden** | — | — | — | — | — | — | — | — | — |

### Party / bank policy for DP edges

| Edge | Party on JE? | Bank GL? |
|------|--------------|----------|
| DP1 Assign | **Yes** — drawer Party on DPIC and CIH | No (Bank Account on PDC for ops only) |
| DP3 Bounce | **Yes** — drawer Party on Protested and DPIC | No |
| DP4 Settle | **PDC Party only on DPIC settlement credit**; other Facility rows keep Facility policy | **No** — credit is DPIC role, not bank |

---

# Part 6 — Facility Repayment as a multi-method document

**Locked product rule:** Facility Repayment is **not** converted into a Debt Purchase-only process. It remains the general repayment document and **additionally** supports Debt Purchase cheque settlement.

```
Facility Repayment
├── Bank Account          ← existing accounting & behavior (default, backward compatible)
└── Debt Purchase Cheque  ← additive method: Cr debt_purchase_in_collection + PDC state/links
```

## 6.1 Field: `repayment_method`

| Item | Value |
|------|-------|
| Fieldname | `repayment_method` |
| Label | Repayment Method / روش پرداخت قسط |
| Type | Select |
| Options (v1) | `Bank Account` (حساب بانکی), `Debt Purchase Cheque` (چک خرید دین) |
| Default | `Bank Account` |
| Migration | NULL / empty / missing → treat as **Bank Account**; do **not** repost existing submitted docs |

Rename note: prior design drafts used `settlement_mode` / `debt_purchase_cheque` / `bank_cash`. Canonical v1 field is **`repayment_method`** with the labels above.

## 6.2 Existing stack (unchanged foundation)

| Layer | Location |
|-------|----------|
| DocType | `Facility Repayment` |
| Controller | `FacilityRepayment` |
| JE plan | `facility_accounting.build_repayment_je_plan` |
| Post | `create_and_submit_repayment_je` |
| Cancel JE | `cancel_journal_entry` |
| Balances | `get_facility_balance_row` / `refresh_facility_paid_fields` |

One JE per repayment. Paid/outstanding from opening + Σ submitted repayments (both methods included).

## 6.3 Method: Bank Account (preserve exactly)

When `repayment_method = "Bank Account"` (including legacy rows with empty method):

| Rule | Behavior |
|------|----------|
| `bank_account` | **Mandatory**; used as settlement credit |
| `post_dated_cheque` | Hidden / disabled; must be **empty** (server rejects if set) |
| DP validations | **None** |
| PDC state | **Unchanged** |
| PDC Journal Reference | **Not created** |
| JE builder | Existing `build_repayment_je_plan` path unchanged |
| Penalty | Supported as today |
| `is_debt_purchase` | **Not** required; DP facilities may still repay via Bank Account |

**Accounting (unchanged):**

| Side | Role | Amount |
|------|------|--------|
| Cr | `bank` (`bank_account`) | total = P + profit + penalty |
| Dr | `loan` | principal |
| Dr | `loan_profit` | profit |
| Dr | `penalty` | penalty if > 0 |
| Cr | `deferred_credit` | profit if > 0 |
| Dr | `interest_expense` | profit if > 0 |

**Submit:** create JE → set `journal_entry` → refresh balances.
**Cancel:** cancel JE → clear `journal_entry` → refresh balances. **No PDC steps.**

## 6.4 Method: Debt Purchase Cheque (additive)

When `repayment_method = "Debt Purchase Cheque"`:

| Rule | Behavior |
|------|----------|
| `bank_account` | **Not required**; must **not** be used as settlement credit; clear on method switch |
| `post_dated_cheque` | **Mandatory**; one receivable PDC |
| Facility Type | `is_debt_purchase = 1` |
| PDC state | Must be `Assigned to Bank for Debt Purchase` |
| Company / currency | Must match Facility Repayment |
| Uniqueness | Cheque not Settled / not linked to another submitted repayment |
| Amount | `cheque_amount == principal_amount + profit_amount` exactly |
| Penalty (v1) | `penalty_amount == 0` |
| Partial / multi | Forbidden |

`is_debt_purchase = 1` means the type is **eligible** for cheque settlement — it does **not** force all repayments onto cheques.

## 6.5 Dynamic form behavior (client UX + server truth)

| `repayment_method` | UI |
|--------------------|-----|
| Bank Account | Show + require `bank_account`; hide/disable `post_dated_cheque`; **clear** PDC if switching from cheque |
| Debt Purchase Cheque | Show + require `post_dated_cheque`; hide/disable `bank_account`; **clear** bank if switching from bank; filter eligible Assigned DP cheques |

Client scripts are usability only. Server `validate` must reject stale/conflicting fields if client is bypassed.

## 6.6 Accounting builder — settlement credit source branch

Extend **one** builder (`build_repayment_je_plan`); do **not** duplicate debit/deferred legs.

```
common legs: loan, loan_profit, penalty?, deferred_credit?, interest_expense?
settlement credit:
  if repayment_method == "Bank Account":
      credit_role = bank
  if repayment_method == "Debt Purchase Cheque":
      credit_role = debt_purchase_in_collection   # resolve via PDC Settings role
```

Only the settlement **credit source** changes. Direction: assignment Dr DPIC → settlement **Cr** DPIC.

### Example (Debt Purchase Cheque)

Principal 900, Profit 100, Cheque 1,000, Penalty 0:

| Side | Role | Amount |
|------|------|--------|
| Dr | `loan` | 900 |
| Dr | `loan_profit` | 100 |
| Cr | `debt_purchase_in_collection` | 1,000 |
| Dr | `interest_expense` | 100 |
| Cr | `deferred_credit` | 100 |

Roles only — no hardcoded account names.

## 6.7 PDC state and Journal Reference (cheque method only)

After successful JE submit, **same DB transaction**:

1. Link PDC ↔ Facility Repayment
2. Append PDC Journal Reference → Facility Repayment `journal_entry`
3. Purpose = `Debt Purchase Settlement`
4. PDC: `Assigned to Bank for Debt Purchase` → `Debt Purchase Settled`

Bank Account method: **no** link, **no** state change, **no** journal reference.

## 6.8 Cancel behavior by method

### Bank Account

Preserve current order: cancel JE → clear JE link → refresh balances.

### Debt Purchase Cheque

Ordered cancel (fail-safe):

1. Lock Facility Repayment and PDC
2. Validate linked PDC is still `Debt Purchase Settled` **by this repayment**
3. Cancel JE successfully
4. Cancel/remove PDC Journal Reference (existing rollback architecture)
5. PDC → `Assigned to Bank for Debt Purchase`
6. Clear repayment/PDC links
7. Refresh Facility balances

If JE cancel **fails** → **do not** change PDC state or clear links.

## 6.9 Backward compatibility

| Rule | Detail |
|------|--------|
| Default | Empty/`NULL` method → Bank Account |
| Historical docs | No modify / no repost of submitted repayments |
| Balances / reports | Continue summing **all** submitted repayments regardless of method |
| Bank tests | Must remain green |
| `is_debt_purchase` | Not mandatory for bank repayments; DP types may still use Bank Account |

---

# Part 7 — Numerical examples

Roles: CIH, DPIC, AR, LOAN, DEF, IEXP (as before). Cheque 1,000 = 900 + 100.

### 7.1 Assign / 7.2 Return

Unchanged (PDC JEs; no Facility).

### 7.3a Bank Account repayment (no PDC)

Same as today’s Facility JE: Cr bank 1,000 + Facility debit/deferred legs. PDC untouched.

### 7.3b Debt Purchase Cheque settlement

One Facility JE: Cr DPIC 1,000 + Facility debit/deferred legs; PDC → Settled + Journal Reference.

### 7.4 Rollbacks

| Path | Action |
|------|--------|
| Assign / Return | Cancel PDC transition JE |
| Cheque settle cancel | Facility Repayment cancel order in §6.8 |
| Bank repay cancel | Existing Facility cancel only |

---

# Part 8 — Gap analysis & test matrix

### Gaps to implement (after approval)

- Field `repayment_method` + `post_dated_cheque` on Facility Repayment
- Client form toggles + server validation for both methods
- Credit-source branch in `build_repayment_je_plan`
- Cheque-method submit/cancel orchestration with PDC
- PDC states/builders/role/remarks (assignment family)
- Migration default for empty method

### Required test matrix

**Bank Account**

- Creation unchanged; `bank_account` mandatory; PDC not required
- Penalty supported; submit/cancel as today; JE shape unchanged
- Existing bank-payment tests green

**Debt Purchase Cheque**

- Eligible Assigned PDC selectable; non-DP Facility Type rejected
- Wrong state / already settled / amount mismatch / penalty > 0 rejected
- Bank not required; credit role = `debt_purchase_in_collection`
- Submit → Settled + links + Journal Reference
- Cancel → Assigned; failed JE cancel leaves PDC/links unchanged
- Concurrent submit cannot settle one PDC twice

**Method switching**

- Bank → cheque clears `bank_account`
- Cheque → bank clears `post_dated_cheque`
- Server rejects conflicting fields if client bypassed

### Design lock checklist

- [x] Multi-method Facility Repayment (Bank default + DP cheque additive)
- [x] Settlement **credits** DPIC
- [x] One JE; shared debit/deferred legs
- [x] Bank path unchanged / backward compatible
- [ ] Final approval to implement

---

## Explicit non-goals

- No code until approval
- Do **not** replace or restrict bank repayment
- Do **not** force `is_debt_purchase` facilities onto cheque-only repayment
- No second settlement JE; no `facility_category`; no reuse of Sent to Bank / Cleared for DP

---

*End of design document.*
