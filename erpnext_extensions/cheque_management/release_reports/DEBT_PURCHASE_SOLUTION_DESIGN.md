# Solution Design Proposal (Revised): Debt Purchase Accounting via PDC Template Architecture

**Application:** `erpnext_extensions`  
**Modules:** `cheque_management`, `facility_management`  
**Status:** Design only — **no implementation until approval**  
**Date:** 2026-07-26 (revision 6 — multi-method Facility Repayment: Bank Account + Debt Purchase Cheque)

---

## A. Existing PDC accounting “template” architecture (analysis)

### Important clarification

There is **no** separate DocType that stores per-transition Debit/Credit account pairs as editable rows.

What exists is a **layered template / policy engine**:

| Layer | Location | What it defines |
|---|---|---|
| 1. Allowed edges | `pdc_workflow_state_machine.py` → `RECEIVABLE_WORKFLOW_TRANSITIONS` / `PAYABLE_*` | Which `from → to` states are legal |
| 2. Posting decision | same file → `_RECEIVABLE_ACCOUNTING_DECISIONS` / `get_pdc_accounting_decision` | `journal_entry` vs `no_document` |
| 3. Edge documentation | `pdc_transition_accounting_registry.py` → `PDC_ACCOUNTING_TRANSITION_REGISTRY` | Declarative Dr/Cr intent + `touches_party` (policy metadata, not GL insert) |
| 4. Account **roles** resolver | `post_dated_cheque.resolve_pdc_accounts_for_journal` | Maps role keys → GL Account from **PDC Settings** + PDC field overrides |
| 5. Edge **builders** | `post_dated_cheque.build_pdc_journal_entry_data` | Per-transition code templates: which role is Debit/Credit, party, refs |
| 6. Narration templates | `PDC Settings` → `je_remark_*_template` + `utils/descriptions.render_pdc_je_text` | Configurable JE remarks (not accounts) |
| 7. Purpose + audit | `pdc_journal_entry_service._purpose_for_transition` + child **PDC Journal Reference** | Purpose tag + `pdc_transition_key` idempotency |
| 8. Posting | `post_pdc_transition_journal_entry` / `create_and_submit_journal_entry_from_payload` | Create/submit JE, append journal_reference |
| 9. Rollback | `pdc_workflow_rollback` + `accounting_rollback/*` | Reverse edges; cancel JE by transition key |

**Design implication:** Debt Purchase must be added as a **new edge template** in this stack (new role + Settings account + builder branch + decision/registry/purpose/remark), **not** as a one-off hardcoded Journal Entry outside the PDC pipeline.

### A.1 Account roles today (`resolve_pdc_accounts_for_journal`)

Returned dict keys (roles):

| Role key | PDC Settings field | Doc override |
|---|---|---|
| `cheques_in_hand` | `default_cheques_in_hand_account` | `account_paid_to` (Receivable) |
| `cheques_in_clearing` | `default_cheques_in_clearing_account` | `cheques_in_clearing_account` |
| `payable_cheque` | `default_payable_cheque_account` | Payable `account_paid_from` |
| `protested` | `default_protested_account` | — |
| `endorsement_account` | `default_endorsement_account` | `endorsement_settlement_account` |

Builders choose **roles**, not raw account names (except bank GL from Bank Account link, and party AR/AP from party masters).

### A.2 Current Receivable transition templates (code-backed)

| Transition | Decision | Debit (role/source) | Credit (role/source) | Purpose | Journal Ref |
|---|---|---|---|---|---|
| Draft → Registered | JE | `cheques_in_hand` / `account_paid_to` | Party AR (`account_paid_from` / party) | `Receive` | Yes |
| Registered → Sent to Bank | JE | `cheques_in_clearing` | `cheques_in_hand` | `Under Collection` | Yes |
| Registered → Cleared | JE | Bank GL | In Hand intermediary | `Collected` | Yes |
| Sent to Bank → Cleared | JE | Bank GL | Clearing intermediary | `Collected` | Yes |
| Sent to Bank → Bounced | JE | `protested` (else In Hand) | `cheques_in_clearing` | `Returned` | Yes |
| Registered → Returned | JE | Party AR | `cheques_in_hand` | `Returned` | Yes |
| Registered → Endorsed | JE | `endorsement_account` or holder AR | `cheques_in_hand` | `Endorsement` | Yes |
| Bounced → Returned | **no_document** | — | — | — | No |
| Returned → Replaced | JE | In Hand | Party AR | `Receive` | Yes |

Narration templates (PDC Settings) exist per edge family, e.g.:
- `je_remark_register_receivable_template`
- `je_remark_send_receivable_to_bank_template`
- `je_remark_receivable_bounced_template`
- `je_remark_return_receivable_to_party_template`
- `je_remark_endorse_receivable_template`
- clear templates for Registered/Clearing/Legal paths

### A.3 Pattern that Debt Purchase must mirror

Closest structural analogue: **`Registered → Sent to Bank`**

- Internal reclass of instrument pool  
- No party  
- Debit = dedicated intermediate role account from Settings  
- Credit = Cheques in Hand  
- Purpose = collection-family tag  
- Remark template configurable  
- Rollback cancels that transition JE  

Debt Purchase assignment is the **same pattern** with a **new intermediate role**, not reuse of `cheques_in_clearing`.

### A.4 Code map (absolute module paths under `cheque_management/`)

```
pdc_workflow_state_machine.py          # edges + JE/no_document decisions
pdc_transition_accounting_registry.py  # declarative edge specs
doctype/post_dated_cheque/post_dated_cheque.py
    resolve_pdc_accounts_for_journal()
    build_pdc_journal_entry_data()
pdc_journal_entry_service.py           # purpose, post, journal_reference
doctype/pdc_settings/pdc_settings.json # account defaults + remark templates
doctype/pdc_journal_reference/         # audit child
utils/descriptions.py                  # remark placeholder renderer
pdc_workflow_rollback.py               # rollback orchestration
accounting_rollback/pdc/*              # JE cancel by transition key
```

---

## B. Proposed Debt Purchase as new template/state family

### B.1 Workflow (unchanged business rules)

```
Registered (نزد صندوق)
    ↓
Assigned to Bank for Debt Purchase (واگذار به بانک جهت خرید دین)

Allowed:
  → Registered                 (rollback)
  → Returned                   (برگشت)
  → Debt Purchase Settled      (only via Facility Repayment)

Forbidden:
  → Cleared
```

Facility Type gate: `is_debt_purchase = 1` (Check).  
Facility links: **only at settlement**, not at assignment.  
Amount rule: `cheque_amount == principal_amount + profit_amount` exactly (business “interest” = `profit_amount`).

### B.2 New account **role** (template architecture)

Extend resolver with:

| Role key | PDC Settings field | Meaning |
|---|---|---|
| `debt_purchase_in_collection` | `default_debt_purchase_in_collection_account` | اسناد در جریان وصول خرید دین |

Optional later: per-PDC override field (like `cheques_in_clearing_account`) — not required for v1 if Settings default is mandatory when DP is used.

**This is not “just renaming clearing”.** It is a **peer role** to `cheques_in_clearing` / `endorsement_account`, selected only by Debt Purchase edge builders.

### B.3 Proposed new edge templates

#### 1) Assignment — `Registered → Assigned to Bank for Debt Purchase`

| Item | Value |
|---|---|
| Decision | `journal_entry` |
| Registry summary | Dr Debt Purchase In Collection, Cr Cheques in Hand — internal reclass; no party |
| Debit role | `debt_purchase_in_collection` |
| Credit role | `cheques_in_hand` (doc `account_paid_to` fallback) |
| Purpose (new Select value recommended) | `Debt Purchase Assignment` |
| Remark Settings field | `je_remark_assign_receivable_debt_purchase_template` |
| Journal reference | Yes — transition key `…\|Registered\|Assigned to Bank for Debt Purchase` |
| Facility links | None |

Mirror of Sent-to-Bank template shape; different debit role + purpose + remark.

#### 2) Rollback assignment — `Assigned → Registered`

| Item | Value |
|---|---|
| Mechanism | Existing rollback engine |
| Accounting | Cancel assignment JE via journal_reference for that transition key |
| Builder | No new forward JE |

#### 3) Return — `Assigned → Returned` (**separate builder branch**)

| Item | Value |
|---|---|
| Decision | `journal_entry` |
| Why not reuse Registered→Returned | That template **credits `cheques_in_hand`**; after assignment, balance is in DP role |
| Debit | Party AR (same as Registered→Returned, incl. SI slices) |
| Credit role | `debt_purchase_in_collection` |
| Purpose | `Returned` (existing) or `Debt Purchase Return` if finance wants distinct tag |
| Remark | New template `je_remark_return_debt_purchase_receivable_template` (or reuse return template text with different accounts) |
| Journal reference | Yes |

**Recommendation:** Same Returned state/validations, **new edge template** for accounts (do not reuse Registered→Returned credit of in-hand).

#### 4) Settlement — multi-method Facility Repayment

**Product rule:** Facility Repayment is **not** Debt Purchase-only. It is a multi-method document:

```
Facility Repayment
├── Bank Account                 ← existing path (default); unchanged accounting
└── Debt Purchase Cheque         ← additive; Cr debt_purchase_in_collection + PDC settle
```

##### New field

| Item | Value |
|---|---|
| Fieldname | `repayment_method` |
| Label | Repayment Method / روش پرداخت قسط |
| Options | `Bank Account` \| `Debt Purchase Cheque` |
| Default | `Bank Account` |
| Legacy | Empty/NULL → treat as Bank Account; never repost historical submitted docs |

Also: `post_dated_cheque` Link (mandatory only when method = Debt Purchase Cheque).

##### Direction rule (cheque settlement)

Assignment **debits** `debt_purchase_in_collection`. Cheque-method settlement must **credit** that role for `principal + profit`. Debiting DPIC at settlement is invalid.

##### Bank Account method (preserve exactly)

| Rule | Behavior |
|---|---|
| `bank_account` | Mandatory; settlement credit |
| `post_dated_cheque` | Hidden; must be empty |
| PDC | No validation, no state change, no Journal Reference |
| Builder | Existing `build_repayment_je_plan` bank-credit path |
| Penalty | Supported |
| Cancel | Cancel JE → clear link → refresh balances |
| `is_debt_purchase` | Not required; DP-eligible facilities may still repay via bank |

##### Debt Purchase Cheque method (additive)

| Rule | Behavior |
|---|---|
| Gate | Facility Type `is_debt_purchase = 1` (eligibility only — does not force cheque) |
| `bank_account` | Not required; not used as credit; cleared on switch to this method |
| `post_dated_cheque` | Mandatory; Receivable; state `Assigned to Bank for Debt Purchase` |
| Match | Company/currency; not already settled/linked |
| Amount | `cheque_amount == principal_amount + profit_amount` |
| Penalty v1 | `penalty_amount == 0` |
| JE | **One** JE; common debit/deferred legs; credit = `debt_purchase_in_collection` |
| After JE (atomic) | Link docs; PDC Journal Reference (purpose `Debt Purchase Settlement`); PDC → `Debt Purchase Settled` |

##### Builder branch (do not duplicate builder)

```
if repayment_method == "Bank Account":
    credit_role = bank
elif repayment_method == "Debt Purchase Cheque":
    credit_role = debt_purchase_in_collection  # PDC Settings via resolve_pdc_accounts_for_journal
# shared: loan, loan_profit, penalty?, deferred_credit?, interest_expense?
```

##### Example (Debt Purchase Cheque: 900 + 100 = 1,000)

| Side | Role | Amount |
|---|---|---|
| Dr | `loan` | 900 |
| Dr | `loan_profit` | 100 |
| Cr | `debt_purchase_in_collection` | 1,000 |
| Dr | `interest_expense` | 100 |
| Cr | `deferred_credit` | 100 |

##### UI (client) + server validation

Bank → show/require bank; hide/clear PDC.  
Cheque → show/require PDC; hide/clear bank; filter eligible Assigned cheques.  
Server enforces all rules if client bypassed.

##### Cancel — Debt Purchase Cheque (ordered, fail-safe)

1. Lock repayment + PDC  
2. Validate PDC still Settled by this repayment  
3. Cancel JE successfully  
4. Remove/cancel PDC Journal Reference  
5. PDC → Assigned to Bank for Debt Purchase  
6. Clear links  
7. Refresh balances  

If JE cancel fails → **do not** change PDC state or clear links.

##### Cancel — Bank Account

Unchanged current behavior only.

### B.4 Purpose Select extension

`PDC Journal Reference.purpose` options today:

`Receive | Under Collection | Collected | Returned | Payable Issue | Payable Clear | Endorsement | Cancel | Bounce | Replacement`

**Proposed additions:**
- `Debt Purchase Assignment`
- `Debt Purchase Settlement`

(Avoid overloading `Under Collection` / `Collected` — those mean normal clearing/bank clear.)

---

## C. Required DocType / config changes

### Facility Type
- `is_debt_purchase` Check, default 0

### PDC Settings
- `default_debt_purchase_in_collection_account` (Account link)
- `je_remark_assign_receivable_debt_purchase_template`
- `je_remark_return_debt_purchase_receivable_template` (recommended)
- optional settlement remark template if PDC side stores one

### Post Dated Cheque
- Workflow states: `Assigned to Bank for Debt Purchase`, `Debt Purchase Settled`
- Links set **only on settlement:** `debt_purchase_facility`, `debt_purchase_repayment`
- Optional later: per-doc DP account override

### Facility Repayment
- `repayment_method` Select: `Bank Account` (default) | `Debt Purchase Cheque`
- `post_dated_cheque` Link (reqd only for Debt Purchase Cheque)
- Client JS toggles + server validation for both methods
- Extend `build_repayment_je_plan` with settlement-credit-source branch only
- Cheque-method submit/cancel orchestrates PDC links, Journal Reference, state
- Migration: empty method → Bank Account semantics; no repost of old docs

**Do not** remove or alter Bank Account accounting behavior.

### PDC Journal Reference
- Extend `purpose` options (above)

### Code layers to extend (not hardcode outside)
1. State machine transitions + decisions  
2. Transition registry specs  
3. `resolve_pdc_accounts_for_journal` role  
4. `build_pdc_journal_entry_data` branches (assignment + Assigned→Returned)  
5. `_purpose_for_transition`  
6. Facility repayment JE plan branch using resolver role  
7. Rollback edges + Settled guards  

---

## D. Workflow changes (summary)

| From | To | Template |
|---|---|---|
| Registered | Assigned to Bank for Debt Purchase | New JE template (DP role Dr / In Hand Cr) |
| Assigned… | Registered | Rollback (cancel assignment JE) |
| Assigned… | Returned | New JE template (Party Dr / DP role Cr) |
| Assigned… | Debt Purchase Settled | Facility Repayment with `repayment_method = Debt Purchase Cheque` |
| Assigned… | Cleared | **Forbidden** |

---

## E. Rollback behavior

| Path | Behavior |
|---|---|
| Settled → Assigned | Cancel Facility Repayment (**Debt Purchase Cheque** method only): ordered fail-safe in §B.4; Bank Account cancel never touches PDC |
| Assigned → Registered | PDC rollback: cancel assignment JE by transition key |
| Assigned → Returned then rollback | Cancel return JE; restore Assigned (if rollback path allows) |

Settled must not roll back via PDC-only action while linked repayment is submitted.

---

## F. Accounting entries (role-based wording)

### Assignment
Dr **role** `debt_purchase_in_collection` → Settings account  
Cr **role** `cheques_in_hand`

### DP Return
Dr Party AR  
Cr **role** `debt_purchase_in_collection`

### Facility settlement

**Bank Account method** — unchanged current JE (Cr `bank` + Facility debit/deferred/penalty legs). No PDC.

**Debt Purchase Cheque method** — one JE from extended `build_repayment_je_plan`:

Cr **role** `debt_purchase_in_collection` = principal + profit  
(+ shared Facility debit/deferred legs; penalty = 0 in v1)  
(+ PDC → Debt Purchase Settled + links + Journal Reference to **this** JE)

**Rejected:** converting all repayments to DP; debiting DPIC at settlement; two-JE settlement; skipping deferred/interest-expense legs.

---

## G. Validation rules

1. Assignment requires Settings DP role account configured.  
2. Assigned → Cleared / Sent to Bank rejected.  
3. Debt Purchase Settled only via Facility Repayment with `repayment_method = Debt Purchase Cheque`.  
4. Cheque method only if `is_debt_purchase = 1` (eligibility). Bank method never requires this flag.  
5. Exact amount: `cheque_amount == principal_amount + profit_amount`.  
6. `penalty_amount == 0` for Debt Purchase Cheque (v1).  
7. No Facility links at assignment.  
8. Atomic cheque-method submit/cancel (one JE; PDC state + journal reference in same transaction).  
9. Settled→Assigned only via Facility Repayment cancel (cheque method).  
10. Bank method: `post_dated_cheque` must be empty; bank mandatory.  
11. Method switch: clear the other method’s field; server rejects conflicts.  
12. Empty/`NULL` `repayment_method` ≡ Bank Account.  

---

## H. Test matrix

### Bank Account
- Existing repayment creation unchanged  
- `bank_account` mandatory; PDC not required / rejected if set  
- Penalty supported; submit/cancel as before; JE unchanged  
- Existing bank-payment tests remain green  
- DP Facility Type may still repay via Bank Account  

### Debt Purchase Cheque
- Eligible Assigned PDC selectable  
- Non-DP Facility Type rejected  
- Wrong PDC state / already settled / amount mismatch / penalty > 0 rejected  
- Bank not required; credit role = `debt_purchase_in_collection`  
- Submit → Settled + links + Journal Reference  
- Cancel → Assigned; failed JE cancel leaves PDC/links unchanged  
- Concurrent submit cannot settle one PDC twice  

### Method switching
- Bank → cheque clears `bank_account`  
- Cheque → bank clears `post_dated_cheque`  
- Server rejects stale/conflicting fields if client bypassed  

### PDC assignment family (unit/integration/Playwright)
- Resolver role; assign/return builders; rollback assignment; no Facility link on assign  

### Regression
PDC rollback, opening import, cheque leaf, standard Facility loan (`is_debt_purchase=0`), balances include both methods.

---

## I. Corrected design stance vs prior draft

| Prior misunderstanding | Corrected stance |
|---|---|
| Treat “DP In Collection” as ad-hoc replacement for clearing | New account **role** in PDC resolver + edge templates |
| Convert Facility Repayment into DP-only flow | **Multi-method**: Bank Account (default) + Debt Purchase Cheque (additive) |
| `settlement_mode` / force cheque on DP types | Field `repayment_method`; `is_debt_purchase` = eligibility only |
| Debit DPIC at settlement | **Credit** DPIC; swap only settlement credit source |
| Two JEs for settlement | **One** Facility Repayment JE; PDC Journal Reference points at it |

---

## J. Implementation plan (after final approval — no code yet)

### Phase 1 — PDC Debt Purchase family
1. Workflow states + edges (forbid Assigned→Cleared)  
2. PDC Settings role `debt_purchase_in_collection` + remark templates  
3. Resolver + assignment / Assigned→Returned builders + purposes  
4. Rollback for assignment/return  

### Phase 2 — Facility Repayment multi-method
1. Add `repayment_method` (default Bank Account) + `post_dated_cheque`  
2. Client form toggles; server validation for both methods  
3. Credit-source branch in `build_repayment_je_plan` / prerequisites  
4. Cheque-method `on_submit` atomic: JE → links → Journal Reference → Settled  
5. Cheque-method `on_cancel` ordered fail-safe restore to Assigned  
6. Migration: treat empty method as Bank Account (no repost)  

### Phase 3 — Tests
1. Full Bank Account regression (must stay green)  
2. Debt Purchase Cheque matrix (§H)  
3. Method-switching + concurrency  
4. Playwright for assign / settle / cancel  

### Phase 4 — Reports / UX polish
Include `Debt Purchase Settled` in closed/settled cheque reporting as needed.

**No coding until this multi-method revision is approved.**
