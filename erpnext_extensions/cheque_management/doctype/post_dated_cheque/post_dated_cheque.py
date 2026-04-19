# Copyright (c) 2025, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Post Dated Cheque **Document** controller.

**Module map (concerns are split across files)**

* **Workflow graph & accounting policy** — ``pdc_workflow_state_machine`` (allowed transitions,
  ``get_pdc_accounting_decision`` → journal vs no document).
* **``cheque_status`` labels** — ``pdc_workflow_to_cheque_status`` (maps ``workflow_state`` + direction).
* **JE payloads (no GL insert here)** — ``build_pdc_journal_entry_data`` in this module; receivable
  clearing helpers in ``pdc_receivable_accounting``.
* **Allocation rows (planning / reporting only)** — ``pdc_allocation`` (summary sync + row validation).
* **Idempotency keys & JE posting** — ``pdc_accounting_idempotency``, ``pdc_journal_entry_service``.

**Journal-centric lifecycle**

All workflow GL posting uses **Journal Entry** only. **Payment Entry** is not part of the PDC
lifecycle architecture.

**Business rules**

* **Receivable:** party (AR) at **Registered** (Draft → Registered JE). **Cleared:** Dr bank, Cr CIH /
  clearing / protested — **no party** on clear lines.
* **Payable:** party (AP) at **Issued** — Purchase Invoice settlement via standard JE ``reference_type`` /
  ``reference_name`` on supplier payable rows when allocations map to PI (direct or PR→PI). **Cleared:**
  Dr notes-payable pool, Cr bank — **no party** / **no invoice reference** (liability vs bank only).
* **Allocations** drive PI references on payable **party** lines only; see ``pdc_payable_purchase_invoice_je_refs``.

**Document hooks**

* ``validate`` / ``on_update`` — :meth:`_pdc_pre_save_workflow_sequence`, :meth:`_pdc_post_save_accounting_sequence`.
* ``journal_references`` — one row per posted JE; ``holder_history`` — receivable endorsement audit.

Design reference: ``PDC_DESIGN_FINAL_FA.md``; English notes: ``../../DEVELOPER.md``.
"""

import logging

import frappe
from frappe.model.document import Document
from frappe.utils import cint, getdate, now_datetime

from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	PDC_ACCOUNTING_JOURNAL_ENTRY,
	PDC_ACCOUNTING_NO_DOCUMENT,
	PDC_VALIDATION_BOUNCED_REQUIRES_RECEIVABLE_SENT_TO_BANK,
	PDC_VALIDATION_ENDORSED_RECEIVABLE_ONLY,
	PDC_VALIDATION_ISSUED_PAYABLE_ONLY,
	PDC_VALIDATION_SENT_TO_BANK_RECEIVABLE_ONLY,
	WORKFLOW_BOUNCED,
	WORKFLOW_CANCELLED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ENDORSED,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_REPLACED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
	WORKFLOW_UNDER_LEGAL_ACTION,
	get_pdc_accounting_decision,
	get_pdc_workflow_transition_validation_error,
	is_workflow_previous_empty,
	normalize_workflow_state_value,
)
from erpnext_extensions.cheque_management.pdc_receivable_accounting import (
	receivable_intermediary_account_for_bank_clear,
)
from erpnext_extensions.cheque_management.pdc_allocation import (
	autofill_pdc_allocations_from_parent_reference,
	is_pdc_allocation_draft_only as _is_pdc_allocation_draft_only,
	is_pdc_allocation_effective as _is_pdc_allocation_effective,
	pdc_allocation_effective_milestone_workflow_state,
	sanitize_pdc_allocation_child_rows,
	sync_pdc_allocation_summary_amounts,
	validate_pdc_allocation_rows,
	validate_pdc_allocation_workflow_milestone,
)
from erpnext_extensions.cheque_management.pdc_payable_purchase_invoice_je_refs import (
	payable_purchase_invoice_settlement_slices,
)
from erpnext_extensions.cheque_management.pdc_workflow_to_cheque_status import (
	CHEQUE_STATUS_RETURNED_FROM_PAYEE,
	CHEQUE_STATUS_RETURNED_TO_CUSTOMER,
	map_workflow_state_to_cheque_status,
)

_pdc_accounting_logger = logging.getLogger("erpnext_extensions.cheque_management")


def _log_debug_journal_entry_payload(doc, from_state: str, to_state: str, payload: dict | None) -> None:
	"""Optional debug logging for JE payloads (duplicate-party investigations)."""
	if not payload:
		return
	rows = payload.get("accounts") or []
	party_lines = [
		(i, r.get("account"), r.get("party_type"), r.get("party"))
		for i, r in enumerate(rows)
		if r.get("party_type") or r.get("party")
	]
	_pdc_accounting_logger.info(
		"[PDC_ACCOUNTING_TRACE] JE payload | pdc=%s | cheque_direction=%s | from=%s | to=%s | "
		"party_on_lines=%s | accounts=%s",
		getattr(doc, "name", None),
		getattr(doc, "cheque_direction", None),
		from_state,
		to_state,
		party_lines,
		[r.get("account") for r in rows],
	)


def _strip_link_name_or_none(value) -> str | None:
	"""Return stripped Link / Dynamic Link value, or ``None`` if empty."""
	if not value:
		return None
	s = str(value).strip()
	return s or None


# Holder History child row reason when workflow moves to Endorsed (Receivable).
PDC_HOLDER_HISTORY_REASON_ENDORSEMENT = "Endorsement — transfer to new holder"

# Journal Entry remarks — Receivable Draft → Registered
PDC_JE_REMARK_REGISTER_RECEIVABLE_CHEQUE = "Register receivable cheque"
# Journal Entry remarks — Receivable Registered → Sent to Bank
PDC_JE_REMARK_SEND_RECEIVABLE_CHEQUE_TO_BANK = "Send receivable cheque to bank"
# Journal Entry remarks — Receivable Sent to Bank → Bounced
PDC_JE_REMARK_RECEIVABLE_CHEQUE_BOUNCED = "Receivable cheque bounced"
# Journal Entry remarks — Receivable Registered → Returned
PDC_JE_REMARK_RETURN_RECEIVABLE_CHEQUE_TO_PARTY = "Return receivable cheque to party"
# Journal Entry remarks — Receivable Registered → Endorsed
PDC_JE_REMARK_ENDORSE_RECEIVABLE_CHEQUE = "Endorse receivable cheque"
# Journal Entry remarks — Payable Draft → Registered (supplier / PI settlement)
PDC_JE_REMARK_REGISTER_PAYABLE_CHEQUE = "Register payable cheque (supplier settlement)"
# Legacy label kept for older remarks / docs; new postings use REGISTER variant above.
PDC_JE_REMARK_ISSUE_PAYABLE_CHEQUE = "Issue payable cheque"
# Journal Entry remarks — Payable Issued → Returned
PDC_JE_REMARK_RETURNED_PAYABLE_CHEQUE_FROM_PAYEE = "Returned payable cheque from payee"
# Journal Entry remarks — Payable Issued → Cancelled
PDC_JE_REMARK_CANCEL_ISSUED_PAYABLE_CHEQUE = "Cancel issued payable cheque"
# Journal Entry remarks — replacement transitions (see TODO(accounting) in builder)
PDC_JE_REMARK_REPLACE_RECEIVABLE_AFTER_BOUNCE = "Replace receivable cheque after bank bounce"
PDC_JE_REMARK_REPLACE_RECEIVABLE_AFTER_RETURN = "Replace receivable cheque after return"
PDC_JE_REMARK_REPLACE_ISSUED_PAYABLE_CHEQUE = "Replace issued payable cheque"
PDC_JE_REMARK_REPLACE_RETURNED_PAYABLE_CHEQUE = "Replace returned payable cheque"
PDC_JE_REMARK_CLEAR_PAYABLE_CHEQUE = "Clear payable cheque"
# Journal Entry remarks — Payable Registered → Cancelled (reverse register settlement)
PDC_JE_REMARK_CANCEL_REGISTERED_PAYABLE_CHEQUE = "Cancel registered payable cheque (reverse supplier settlement)"

# Journal Entry remarks — Receivable → Cleared (Dr bank, Cr intermediary; no party)
PDC_JE_REMARK_CLEAR_RECEIVABLE_REGISTERED = (
	"Receivable PDC cleared at bank vs cheques in hand (no party on clear)."
)
PDC_JE_REMARK_CLEAR_RECEIVABLE_CLEARING = (
	"Receivable PDC cleared at bank vs cheques in clearing (no party on clear)."
)
PDC_JE_REMARK_CLEAR_RECEIVABLE_LEGAL = (
	"Receivable PDC cleared at bank after legal follow-up vs protested/clearing/in-hand (no party on clear)."
)
#
# NOTE: This app does not use Payment Entry for PDC lifecycle.

def _resolve_holder_party_type_and_party(doc) -> tuple[str | None, str | None]:
	"""Holder for endorsement / display: ``holder_party*`` if set, else drawer ``party*``."""
	if not doc:
		return None, None
	if isinstance(doc, dict):
		ht = doc.get("holder_party_type") or doc.get("party_type")
		hp = doc.get("holder_party") or doc.get("party")
	else:
		ht = doc.holder_party_type or doc.party_type
		hp = doc.holder_party or doc.party
	return _strip_link_name_or_none(ht), _strip_link_name_or_none(hp)


def get_accounting_action(doc, previous_workflow_state: str | None) -> str:
	"""Return which accounting artefact applies for the transition into the current save.

	PDC lifecycle is **Journal Entry only** — expect ``journal_entry`` or ``no_document`` only.

	Combines ``doc.cheque_direction``, ``previous_workflow_state`` (workflow before this
	change), and ``doc.workflow_state`` (target). Delegates to
	:func:`erpnext_extensions.cheque_management.pdc_workflow_state_machine.get_pdc_accounting_decision`.
	States are normalized with :func:`normalize_workflow_state_value` (blank/``None``
	→ **Draft**).

	When the state machine has no explicit rule for the edge (``None`` from
	``get_pdc_accounting_decision``), returns ``no_document`` — same default as
	undefined Payable/Receivable policy.

	Returns:
		One of ``journal_entry`` or ``no_document`` (see ``PDC_ACCOUNTING_*`` in
		``pdc_workflow_state_machine.py``).
	"""
	cheque_direction = getattr(doc, "cheque_direction", None) or ""
	to_state = normalize_workflow_state_value(getattr(doc, "workflow_state", None))
	from_state = normalize_workflow_state_value(previous_workflow_state)
	decision = get_pdc_accounting_decision(cheque_direction, from_state, to_state)
	# Enforce lifecycle rule: selector can only yield journal_entry or no_document.
	return PDC_ACCOUNTING_JOURNAL_ENTRY if decision == PDC_ACCOUNTING_JOURNAL_ENTRY else PDC_ACCOUNTING_NO_DOCUMENT


def _get_party_account_or_company_default(party_type, party, company, account_kind="receivable"):
	"""Get party account; fallback to company default. account_kind: receivable or payable."""
	# ERPNext's party account helper is primarily designed for Customer/Supplier.
	# For Employee/Shareholder we intentionally fallback to company defaults.
	if party_type in ("Employee", "Shareholder"):
		if account_kind == "receivable":
			return frappe.get_cached_value("Company", company, "default_receivable_account")
		return frappe.get_cached_value("Company", company, "default_payable_account")
	try:
		from erpnext.accounts.party import get_party_account
		account = get_party_account(party_type, party, company)
		if account:
			return account
	except Exception:
		pass
	# Fallback: company default
	if account_kind == "receivable":
		return frappe.get_cached_value("Company", company, "default_receivable_account")
	return frappe.get_cached_value("Company", company, "default_payable_account")


def _get_cheques_in_hand_account_for_company(company):
	"""PDC Settings: Cheques in Hand account for company, or None if not configured."""
	if not company:
		return None
	settings_name = frappe.db.get_value("PDC Settings", {"company": company}, "name") or company
	if not settings_name or not frappe.db.exists("PDC Settings", settings_name):
		return None
	return frappe.db.get_value("PDC Settings", settings_name, "default_cheques_in_hand_account")


def _get_pdc_settings_for_company(company: str):
	"""Fetch ``PDC Settings`` doc for a given company (by name or company field)."""
	if not company:
		return None
	name = frappe.db.get_value("PDC Settings", {"company": company}, "name") or company
	if not name or not frappe.db.exists("PDC Settings", name):
		return None
	return frappe.get_doc("PDC Settings", name)


def _pdc_company_policy_flags(company: str | None) -> dict[str, int]:
	"""Runtime flags from PDC Settings (defaults match DocType defaults when no row exists)."""
	st = _get_pdc_settings_for_company(company) if company else None
	if not st:
		return {"allow_endorsement": 1, "require_sayad_registration": 0}
	return {
		"allow_endorsement": cint(st.get("allow_endorsement", 1)),
		"require_sayad_registration": cint(st.get("require_sayad_registration", 0)),
	}


def resolve_pdc_accounts_for_journal(doc, settings=None):
	"""Resolve GL accounts for PDC Journal Entry lines from **PDC Settings** with document fallbacks.

	Uses these settings fields when set:

	* ``default_cheques_in_hand_account``
	* ``default_cheques_in_clearing_account``
	* ``default_payable_cheque_account``
	* ``default_protested_account``
	* ``default_endorsement_account`` (receivable endorsement debit when no per-PDC override)

	Fallbacks (when the setting is empty):

	* **Cheques in Hand** → ``doc.account_paid_to`` (Receivable: operational Cheques in Hand side).
	* **Endorsement debit** → ``doc.endorsement_settlement_account`` if set (takes precedence over setting);
	  else holder receivable when endorsing to a different party than ``party``.
	* Other roles have no DocType counterpart and remain unset unless configured in **PDC Settings**.

	:param doc: :class:`~frappe.model.document.Document` **Post Dated Cheque** (or any object with
		``company``, ``account_paid_to``, etc.).
	:param settings: optional **PDC Settings** document; if omitted, loaded from ``doc.company``.

	Returns:
		Dict with keys: ``cheques_in_hand``, ``cheques_in_clearing``, ``payable_cheque``,
		``protested``, ``endorsement_account`` — each value is an Account name or ``None``.
	"""
	if settings is None and doc is not None:
		company = getattr(doc, "company", None)
		settings = _get_pdc_settings_for_company(company) if company else None

	def _s(field: str) -> str | None:
		if not settings:
			return None
		return _strip_link_name_or_none(settings.get(field))

	out = {
		"cheques_in_hand": _s("default_cheques_in_hand_account")
		or _strip_link_name_or_none(getattr(doc, "account_paid_to", None) if doc else None),
		"cheques_in_clearing": _strip_link_name_or_none(
			getattr(doc, "cheques_in_clearing_account", None) if doc else None
		)
		or _s("default_cheques_in_clearing_account"),
		"payable_cheque": _s("default_payable_cheque_account"),
		"protested": _s("default_protested_account"),
		"endorsement_account": _s("default_endorsement_account"),
	}
	return out


def build_pdc_journal_entry_data(doc, from_state: str, to_state: str, posting_date=None):
	"""Prepare Journal Entry data dict for supported PDC workflow transitions.

	This builder is the **primary** vehicle for journal-centric lifecycle posting: party-affecting
	lines belong on Registered (Receivable), Registered (Payable — Draft → Registered settlement),
	Return-to-party (Receivable), and
	optionally **Endorsement** (Receivable) **only for the endorsed holder’s** receivable — never the
	drawer’s party again. **Cleared** transitions use bank vs intermediary/pool lines **without** party.

	Does **not** insert any Journal Entry; only returns a structured payload:

	* ``voucher_type`` — ``\"Bank Entry\"`` for bank-facing clear transitions (``→ Cleared``),
	  otherwise ``\"Journal Entry\"``
	* ``posting_date`` — supplied value or today's date
	* ``remarks`` — user-facing description
	* ``accounts`` — list of debit/credit rows

	Replacement transitions (Receivable/Payable) use working defaults with ``TODO(accounting)``
	comments in-code; see design doc §9.1.

	Payable **Purchase Invoice** linkage on party/AP rows (register-settlement and symmetric reversals) comes from
	``pdc_payable_purchase_invoice_je_refs`` when allocation rows resolve to PI (direct or via PR).
	"""
	if not posting_date:
		posting_date = getdate()

	if doc.cheque_direction not in (CHEQUE_DIRECTION_RECEIVABLE, CHEQUE_DIRECTION_PAYABLE):
		return None

	decision = get_pdc_accounting_decision(doc.cheque_direction, from_state, to_state)
	if decision != "journal_entry":
		# PE and no_document transitions must not go through the JE builder (avoids silent wrong accounts).
		return None

	settings = _get_pdc_settings_for_company(doc.company)
	acc = resolve_pdc_accounts_for_journal(doc, settings)

	def _payable_party_issue_debit_lines(debit_account: str) -> list[dict]:
		slices = payable_purchase_invoice_settlement_slices(doc)
		if slices:
			return [
				{
					"account": debit_account,
					"debit_in_account_currency": amt,
					"party_type": doc.party_type,
					"party": doc.party,
					"reference_type": "Purchase Invoice",
					"reference_name": pnm,
				}
				for pnm, amt in slices
			]
		return [
			{
				"account": debit_account,
				"debit_in_account_currency": doc.cheque_amount,
				"party_type": doc.party_type,
				"party": doc.party,
			}
		]

	def _payable_party_reverse_credit_lines(credit_account: str) -> list[dict]:
		slices = payable_purchase_invoice_settlement_slices(doc)
		if slices:
			return [
				{
					"account": credit_account,
					"credit_in_account_currency": amt,
					"party_type": doc.party_type,
					"party": doc.party,
					"reference_type": "Purchase Invoice",
					"reference_name": pnm,
				}
				for pnm, amt in slices
			]
		return [
			{
				"account": credit_account,
				"credit_in_account_currency": doc.cheque_amount,
				"party_type": doc.party_type,
				"party": doc.party,
			}
		]

	def _base(remark: str) -> dict:
		voucher_type = "Bank Entry" if to_state == WORKFLOW_CLEARED else "Journal Entry"
		return {
			"voucher_type": voucher_type,
			"posting_date": posting_date,
			"remarks": remark,
			"accounts": [],
		}

	je: dict | None = None

	def _validate_receivable_party_integrity(payload: dict) -> None:
		"""Receivable integrity: party lines allowed only for Register/Return-to-party and holder-only endorsement.

		Rules:
		- Party is allowed in Draft → Registered and Registered → Returned (must be present).
		- Registered → Endorsed: party lines (if any) must be **only** the endorsed holder — never the drawer.
		- Party must not appear on Sent to Bank, Cleared, Bounced, or other receivable edges.
		"""
		if doc.cheque_direction != CHEQUE_DIRECTION_RECEIVABLE:
			return
		allowed_party_edges = {
			(WORKFLOW_DRAFT, WORKFLOW_REGISTERED),
			(WORKFLOW_REGISTERED, WORKFLOW_RETURNED),
		}
		edge = (from_state, to_state)
		rows = payload.get("accounts") or []

		if edge == (WORKFLOW_REGISTERED, WORKFLOW_ENDORSED):
			holder_pt = _strip_link_name_or_none(getattr(doc, "holder_party_type", None)) or _strip_link_name_or_none(
				getattr(doc, "party_type", None)
			)
			holder_p = _strip_link_name_or_none(getattr(doc, "holder_party", None)) or _strip_link_name_or_none(
				getattr(doc, "party", None)
			)
			for r in rows:
				pt, p = r.get("party_type"), r.get("party")
				if not pt and not p:
					continue
				if not holder_pt or not holder_p:
					frappe.throw(
						frappe._(
							"Receivable PDC accounting integrity: Endorsement Journal Entry cannot use Party on lines without holder_party_type and holder_party on the PDC."
						),
						title=frappe._("PDC accounting integrity"),
					)
				if _strip_link_name_or_none(pt) != holder_pt or _strip_link_name_or_none(p) != holder_p:
					frappe.throw(
						frappe._(
							"Receivable PDC accounting integrity: Endorsement may only post Party dimensions for the endorsed holder ({0} / {1}), not the drawer or any other party."
						).format(holder_pt, holder_p),
						title=frappe._("PDC accounting integrity"),
					)
			return

		has_party = any((r.get("party_type") or r.get("party")) for r in rows)
		if edge in allowed_party_edges:
			# When party is allowed, enforce that it is present (prevents silent partial settlement).
			if not has_party:
				frappe.throw(
					frappe._(
						"Receivable PDC accounting integrity: Party must be present on Journal Entry lines for transition {0} → {1}."
					).format(from_state, to_state),
					title=frappe._("PDC accounting integrity"),
				)
			return

		# Disallow party everywhere else (explicitly includes Sent to Bank / Cleared / Bounced).
		if has_party:
			frappe.throw(
				frappe._(
					"Receivable PDC accounting integrity: Party must NOT be present on Journal Entry lines for transition {0} → {1}."
				).format(from_state, to_state),
				title=frappe._("PDC accounting integrity"),
			)

	def _validate_payable_party_integrity(payload: dict) -> None:
		"""Payable integrity for the final model transitions.

		Applies only to these edges (scope of the payable final model):
		- Draft → Registered: party must be present (supplier / PI settlement)
		- Registered → Cancelled: party must be present (reverse register settlement)
		- Issued → Returned / Cancelled / Replaced: party must be present (reverse)
		- Issued → Cleared: party must NOT be present (bank vs payable cheque pool only)

		Other Payable edges are not constrained by this validator unless listed above.
		"""
		if doc.cheque_direction != CHEQUE_DIRECTION_PAYABLE:
			return
		edge = (from_state, to_state)
		rows = payload.get("accounts") or []
		has_party = any((r.get("party_type") or r.get("party")) for r in rows)

		party_required_edges = {
			(WORKFLOW_DRAFT, WORKFLOW_REGISTERED),
			(WORKFLOW_REGISTERED, WORKFLOW_CANCELLED),
			(WORKFLOW_ISSUED, WORKFLOW_RETURNED),
			(WORKFLOW_ISSUED, WORKFLOW_CANCELLED),
			(WORKFLOW_ISSUED, WORKFLOW_REPLACED),
		}
		if edge in party_required_edges:
			if not has_party:
				frappe.throw(
					frappe._(
						"Payable PDC accounting integrity: Party must be present on Journal Entry lines for transition {0} → {1}."
					).format(from_state, to_state),
					title=frappe._("PDC accounting integrity"),
				)
			return

		if edge == (WORKFLOW_ISSUED, WORKFLOW_CLEARED) and has_party:
			# Explicit business rule: Payable clear must not touch party at all.
			frappe.throw(
				frappe._(
					"Payable PDC accounting integrity: Party must NOT be present on Journal Entry lines for transition {0} → {1} (Cleared must not touch Party)."
				).format(from_state, to_state),
				title=frappe._("PDC accounting integrity"),
			)

		if edge == (WORKFLOW_ISSUED, WORKFLOW_CLEARED):
			# Explicit business rule: Cleared must only move value between payable cheque pool and bank.
			expected_pool = acc.get("payable_cheque")
			expected_bank = _pdc_bank_gl_account(doc)
			rows = payload.get("accounts") or []
			if not expected_pool or not expected_bank:
				# Builder should have returned None earlier; keep this as a defensive guard.
				frappe.throw(
					frappe._(
						"Payable PDC accounting integrity: Cannot validate Cleared payload without Payable Cheque account and Bank GL."
					),
					title=frappe._("PDC accounting integrity"),
				)
			if len(rows) != 2:
				frappe.throw(
					frappe._(
						"Payable PDC accounting integrity: Cleared Journal Entry must have exactly 2 lines (Dr Payable Cheque account, Cr Bank)."
					),
					title=frappe._("PDC accounting integrity"),
				)
			debit_rows = [
				r for r in rows if float(r.get("debit_in_account_currency") or 0) and not float(r.get("credit_in_account_currency") or 0)
			]
			credit_rows = [
				r for r in rows if float(r.get("credit_in_account_currency") or 0) and not float(r.get("debit_in_account_currency") or 0)
			]
			if len(debit_rows) != 1 or len(credit_rows) != 1:
				frappe.throw(
					frappe._(
						"Payable PDC accounting integrity: Cleared Journal Entry must be one debit line and one credit line (no mixed debit/credit lines)."
					),
					title=frappe._("PDC accounting integrity"),
				)
			dr = debit_rows[0]
			cr = credit_rows[0]
			if _strip_link_name_or_none(dr.get("account")) != expected_pool or _strip_link_name_or_none(cr.get("account")) != expected_bank:
				frappe.throw(
					frappe._(
						"Payable PDC accounting integrity: Cleared must only use Dr {0} (Payable Cheque account) and Cr {1} (Bank)."
					).format(expected_pool, expected_bank),
					title=frappe._("PDC accounting integrity"),
				)

	def _return_je(payload: dict) -> dict:
		_validate_receivable_party_integrity(payload)
		_validate_payable_party_integrity(payload)
		_log_debug_journal_entry_payload(doc, from_state, to_state, payload)
		return payload

	# --- Receivable transitions ---
	if doc.cheque_direction == CHEQUE_DIRECTION_RECEIVABLE:
		# Draft -> Registered: Dr Cheques in Hand (``account_paid_to``), Cr party AR (``account_paid_from`` or party receivable).
		if from_state == WORKFLOW_DRAFT and to_state == WORKFLOW_REGISTERED:
			debit_account = _strip_link_name_or_none(getattr(doc, "account_paid_to", None)) or acc["cheques_in_hand"]
			credit_account = _strip_link_name_or_none(getattr(doc, "account_paid_from", None)) or _get_party_account_or_company_default(
				doc.party_type, doc.party, doc.company, "receivable"
			)
			if not debit_account or not credit_account:
				return None
			remark = frappe._(PDC_JE_REMARK_REGISTER_RECEIVABLE_CHEQUE)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			je["accounts"] = [
				{
					"account": debit_account,
					"debit_in_account_currency": doc.cheque_amount,
				},
				{
					"account": credit_account,
					"credit_in_account_currency": doc.cheque_amount,
					"party_type": doc.party_type,
					"party": doc.party,
				},
			]
			return _return_je(je)

		# Registered -> Sent to Bank: Dr Clearing, Cr Cheques in Hand (``account_paid_to`` / resolver).
		if from_state == WORKFLOW_REGISTERED and to_state == WORKFLOW_SENT_TO_BANK:
			if not acc["cheques_in_clearing"]:
				return None
			credit_account = _strip_link_name_or_none(getattr(doc, "account_paid_to", None)) or acc["cheques_in_hand"]
			if not credit_account:
				return None
			remark = frappe._(PDC_JE_REMARK_SEND_RECEIVABLE_CHEQUE_TO_BANK)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			je["accounts"] = [
				{
					"account": acc["cheques_in_clearing"],
					"debit_in_account_currency": doc.cheque_amount,
				},
				{
					"account": credit_account,
					"credit_in_account_currency": doc.cheque_amount,
				},
			]
			return _return_je(je)

		# Registered / Sent to Bank / Under Legal Action -> Cleared: Dr Bank GL, Cr intermediary — **no party**.
		if to_state == WORKFLOW_CLEARED and from_state in (
			WORKFLOW_REGISTERED,
			WORKFLOW_SENT_TO_BANK,
			WORKFLOW_UNDER_LEGAL_ACTION,
		):
			bank_gl = _pdc_bank_gl_account(doc)
			if not bank_gl:
				return None
			_pdc_validate_clearing_bank_ledger_account(doc, bank_gl)
			credit_account = receivable_intermediary_account_for_bank_clear(doc, from_state, acc)
			if not credit_account:
				return None
			_pdc_validate_receivable_clear_accounts_no_party_gl(bank_gl, credit_account)
			if from_state == WORKFLOW_REGISTERED:
				remark_base = PDC_JE_REMARK_CLEAR_RECEIVABLE_REGISTERED
			elif from_state == WORKFLOW_SENT_TO_BANK:
				remark_base = PDC_JE_REMARK_CLEAR_RECEIVABLE_CLEARING
			else:
				remark_base = PDC_JE_REMARK_CLEAR_RECEIVABLE_LEGAL
			remark = frappe._(remark_base)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			je["accounts"] = [
				{
					"account": bank_gl,
					"debit_in_account_currency": doc.cheque_amount,
				},
				{
					"account": credit_account,
					"credit_in_account_currency": doc.cheque_amount,
				},
			]
			return _return_je(je)

		# Sent to Bank -> Bounced: Cr Clearing; Dr protested (preferred) or Cheques in Hand.
		if from_state == WORKFLOW_SENT_TO_BANK and to_state == WORKFLOW_BOUNCED:
			if not acc["cheques_in_clearing"]:
				return None
			debit_account = acc["protested"] or acc["cheques_in_hand"]
			if not debit_account:
				return None
			remark = frappe._(PDC_JE_REMARK_RECEIVABLE_CHEQUE_BOUNCED)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			je["accounts"] = [
				{
					"account": debit_account,
					"debit_in_account_currency": doc.cheque_amount,
				},
				{
					"account": acc["cheques_in_clearing"],
					"credit_in_account_currency": doc.cheque_amount,
				},
			]
			return _return_je(je)

		# Bounced -> Replaced (Receivable): Dr Cheques in Hand (replacement instrument), Cr protested pool.
		# TODO(accounting): Confirm with finance — offsets dishonoured balance; may need clearing/protest split or link to ``replaces_cheque``.
		if from_state == WORKFLOW_BOUNCED and to_state == WORKFLOW_REPLACED:
			if not acc["protested"]:
				return None
			debit_account = _strip_link_name_or_none(getattr(doc, "account_paid_to", None)) or acc["cheques_in_hand"]
			if not debit_account:
				return None
			remark = frappe._(PDC_JE_REMARK_REPLACE_RECEIVABLE_AFTER_BOUNCE)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			je["accounts"] = [
				{
					"account": debit_account,
					"debit_in_account_currency": doc.cheque_amount,
				},
				{
					"account": acc["protested"],
					"credit_in_account_currency": doc.cheque_amount,
				},
			]
			return _return_je(je)

		# Returned -> Replaced (Receivable): Dr Cheques in Hand, Cr party AR (inverse of Registered->Returned).
		# TODO(accounting): Tie to ``replaces_cheque`` / prior return JE — confirm amounts and timing.
		if from_state == WORKFLOW_RETURNED and to_state == WORKFLOW_REPLACED:
			debit_account = _strip_link_name_or_none(getattr(doc, "account_paid_to", None)) or acc["cheques_in_hand"]
			credit_account = _strip_link_name_or_none(getattr(doc, "account_paid_from", None)) or _get_party_account_or_company_default(
				doc.party_type, doc.party, doc.company, "receivable"
			)
			if not debit_account or not credit_account:
				return None
			remark = frappe._(PDC_JE_REMARK_REPLACE_RECEIVABLE_AFTER_RETURN)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			je["accounts"] = [
				{
					"account": debit_account,
					"debit_in_account_currency": doc.cheque_amount,
				},
				{
					"account": credit_account,
					"credit_in_account_currency": doc.cheque_amount,
					"party_type": doc.party_type,
					"party": doc.party,
				},
			]
			return _return_je(je)

		# Registered -> Returned: Dr party AR (``account_paid_from`` / party receivable), Cr Cheques in Hand (``account_paid_to`` / resolver).
		if from_state == WORKFLOW_REGISTERED and to_state == WORKFLOW_RETURNED:
			debit_account = _strip_link_name_or_none(getattr(doc, "account_paid_from", None)) or _get_party_account_or_company_default(
				doc.party_type, doc.party, doc.company, "receivable"
			)
			credit_account = _strip_link_name_or_none(getattr(doc, "account_paid_to", None)) or acc["cheques_in_hand"]
			if not debit_account or not credit_account:
				return None
			remark = frappe._(PDC_JE_REMARK_RETURN_RECEIVABLE_CHEQUE_TO_PARTY)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			je["accounts"] = [
				{
					"account": debit_account,
					"debit_in_account_currency": doc.cheque_amount,
					"party_type": doc.party_type,
					"party": doc.party,
				},
				{
					"account": credit_account,
					"credit_in_account_currency": doc.cheque_amount,
				},
			]
			return _return_je(je)

		# Registered -> Endorsed: Dr settlement GL (preferred) or endorsed holder AR — Cr Cheques in Hand.
		# No bank / PE; drawer (party) must not appear on lines (registration already credited AR).
		if from_state == WORKFLOW_REGISTERED and to_state == WORKFLOW_ENDORSED:
			holder_party_type = _strip_link_name_or_none(getattr(doc, "holder_party_type", None)) or _strip_link_name_or_none(
				getattr(doc, "party_type", None)
			)
			holder_party = _strip_link_name_or_none(getattr(doc, "holder_party", None)) or _strip_link_name_or_none(
				getattr(doc, "party", None)
			)
			if not holder_party_type or not holder_party:
				return None
			credit_account = _strip_link_name_or_none(getattr(doc, "account_paid_to", None)) or acc["cheques_in_hand"]
			if not credit_account:
				return None
			doc_settlement = _strip_link_name_or_none(getattr(doc, "endorsement_settlement_account", None))
			debit_account = doc_settlement or acc["endorsement_account"]
			debit_row: dict
			if debit_account:
				debit_row = {
					"account": debit_account,
					"debit_in_account_currency": doc.cheque_amount,
				}
			else:
				orig_pt = _strip_link_name_or_none(getattr(doc, "party_type", None))
				orig_p = _strip_link_name_or_none(getattr(doc, "party", None))
				if orig_pt == holder_party_type and orig_p == holder_party:
					return None
				holder_account = _get_party_account_or_company_default(
					holder_party_type, holder_party, doc.company, "receivable"
				)
				if not holder_account:
					return None
				debit_row = {
					"account": holder_account,
					"debit_in_account_currency": doc.cheque_amount,
					"party_type": holder_party_type,
					"party": holder_party,
				}
			remark = frappe._(PDC_JE_REMARK_ENDORSE_RECEIVABLE_CHEQUE)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			je["accounts"] = [
				debit_row,
				{
					"account": credit_account,
					"credit_in_account_currency": doc.cheque_amount,
				},
			]
			return _return_je(je)

	# --- Payable transitions ---
	if doc.cheque_direction == CHEQUE_DIRECTION_PAYABLE:
		# Draft -> Registered: Dr party payable (PI refs on AP rows), Cr notes payable pool — supplier settlement.
		if from_state == WORKFLOW_DRAFT and to_state == WORKFLOW_REGISTERED:
			if not acc["payable_cheque"]:
				return None
			debit_account = _strip_link_name_or_none(getattr(doc, "account_paid_to", None)) or _get_party_account_or_company_default(
				doc.party_type, doc.party, doc.company, "payable"
			)
			if not debit_account:
				return None
			remark = frappe._(PDC_JE_REMARK_REGISTER_PAYABLE_CHEQUE)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			party_debits = _payable_party_issue_debit_lines(debit_account)
			je["accounts"] = party_debits + [
				{
					"account": acc["payable_cheque"],
					"credit_in_account_currency": doc.cheque_amount,
				}
			]
			return _return_je(je)

		# Registered -> Cancelled: Dr notes payable pool, Cr party payable — reverse Draft→Registered settlement.
		if from_state == WORKFLOW_REGISTERED and to_state == WORKFLOW_CANCELLED:
			if not acc["payable_cheque"]:
				return None
			credit_account = _strip_link_name_or_none(getattr(doc, "account_paid_to", None)) or _get_party_account_or_company_default(
				doc.party_type, doc.party, doc.company, "payable"
			)
			if not credit_account:
				return None
			remark = frappe._(PDC_JE_REMARK_CANCEL_REGISTERED_PAYABLE_CHEQUE)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			party_credits = _payable_party_reverse_credit_lines(credit_account)
			je["accounts"] = [
				{
					"account": acc["payable_cheque"],
					"debit_in_account_currency": doc.cheque_amount,
				},
				*party_credits,
			]
			return _return_je(je)

		# Issued -> Returned: Dr notes payable pool, Cr party payable (``account_paid_to`` / settlement).
		if from_state == WORKFLOW_ISSUED and to_state == WORKFLOW_RETURNED:
			if not acc["payable_cheque"]:
				return None
			credit_account = _strip_link_name_or_none(getattr(doc, "account_paid_to", None)) or _get_party_account_or_company_default(
				doc.party_type, doc.party, doc.company, "payable"
			)
			if not credit_account:
				return None
			remark = frappe._(PDC_JE_REMARK_RETURNED_PAYABLE_CHEQUE_FROM_PAYEE)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			party_credits = _payable_party_reverse_credit_lines(credit_account)
			je["accounts"] = [
				{
					"account": acc["payable_cheque"],
					"debit_in_account_currency": doc.cheque_amount,
				},
				*party_credits,
			]
			return _return_je(je)

		# Issued -> Replaced: same shape as Issued -> Returned (reverse notes-payable pool to party).
		# TODO(accounting): May require paired JE for the new cheque / link via ``replaces_cheque`` — policy TBD.
		if from_state == WORKFLOW_ISSUED and to_state == WORKFLOW_REPLACED:
			if not acc["payable_cheque"]:
				return None
			credit_account = _strip_link_name_or_none(getattr(doc, "account_paid_to", None)) or _get_party_account_or_company_default(
				doc.party_type, doc.party, doc.company, "payable"
			)
			if not credit_account:
				return None
			remark = frappe._(PDC_JE_REMARK_REPLACE_ISSUED_PAYABLE_CHEQUE)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			party_credits = _payable_party_reverse_credit_lines(credit_account)
			je["accounts"] = [
				{
					"account": acc["payable_cheque"],
					"debit_in_account_currency": doc.cheque_amount,
				},
				*party_credits,
			]
			return _return_je(je)

		# Returned -> Replaced: same shape as Draft -> Registered (book new instrument to pool).
		# TODO(accounting): Confirm netting with prior return JE and replacement numbering.
		if from_state == WORKFLOW_RETURNED and to_state == WORKFLOW_REPLACED:
			if not acc["payable_cheque"]:
				return None
			debit_account = _strip_link_name_or_none(getattr(doc, "account_paid_to", None)) or _get_party_account_or_company_default(
				doc.party_type, doc.party, doc.company, "payable"
			)
			if not debit_account:
				return None
			remark = frappe._(PDC_JE_REMARK_REPLACE_RETURNED_PAYABLE_CHEQUE)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			party_debits = _payable_party_issue_debit_lines(debit_account)
			je["accounts"] = party_debits + [
				{
					"account": acc["payable_cheque"],
					"credit_in_account_currency": doc.cheque_amount,
				}
			]
			return _return_je(je)

		# Issued -> Cancelled: Dr notes payable pool, Cr party payable (same shape as return).
		if from_state == WORKFLOW_ISSUED and to_state == WORKFLOW_CANCELLED:
			if not acc["payable_cheque"]:
				return None
			credit_account = _strip_link_name_or_none(getattr(doc, "account_paid_to", None)) or _get_party_account_or_company_default(
				doc.party_type, doc.party, doc.company, "payable"
			)
			if not credit_account:
				return None
			remark = frappe._(PDC_JE_REMARK_CANCEL_ISSUED_PAYABLE_CHEQUE)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			party_credits = _payable_party_reverse_credit_lines(credit_account)
			je["accounts"] = [
				{
					"account": acc["payable_cheque"],
					"debit_in_account_currency": doc.cheque_amount,
				},
				*party_credits,
			]
			return _return_je(je)

		# Issued -> Cleared: Dr notes payable pool, Cr Bank GL — **no party** (journal-centric clear).
		if from_state == WORKFLOW_ISSUED and to_state == WORKFLOW_CLEARED:
			if not getattr(doc, "cheque_amount", None):
				return None
			if not acc["payable_cheque"]:
				return None
			bank_gl = _pdc_bank_gl_account(doc)
			if not bank_gl:
				return None
			_pdc_validate_clearing_bank_ledger_account(doc, bank_gl)
			debit_pool = acc["payable_cheque"]
			_pdc_validate_payable_clear_accounts_no_party_gl(debit_pool, bank_gl)
			remark = frappe._(PDC_JE_REMARK_CLEAR_PAYABLE_CHEQUE)
			if doc.cheque_no:
				remark = f"{remark} — {doc.cheque_no}"
			je = _base(remark)
			je["accounts"] = [
				{
					"account": debit_pool,
					"debit_in_account_currency": doc.cheque_amount,
				},
				{
					"account": bank_gl,
					"credit_in_account_currency": doc.cheque_amount,
				},
			]
			return _return_je(je)

	return None


# Alias: same payload shape (voucher_type, posting_date, remarks, accounts).
build_pdc_journal_entry_payload = build_pdc_journal_entry_data


def _pdc_bank_gl_account(doc) -> str | None:
	"""Company bank GL from PDC ``bank_account`` → **Bank Account** ``account``.

	The linked **Account** must be the real **Bank** ledger for this company (validated at clear via
	:func:`_pdc_validate_clearing_bank_ledger_account` when the account row exists in the database)
	so bank ledger and bank reconciliation stay aligned with the voucher.
	"""
	ba = _strip_link_name_or_none(getattr(doc, "bank_account", None))
	if not ba:
		return None
	return _strip_link_name_or_none(frappe.db.get_value("Bank Account", ba, "account"))


def _pdc_validate_clearing_bank_ledger_account(doc, bank_gl: str | None) -> None:
	"""Cleared cheques must post the bank leg to the company **Bank** GL from the PDC Bank Account.

	Receivable **→ Cleared** debits this account; Payable **Issued → Cleared** credits it.
	Requires **Account.account_type == Bank** and (when both are known) **Account.company** = PDC company.
	Company Bank Account linkage (``is_company_account``, Bank Account.company) is enforced separately
	in :meth:`PostDatedCheque._validate_bank_account_for_cleared_workflow_state`.

	When the **Account** doc is not in the local DB (e.g. isolated unit tests), validation is skipped —
	the same guard as :func:`_pdc_validate_receivable_clear_accounts_no_party_gl` for missing rows.
	"""
	if not bank_gl:
		return
	if not frappe.db.exists("Account", bank_gl):
		return
	doc_company = (getattr(doc, "company", None) or "").strip()
	acc_company = (frappe.get_cached_value("Account", bank_gl, "company") or "").strip()
	if doc_company and acc_company and acc_company != doc_company:
		frappe.throw(
			frappe._(
				"Cheque clearing bank ledger **{0}** belongs to company «{1}», but this Post Dated Cheque is for "
				"«{2}». Use a **Bank Account** for the same company so the Journal Entry hits the correct bank ledger."
			).format(bank_gl, acc_company, doc_company),
			title=frappe._("Wrong company for clearing bank account"),
		)
	at = frappe.get_cached_value("Account", bank_gl, "account_type")
	if at != "Bank":
		frappe.throw(
			frappe._(
				"Cheque clearing must use a **Bank** ledger account (the GL linked from **Bank Account** on this PDC); "
				"account **{0}** has type «{1}». Update the bank account or chart of accounts so reconciliation sees the correct bank book."
			).format(bank_gl, at or ""),
			title=frappe._("Invalid bank ledger for clearing"),
		)


def _pdc_validate_receivable_clear_accounts_no_party_gl(bank_gl: str | None, credit_account: str | None) -> None:
	"""Block clearing lines that use Receivable/Payable GL.

	ERPNext :meth:`Journal Entry.validate_party` requires **Party** on accounts whose type is
	Receivable or Payable. Posting clearing there would either fail or force a second party hit.
	Cheque clearing must use Bank + internal pool accounts (Cheques in Hand / Clearing / Protested)
	that are **not** Receivable/Payable in Chart of Accounts.
	"""
	for acc_name, leg in (
		(bank_gl, "bank (debit)"),
		(credit_account, "cheque pool (credit)"),
	):
		if not acc_name or not frappe.db.exists("Account", acc_name):
			continue
		at = frappe.get_cached_value("Account", acc_name, "account_type")
		if at in ("Receivable", "Payable"):
			frappe.throw(
				frappe._(
					"Cannot clear receivable cheque on account {0} (account type «{1}») for {2}. "
					"Use the company Bank GL on the PDC and configure Cheques in Hand, "
					"Cheques in Clearing, or Protested in PDC Settings so they are not "
					"Receivable or Payable accounts in the Chart of Accounts."
				).format(acc_name, at or "", leg),
				title=frappe._("Invalid account for PDC clearing"),
			)


def _pdc_validate_payable_clear_accounts_no_party_gl(pool_gl: str | None, bank_gl: str | None) -> None:
	"""Block Payable clear lines that use Receivable/Payable GL (same constraint as receivable clear).

	Party was already settled at **Issued**; **Cleared** must only move bank vs notes-payable **pool**.
	"""
	for acc_name, leg in (
		(pool_gl, "notes payable pool (debit)"),
		(bank_gl, "bank (credit)"),
	):
		if not acc_name or not frappe.db.exists("Account", acc_name):
			continue
		at = frappe.get_cached_value("Account", acc_name, "account_type")
		if at in ("Receivable", "Payable"):
			frappe.throw(
				frappe._(
					"Cannot clear payable cheque on account {0} (account type «{1}») for {2}. "
					"Use the company Bank GL on the PDC and a **Default Payable Cheque Account** in "
					"PDC Settings that is not typed Receivable/Payable in the Chart of Accounts."
				).format(acc_name, at or "", leg),
				title=frappe._("Invalid account for PDC clearing"),
			)


@frappe.whitelist()
def get_default_party_accounts(party_type, party, company, cheque_direction):
	"""Return default Account Paid From / Account Paid To for the given party and direction."""
	if not company or not cheque_direction:
		return {}
	out = {}
	if cheque_direction == "Receivable":
		# Account Paid To always tracks Cheques in Hand from PDC Settings (no party required).
		ch = _get_cheques_in_hand_account_for_company(company)
		if ch:
			out["account_paid_to"] = ch
	if party_type and party and company:
		if cheque_direction == "Receivable":
			out["account_paid_from"] = _get_party_account_or_company_default(
				party_type, party, company, "receivable"
			)
		elif cheque_direction == "Payable":
			out["account_paid_to"] = _get_party_account_or_company_default(
				party_type, party, company, "payable"
			)
	return out


class PostDatedCheque(Document):
	"""Submittable PDC: receivable or payable post-dated cheque with workflow-driven GL posting.

	Journal-centric lifecycle (design): party settlement timing — **Receivable** at **Registered**,
	**Payable** at **Issued**; **Cleared** = JE bank movement only; allocation to invoices/advances is
	separate from workflow transitions. See module docstring for full rules.
	"""

	def before_insert(self):
		"""Set defaults for new PDC."""
		if not self.workflow_state:
			self.workflow_state = "Draft"
		self._set_default_party_type_for_payable_if_missing()
		# Initial holder = party (Received From / Paid To)
		if not self.holder_party and self.party:
			self.holder_party_type = self.party_type
			self.holder_party = self.party
		self._autofill_accounts_from_pdc_settings_if_missing()

	def before_validate(self):
		"""Runs before ``validate`` on **save** and **submit** (not on ``update_after_submit`` — see ``before_update_after_submit``)."""
		self._set_default_bank_account_for_receivable()
		self._set_default_party_type_for_payable_if_missing()
		if self.is_new():
			self._autofill_accounts_from_pdc_settings_if_missing()

	def before_save(self):
		"""Persist ``cheque_status`` derived from ``workflow_state`` (see ``_sync_cheque_status_from_workflow_state``)."""
		self._sync_cheque_status_from_workflow_state()

	def before_submit(self):
		"""Frappe does not run ``before_save`` on submit — only ``validate`` then ``before_submit``.

		Re-sync so ``cheque_status`` matches ``workflow_state`` immediately before the document is
		submitted (``validate`` already syncs; this is an explicit last pass).
		"""
		self._sync_cheque_status_from_workflow_state()

	def before_update_after_submit(self):
		"""Run the same validations as draft saves when the document is already submitted.

		ERPNext workflow actions call :func:`~frappe.model.workflow.apply_workflow`, which ends in
		``doc.save()`` with ``_action == "update_after_submit"``. For that path Frappe runs
		``before_update_after_submit`` / ``on_update_after_submit`` only — not ``before_save`` or
		``on_update``. Without this hook, ``workflow_state`` can change while ``cheque_status``,
		transition checks, **holder history on endorsement**, and accounting never run.
		"""
		self._set_default_bank_account_for_receivable()
		self.validate()

	def on_update(self):
		"""Keep ``replaces_cheque`` / ``replaced_by`` in sync with the counterparty PDC.

		Runs after insert and after save (Frappe ``run_post_save_methods`` → ``on_update``).
		"""
		self._sync_replacement_bidirectional_links()
		self._pdc_post_save_accounting_sequence()

	def on_update_after_submit(self):
		"""Submitted saves skip :meth:`on_update`; keep replacement mirroring and accounting in sync."""
		self._sync_replacement_bidirectional_links()
		self._pdc_post_save_accounting_sequence()

	def validate(self):
		"""Validate PDC data and enforce immutability after submit."""
		self._reset_party_if_party_type_changed()
		self._set_default_party_accounts()
		self._validate_fields_not_editable_after_related_accounting()
		self._validate_receivable_cheques_in_hand_account_required()
		self._validate_allocations()
		self._validate_party()
		self._validate_duplicate_cheque_no()
		self._validate_drawer_bank()
		self._validate_replaces_cheque()
		self._validate_replacement_bidirectional_conflicts()
		self._validate_replacement_no_cycle()
		self._pdc_pre_save_workflow_sequence()
		self._validate_allocation_status_awareness()
		self._validate_replacement_links_when_replaced()
		self._validate_returned_workflow_state()
		self._validate_handover_date_vs_received_date()
		self._validate_receivable_sent_to_bank_vs_received_date()
		self._validate_receivable_cleared_and_bounced_vs_sent_to_bank()
		self._validate_returned_date_vs_received_date()
		self._validate_payable_cleared_vs_handover_date()
		self._validate_party_immutable_after_submit()
		self._validate_sayad_registration_per_settings()

	def _validate_handover_date_vs_received_date(self) -> None:
		"""``handover_date`` must be on or after ``received_date`` when both are set (Payable + Receivable)."""
		received = getattr(self, "received_date", None)
		handover = getattr(self, "handover_date", None)
		if not received or not handover:
			return
		if getdate(handover) < getdate(received):
			frappe.throw(
				frappe._(
					"Handover / Endorsement Date cannot be earlier than Received / Issued Date.\n"
					"A cheque cannot be handed over before it is issued or recorded."
				),
				title=frappe._("Invalid Date Sequence"),
			)

	def _validate_receivable_sent_to_bank_vs_received_date(self) -> None:
		"""Receivable: ``sent_to_bank_date`` must be on or after ``received_date`` when both are set."""
		if self.cheque_direction != CHEQUE_DIRECTION_RECEIVABLE:
			return
		sent = getattr(self, "sent_to_bank_date", None)
		received = getattr(self, "received_date", None)
		if not sent or not received:
			return
		if getdate(sent) < getdate(received):
			frappe.throw(
				frappe._(
					"Sent to Bank Date cannot be earlier than Received / Issued Date.\n"
					"A receivable cheque cannot be sent for collection before it was received or recorded."
				),
				title=frappe._("Invalid Date Sequence"),
			)

	def _validate_receivable_cleared_and_bounced_vs_sent_to_bank(self) -> None:
		"""Receivable: clearing or bank bounce cannot precede bank submission when both sides are set."""
		if self.cheque_direction != CHEQUE_DIRECTION_RECEIVABLE:
			return
		sent = getattr(self, "sent_to_bank_date", None)
		if not sent:
			return
		cleared = getattr(self, "cleared_date", None)
		if cleared and getdate(cleared) < getdate(sent):
			frappe.throw(
				frappe._(
					"Cleared Date cannot be earlier than Sent to Bank Date.\n"
					"Bank settlement cannot occur before the cheque was sent to the bank."
				),
				title=frappe._("Invalid Date Sequence"),
			)
		bounced = getattr(self, "bounced_date", None)
		if bounced and getdate(bounced) < getdate(sent):
			frappe.throw(
				frappe._(
					"Bounced Date cannot be earlier than Sent to Bank Date.\n"
					"A bank rejection cannot be recorded before the cheque was sent to the bank."
				),
				title=frappe._("Invalid Date Sequence"),
			)

	def _validate_returned_date_vs_received_date(self) -> None:
		"""``returned_date`` must be on or after ``received_date`` when both are set (Payable + Receivable)."""
		ret = getattr(self, "returned_date", None)
		received = getattr(self, "received_date", None)
		if not ret or not received:
			return
		if getdate(ret) < getdate(received):
			frappe.throw(
				frappe._(
					"Returned Date cannot be earlier than Received / Issued Date.\n"
					"A business return cannot be recorded before the cheque was received or issued."
				),
				title=frappe._("Invalid Date Sequence"),
			)

	def _validate_payable_cleared_vs_handover_date(self) -> None:
		"""Payable: ``cleared_date`` must be on or after ``handover_date`` when both are set."""
		if self.cheque_direction != CHEQUE_DIRECTION_PAYABLE:
			return
		cleared = getattr(self, "cleared_date", None)
		handover = getattr(self, "handover_date", None)
		if not cleared or not handover:
			return
		if getdate(cleared) < getdate(handover):
			frappe.throw(
				frappe._(
					"Cleared Date cannot be earlier than Handover / Endorsement Date.\n"
					"Bank withdrawal or settlement cannot occur before the cheque was physically handed over."
				),
				title=frappe._("Invalid Date Sequence"),
			)

	def _set_default_party_type_for_payable_if_missing(self) -> None:
		"""Payable cheques default to Supplier (user can change afterwards)."""
		if (self.cheque_direction or "").strip() != CHEQUE_DIRECTION_PAYABLE:
			return
		if not (self.party_type or "").strip():
			self.party_type = "Supplier"

	def _autofill_accounts_from_pdc_settings_if_missing(self) -> None:
		"""Auto-fill document accounts from **PDC Settings** (backend) without overwriting user values.

		- Receivable ``account_paid_to`` defaults from ``PDC Settings.default_cheques_in_hand_account``.
		- ``cheques_in_clearing_account`` defaults from ``PDC Settings.default_cheques_in_clearing_account``.
		"""
		company = (getattr(self, "company", None) or "").strip()
		if not company:
			return
		settings = _get_pdc_settings_for_company(company)
		if not settings:
			return
		if self.cheque_direction == CHEQUE_DIRECTION_RECEIVABLE and not _strip_link_name_or_none(
			getattr(self, "account_paid_to", None)
		):
			ch = _strip_link_name_or_none(settings.get("default_cheques_in_hand_account"))
			if ch:
				self.account_paid_to = ch
		if not _strip_link_name_or_none(getattr(self, "cheques_in_clearing_account", None)):
			clr = _strip_link_name_or_none(settings.get("default_cheques_in_clearing_account"))
			if clr:
				self.cheques_in_clearing_account = clr
		# Payable: allow storing pool/default payable cheque account on account_paid_from if user didn't set it.
		if self.cheque_direction == CHEQUE_DIRECTION_PAYABLE and not _strip_link_name_or_none(
			getattr(self, "account_paid_from", None)
		):
			pool = _strip_link_name_or_none(settings.get("default_payable_cheque_account"))
			if pool:
				self.account_paid_from = pool

	def _validate_fields_not_editable_after_related_accounting(self) -> None:
		"""Lock sensitive account fields once related accounting has been posted.

		Rules (per-field):
		- ``account_paid_from`` / ``account_paid_to``: locked after any posted JE exists on this PDC.
		- ``cheques_in_clearing_account``: locked after any clearing-related JE exists (Under Collection / Collected / Returned).
		- ``endorsement_settlement_account``: locked after Endorsement JE exists.
		"""
		before = self.get_doc_before_save()
		if not before:
			return
		if not self.name:
			return

		def _has_purpose(purposes: tuple[str, ...]) -> bool:
			for ref in (self.journal_references or []):
				if (ref.purpose or "").strip() in purposes:
					return True
			count = frappe.db.count(
				"PDC Journal Reference",
				{
					"parent": self.name,
					"parenttype": "Post Dated Cheque",
					"purpose": ["in", list(purposes)],
				},
			)
			return bool(count and count > 0)

		has_any_je = _has_purpose(
			(
				"Receive",
				"Under Collection",
				"Collected",
				"Returned",
				"Payable Issue",
				"Payable Clear",
				"Endorsement",
				"Cancel",
			)
		)
		has_clearing_related = _has_purpose(("Under Collection", "Collected", "Returned"))
		has_endorsement = _has_purpose(("Endorsement",))

		def _changed(fieldname: str) -> bool:
			return (getattr(before, fieldname, None) or "") != (getattr(self, fieldname, None) or "")

		locked_fields: list[str] = []
		if has_any_je:
			for fn in ("account_paid_from", "account_paid_to"):
				if _changed(fn):
					locked_fields.append(fn)
		if has_clearing_related and _changed("cheques_in_clearing_account"):
			locked_fields.append("cheques_in_clearing_account")
		if has_endorsement and _changed("endorsement_settlement_account"):
			locked_fields.append("endorsement_settlement_account")
		if locked_fields:
			frappe.throw(
				frappe._(
					"These fields cannot be changed after related accounting entries exist: {0}"
				).format(", ".join(locked_fields)),
				title=frappe._("Accounting already posted"),
			)

	def _validate_receivable_cheques_in_hand_account_required(self) -> None:
		"""Receivable PDC must always have Cheques in Hand account resolved onto the document."""
		if self.cheque_direction != CHEQUE_DIRECTION_RECEIVABLE:
			return
		if _strip_link_name_or_none(getattr(self, "account_paid_to", None)):
			return
		frappe.throw(
			frappe._(
				"Cheques in Hand Account is required for Receivable cheques. Set Account Paid To or configure Default Cheques in Hand Account in PDC Settings."
			),
			title=frappe._("Cheques in Hand account required"),
		)

	def _validate_allocation_status_awareness(self) -> None:
		"""See :func:`~erpnext_extensions.cheque_management.pdc_allocation.validate_pdc_allocation_workflow_milestone`."""
		validate_pdc_allocation_workflow_milestone(self)

	def _validate_allocations(self) -> None:
		"""Autofill from parent SI/PI link, drop empty rows, sync summary totals, then row rules."""
		autofill_pdc_allocations_from_parent_reference(self)
		sanitize_pdc_allocation_child_rows(self)
		sync_pdc_allocation_summary_amounts(self)
		validate_pdc_allocation_rows(self)

	def get_allocation_effective_from_workflow_state(self) -> str | None:
		"""First workflow state at which allocations are effective; see ``pdc_allocation`` module."""
		return pdc_allocation_effective_milestone_workflow_state(self.cheque_direction)

	def is_allocation_effective(self) -> bool:
		"""See :func:`~erpnext_extensions.cheque_management.pdc_allocation.is_pdc_allocation_effective`."""
		return _is_pdc_allocation_effective(self.cheque_direction, self.workflow_state)

	def is_allocation_draft_only(self) -> bool:
		"""See :func:`~erpnext_extensions.cheque_management.pdc_allocation.is_pdc_allocation_draft_only`."""
		return _is_pdc_allocation_draft_only(self.cheque_direction, self.workflow_state)

	def _sync_allocation_summary_amounts(self) -> None:
		"""See :func:`~erpnext_extensions.cheque_management.pdc_allocation.sync_pdc_allocation_summary_amounts`."""
		sync_pdc_allocation_summary_amounts(self)

	def _pdc_pre_save_workflow_sequence(self) -> None:
		"""Run **before** ``db_update`` on every successful validation (draft, submit, update_after_submit).

		Order (must stay stable for accounting and status):

		1. **Detect** prior ``workflow_state`` (Frappe snapshot — :meth:`_capture_previous_workflow_for_accounting`).
		2. **Validate** transition and workflow-shaped rules (state machine, bounce, endorsement, …).
		3. **Update** ``cheque_status`` from ``workflow_state`` and assert consistency.
		4. If moving to **Cleared** with **journal_entry** policy, require a buildable payload
		   (:meth:`_validate_clearing_accounting_payload`) so ``db_update`` cannot leave Cleared without a postable JE.

		Does **not** insert vouchers; that runs in :meth:`_pdc_post_save_accounting_sequence`.
		"""
		self._capture_previous_workflow_for_accounting()
		self._validate_workflow_transition()
		self._validate_received_date_required_for_receivable_registered()
		self._validate_received_date_required_for_payable_registered()
		self._validate_received_date_required_for_payable_issued()
		self._validate_endorsement_allowed_per_settings()
		self._validate_bounced_workflow_state()
		self._validate_endorsed_workflow_state()
		# Endorsement audit + normalized holder (after transition and holder rules pass; runs on update_after_submit too).
		self._sync_holder_fields_for_endorsement()
		self._append_holder_history_on_endorsement()
		self._validate_issued_workflow_state()
		self._validate_sent_to_bank_workflow_state()
		self._validate_bank_account_for_workflow_state()
		self._validate_bank_account_for_cleared_workflow_state()
		self._validate_bank_gl_account_for_cleared_workflow_state()
		self._validate_receivable_bank_account_is_company_account()
		self._validate_payable_bank_account_is_company_account()
		self._sync_cheque_status_from_workflow_state()
		self._validate_cheque_status_matches_workflow_state()
		self._validate_clearing_accounting_payload()

	def _reset_party_if_party_type_changed(self):
		"""If party_type changes, party must be re-selected."""
		before = self.get_doc_before_save()
		if not before:
			return
		if before.party_type != self.party_type:
			self.party = None

	def _validate_drawer_bank(self):
		"""Drawer bank is required for receivable cheques."""
		if self.cheque_direction == "Receivable" and not self.drawer_bank_name:
			frappe.throw(frappe._("Drawer Bank Name is required for Receivable cheques."))

	def _get_previous_workflow_state_raw(self):
		"""``workflow_state`` before this save: Frappe snapshot first, else DB for edge cases (e.g. import)."""
		before = self.get_doc_before_save()
		if before is not None:
			return before.get("workflow_state")
		if self.name and frappe.db.exists("Post Dated Cheque", self.name):
			return frappe.db.get_value("Post Dated Cheque", self.name, "workflow_state")
		return None

	def _get_previous_workflow_state_for_accounting(self) -> str | None:
		"""Prior ``workflow_state`` for transition / accounting (must match Frappe save cycle).

		Uses :meth:`~frappe.model.document.Document.get_value_before_save` → the document snapshot
		loaded in ``check_if_latest`` / ``load_doc_before_save``. That snapshot stays on the doc through
		``on_update`` / ``on_update_after_submit`` **before** any nested reload.

		Never uses the database here: after ``db_update``, the row can already hold the **new**
		workflow state, so ``get_value`` would mis-report the previous step and break accounting
		(e.g. Registered→Sent to Bank misread as Draft→Sent to Bank).

		On brand-new insert there is no snapshot → ``None`` (normalized to **Draft** in policy helpers).
		"""
		return self.get_value_before_save("workflow_state")

	def _capture_previous_workflow_for_accounting(self):
		"""Step 1 (pre-save): store snapshot from :meth:`_get_previous_workflow_state_for_accounting` for logs/cache."""
		self._pdc_previous_workflow_for_accounting = self._get_previous_workflow_state_for_accounting()
		_pdc_accounting_logger.debug(
			"Captured previous_workflow_state for accounting: %r (doc %s)",
			self._pdc_previous_workflow_for_accounting,
			self.name or "(new)",
		)

	def _pdc_post_save_accounting_sequence(self) -> None:
		"""After successful ``db_update`` when ``workflow_state`` changed (``on_update`` / ``on_update_after_submit``).

		PDC lifecycle is **Journal Entry only** — vouchers are recorded in ``journal_references``.

		Preconditions: steps 1–3 already ran in :meth:`validate` via :meth:`_pdc_pre_save_workflow_sequence`.

		4. Re-read prior ``workflow_state`` from the same Frappe snapshot used before save.
		5. If policy is ``journal_entry``, create **at most one** JE per transition
		   (``cheque_name|cheque_direction|from_state|to_state`` on ``journal_references``; legacy suffix
		   ``direction|from|to`` still recognized — skip if voucher already linked;
		   see ``pdc_accounting_idempotency``).

		Skips when ``flags.skip_pdc_accounting_orchestration`` is set (nested saves from posting services).
		"""
		if getattr(self.flags, "skip_pdc_accounting_orchestration", False):
			return
		if not self.name:
			return
		prev_raw = self._get_previous_workflow_state_for_accounting()
		prev_norm = normalize_workflow_state_value(prev_raw)
		curr_norm = normalize_workflow_state_value(self.workflow_state)
		if prev_norm != curr_norm:
			frappe.logger("erpnext_extensions.cheque_management").info(
				"PDC workflow transition | name=%s | cheque_direction=%s | previous_workflow_state=%r | workflow_state=%r",
				self.name,
				getattr(self, "cheque_direction", None),
				prev_raw,
				self.workflow_state,
			)
		if prev_norm == curr_norm:
			return
		_pdc_accounting_logger.debug("Detected transition: %s → %s", prev_norm, curr_norm)
		action = get_accounting_action(self, prev_raw)
		_pdc_accounting_logger.info(
			"[PDC_ACCOUNTING_TRACE] post_save | pdc=%s | previous_workflow_state=%r | workflow_state=%r | "
			"cheque_direction=%s | accounting_action=%s",
			self.name,
			prev_raw,
			self.workflow_state,
			getattr(self, "cheque_direction", None),
			"none" if action == PDC_ACCOUNTING_NO_DOCUMENT else action,
		)
		_pdc_accounting_logger.debug(
			"Accounting action: %s",
			"none" if action == PDC_ACCOUNTING_NO_DOCUMENT else action,
		)
		if action == PDC_ACCOUNTING_NO_DOCUMENT:
			return

		# Posting dates must follow business event dates (not today/workflow timestamp).
		# - Receivable Draft→Registered: use received_date
		# - Any → Cleared: use cleared_date
		# - Any → Returned: use returned_date only
		# - Any → Bounced: use bounced_date only (bank rejection after Sent to Bank)
		# - Receivable → Sent to Bank: use sent_to_bank_date only (bank handover for collection)
		# - Payable Draft→Registered: use received_date (register / settlement event)
		# - Receivable → Endorsed: use handover_date only (endorsement / transfer)
		# Fallback only for other transitions that are not business-dated yet.
		posting_date = None
		if curr_norm == WORKFLOW_CLEARED:
			posting_date = getattr(self, "cleared_date", None)
		elif curr_norm == WORKFLOW_RETURNED:
			posting_date = getattr(self, "returned_date", None)
		elif curr_norm == WORKFLOW_BOUNCED:
			posting_date = getattr(self, "bounced_date", None)
		elif (
			curr_norm == WORKFLOW_SENT_TO_BANK
			and (self.cheque_direction or "").strip() == CHEQUE_DIRECTION_RECEIVABLE
		):
			posting_date = getattr(self, "sent_to_bank_date", None)
		elif (
			curr_norm == WORKFLOW_ENDORSED
			and (self.cheque_direction or "").strip() == CHEQUE_DIRECTION_RECEIVABLE
		):
			posting_date = getattr(self, "handover_date", None)
		elif (
			curr_norm == WORKFLOW_REGISTERED
			and (self.cheque_direction or "").strip() == CHEQUE_DIRECTION_RECEIVABLE
		):
			posting_date = getattr(self, "received_date", None)
		elif (
			curr_norm == WORKFLOW_REGISTERED
			and (self.cheque_direction or "").strip() == CHEQUE_DIRECTION_PAYABLE
			and prev_norm == WORKFLOW_DRAFT
		):
			posting_date = getattr(self, "received_date", None)
		elif (
			curr_norm == WORKFLOW_ISSUED
			and (self.cheque_direction or "").strip() == CHEQUE_DIRECTION_PAYABLE
		):
			# Operational Issued transition does not post a JE; handover is still mandatory for validation.
			posting_date = getattr(self, "handover_date", None)
		if curr_norm == WORKFLOW_RETURNED:
			if not posting_date:
				frappe.throw(
					frappe._(
						"Returned Date is mandatory when Workflow State is Returned. "
						"Returned is a business return, not a bank bounce — use Workflow State Bounced for bank rejection."
					),
					title=frappe._("Missing Returned Date"),
				)
		elif curr_norm == WORKFLOW_BOUNCED:
			if not posting_date:
				frappe.throw(
					frappe._(
						"Bounced Date is mandatory when Workflow State is Bounced. "
						"Enter the date of bank rejection (dishonour after Sent to Bank). "
						"This is not a business return — use Returned for return to party before completion."
					),
					title=frappe._("Missing Bounced Date"),
				)
		elif (
			curr_norm == WORKFLOW_SENT_TO_BANK
			and (self.cheque_direction or "").strip() == CHEQUE_DIRECTION_RECEIVABLE
		):
			if not posting_date:
				frappe.throw(
					frappe._(
						"Sent to Bank Date is mandatory when Workflow State is Sent to Bank (Receivable). "
						"Enter the date the cheque was delivered to the bank for collection — do not use workflow time or today."
					),
					title=frappe._("Missing Sent to Bank Date"),
				)
		elif (
			curr_norm == WORKFLOW_ISSUED
			and (self.cheque_direction or "").strip() == CHEQUE_DIRECTION_PAYABLE
		):
			if not posting_date:
				frappe.throw(
					frappe._(
						"Handover / Endorsement Date is mandatory when Workflow State is Issued (Payable). "
						"Enter the date the cheque was physically handed over to the payee — not Received / Issued Date or today."
					),
					title=frappe._("Missing Handover Date"),
				)
		elif (
			curr_norm == WORKFLOW_ENDORSED
			and (self.cheque_direction or "").strip() == CHEQUE_DIRECTION_RECEIVABLE
		):
			if not posting_date:
				frappe.throw(
					frappe._(
						"Handover / Endorsement Date is mandatory when Workflow State is Endorsed. "
						"Enter the date of endorsement or transfer — not Received / Issued Date."
					),
					title=frappe._("Missing Handover Date"),
				)
		else:
			# Fallback for transitions that don't have a dedicated business date yet.
			# Prefer user-provided/meaningful dates on the doc; only then fall back to today.
			# Do not use handover_date, returned_date, bounced_date, or sent_to_bank_date here —
			# only their workflows use them.
			posting_date = (
				posting_date
				or getattr(self, "cheque_due_date", None)
				or getattr(self, "received_date", None)
				or getattr(self, "cleared_date", None)
				or getdate()
			)
		ch_dir = (self.cheque_direction or "").strip()

		from erpnext_extensions.cheque_management.pdc_journal_entry_service import (
			get_existing_journal_entry_for_transition,
			post_pdc_transition_journal_entry,
		)

		created = False
		if action == PDC_ACCOUNTING_JOURNAL_ENTRY:
			existing_je = get_existing_journal_entry_for_transition(
				self.name, ch_dir, prev_raw, self.workflow_state
			)
			if existing_je:
				_pdc_accounting_logger.debug(
					"PDC accounting: Journal Entry already exists for %s → %s (%s), skip duplicate",
					prev_norm,
					curr_norm,
					existing_je,
				)
			else:
				_pdc_accounting_logger.debug(
					"Calling post_pdc_transition_journal_entry for %s → %s",
					prev_norm,
					curr_norm,
				)
				created = bool(
					post_pdc_transition_journal_entry(
						self, prev_raw, self.workflow_state, posting_date=posting_date
					)
				)
				if not created:
					_pdc_accounting_logger.debug(
						"post_pdc_transition_journal_entry returned no JE (missing payload/accounts or build skipped)"
					)

		if created:
			self.reload()

	def _validate_sayad_registration_per_settings(self) -> None:
		"""Enforce Sayad policy per-company (PDC Settings).

		Rules:
		- If PDC Settings.require_sayad_registration = 1: ``sayad_code`` is required.
		- If enabled: ``sayad_registered`` is required only at lifecycle checkpoints:
		  - Receivable: before becoming **Registered**
		  - Payable: before becoming **Registered**
		"""
		if not _pdc_company_policy_flags(getattr(self, "company", None))["require_sayad_registration"]:
			return

		code = (getattr(self, "sayad_code", None) or "").strip()
		if not code:
			frappe.throw(
				frappe._(
					"Sayad Code is required because Require Sayad Registration is enabled in PDC Settings."
				),
				title=frappe._("Sayad registration required"),
			)

		prev = normalize_workflow_state_value(self._get_previous_workflow_state_raw())
		curr = normalize_workflow_state_value(getattr(self, "workflow_state", None))
		if prev == curr:
			return

		if self.cheque_direction == CHEQUE_DIRECTION_RECEIVABLE and curr == WORKFLOW_REGISTERED:
			if not cint(getattr(self, "sayad_registered", 0)):
				frappe.throw(
					frappe._(
						"Sayad Registered must be checked before registering a receivable cheque because Require Sayad Registration is enabled in PDC Settings."
					),
					title=frappe._("Sayad registration required"),
				)

		if self.cheque_direction == CHEQUE_DIRECTION_PAYABLE and curr == WORKFLOW_REGISTERED:
			if not cint(getattr(self, "sayad_registered", 0)):
				frappe.throw(
					frappe._(
						"Sayad Registered must be checked before registering a payable cheque because Require Sayad Registration is enabled in PDC Settings."
					),
					title=frappe._("Sayad registration required"),
				)

	def _validate_endorsement_allowed_per_settings(self) -> None:
		"""Block **Registered → Endorsed** when **Allow Endorsement** is disabled in PDC Settings."""
		if not self._transitioning_to_endorsed():
			return
		if _pdc_company_policy_flags(getattr(self, "company", None))["allow_endorsement"]:
			return
		frappe.throw(
			frappe._(
				"Transition to Endorsed is not allowed: Allow Endorsement is disabled in PDC Settings for this company."
			),
			title=frappe._("Endorsement not allowed"),
		)

	def _validate_workflow_transition(self):
		"""Enforce allowed ``workflow_state`` transitions via ``pdc_workflow_state_machine``.

		Uses DocType field ``cheque_direction`` as cheque type (**Receivable** / **Payable**).
		Terminal states (**Cleared** / **Cancelled** / **Replaced**) are locked even if
		direction is not set yet (see :func:`get_pdc_workflow_transition_validation_error`).
		Bounced / Endorsed / Issued / Sent to Bank rules are also enforced in
		:meth:`_validate_bounced_workflow_state`, :meth:`_validate_endorsed_workflow_state`,
		:meth:`_validate_issued_workflow_state`, and :meth:`_validate_sent_to_bank_workflow_state`.
		Accounting documents are created in :meth:`_pdc_post_save_accounting_sequence` (``on_update``), not here.
		"""
		prev_raw = self._get_previous_workflow_state_raw()
		cheque_type = (
			self.cheque_direction
			if self.cheque_direction in ("Receivable", "Payable")
			else ""
		)
		err = get_pdc_workflow_transition_validation_error(
			cheque_type,
			prev_raw,
			self.workflow_state,
		)
		if err:
			frappe.throw(frappe._(err), title=frappe._("Invalid Workflow State"))

	def _validate_received_date_required_for_receivable_registered(self) -> None:
		"""Receivable cheques must have ``received_date`` before becoming **Registered**."""
		if (self.cheque_direction or "").strip() != CHEQUE_DIRECTION_RECEIVABLE:
			return
		curr = normalize_workflow_state_value(self.workflow_state)
		if curr != WORKFLOW_REGISTERED:
			return
		prev = normalize_workflow_state_value(self._get_previous_workflow_state_raw())
		if prev == curr:
			return
		if not getattr(self, "received_date", None):
			frappe.throw(
				frappe._("Received Date is mandatory before registering a receivable cheque."),
				title=frappe._("Missing Received Date"),
			)

	def _validate_received_date_required_for_payable_registered(self) -> None:
		"""Payable cheques must have ``received_date`` before **Registered** (Draft → Registered settlement)."""
		if (self.cheque_direction or "").strip() != CHEQUE_DIRECTION_PAYABLE:
			return
		curr = normalize_workflow_state_value(self.workflow_state)
		if curr != WORKFLOW_REGISTERED:
			return
		prev = normalize_workflow_state_value(self._get_previous_workflow_state_raw())
		if prev == curr:
			return
		if prev != WORKFLOW_DRAFT:
			return
		if not getattr(self, "received_date", None):
			frappe.throw(
				frappe._(
					"Received / Issued Date is mandatory before registering a payable cheque (Draft → Registered): "
					"it is the posting date for supplier / Purchase Invoice settlement."
				),
				title=frappe._("Missing Received / Issued Date"),
			)

	def _validate_received_date_required_for_payable_issued(self) -> None:
		"""Payable cheques must have ``received_date`` (preparation / internal issue date) before **Issued**.

		Distinct from ``handover_date`` (physical delivery to payee), validated in
		:meth:`_validate_issued_workflow_state`.
		"""
		if (self.cheque_direction or "").strip() != CHEQUE_DIRECTION_PAYABLE:
			return
		curr = normalize_workflow_state_value(self.workflow_state)
		if curr != WORKFLOW_ISSUED:
			return
		prev = normalize_workflow_state_value(self._get_previous_workflow_state_raw())
		if prev == curr:
			return
		if not getattr(self, "received_date", None):
			frappe.throw(
				frappe._(
					"Received / Issued Date is mandatory before Issued (Payable): record when the cheque was prepared or internally issued. "
					"Physical handover to the payee is Handover / Endorsement Date — set that field separately."
				),
				title=frappe._("Missing Received / Issued Date"),
			)

	def _validate_bounced_workflow_state(self):
		"""**Bounced** = bank rejection after **Sent to Bank** (not **Returned**, which is a business return).

		Requires ``bounced_date``. Transition rules match :data:`PDC_VALIDATION_BOUNCED_REQUIRES_RECEIVABLE_SENT_TO_BANK`
		from :func:`get_pdc_workflow_transition_validation_error` (validated first in
		:meth:`_validate_workflow_transition`).
		"""
		if normalize_workflow_state_value(self.workflow_state) != WORKFLOW_BOUNCED:
			return
		if self.cheque_direction != CHEQUE_DIRECTION_RECEIVABLE:
			frappe.throw(
				frappe._(PDC_VALIDATION_BOUNCED_REQUIRES_RECEIVABLE_SENT_TO_BANK),
				title=frappe._("Invalid Bounced workflow state"),
			)
		prev_raw = self._get_previous_workflow_state_raw()
		if not is_workflow_previous_empty(prev_raw):
			prev = normalize_workflow_state_value(prev_raw)
			if prev != WORKFLOW_SENT_TO_BANK and prev != WORKFLOW_BOUNCED:
				frappe.throw(
					frappe._(PDC_VALIDATION_BOUNCED_REQUIRES_RECEIVABLE_SENT_TO_BANK),
					title=frappe._("Invalid Bounced workflow state"),
				)
		if not getattr(self, "bounced_date", None):
			frappe.throw(
				frappe._(
					"Bounced Date is mandatory when Workflow State is Bounced. "
					"Enter the bank rejection date — dishonour after Sent to Bank. "
					"This is not a business return (use Returned and Returned Date for that)."
				),
				title=frappe._("Missing Bounced Date"),
			)

	def _transitioning_to_endorsed(self) -> bool:
		"""True when this save moves a Receivable PDC into ``workflow_state`` **Endorsed**."""
		if self.cheque_direction != CHEQUE_DIRECTION_RECEIVABLE:
			return False
		if normalize_workflow_state_value(self.workflow_state) != WORKFLOW_ENDORSED:
			return False
		prev = normalize_workflow_state_value(self._get_previous_workflow_state_raw())
		return prev != WORKFLOW_ENDORSED

	def _validate_endorsed_workflow_state(self):
		"""**Endorsed** is only valid for Receivable cheques (not Payable).

		Message: :data:`PDC_VALIDATION_ENDORSED_RECEIVABLE_ONLY` — same rule as
		:func:`get_pdc_workflow_transition_validation_error` (see :meth:`_validate_workflow_transition`).
		For **Receivable** with **Endorsed**, ``holder_party_type`` and ``holder_party`` must both be set
		and must reference an existing document (canonical current holder after endorsement).
		"""
		if normalize_workflow_state_value(self.workflow_state) != WORKFLOW_ENDORSED:
			return
		if self.cheque_direction == CHEQUE_DIRECTION_PAYABLE:
			frappe.throw(
				frappe._(PDC_VALIDATION_ENDORSED_RECEIVABLE_ONLY),
				title=frappe._("Invalid Endorsed workflow state"),
			)
		if self.cheque_direction != CHEQUE_DIRECTION_RECEIVABLE:
			return
		ht = _strip_link_name_or_none(self.holder_party_type)
		hp = _strip_link_name_or_none(self.holder_party)
		if not ht or not hp:
			frappe.throw(
				frappe._(
					"Holder Party Type and Holder Party are required when Workflow State is Endorsed."
				),
				title=frappe._("Invalid Endorsed workflow state"),
			)
		if not frappe.db.exists(ht, hp):
			frappe.throw(
				frappe._("Invalid Holder Party: {0} {1} was not found.").format(ht, hp),
				title=frappe._("Invalid Endorsed workflow state"),
			)
		if not getattr(self, "handover_date", None):
			frappe.throw(
				frappe._(
					"Handover / Endorsement Date is mandatory when Workflow State is Endorsed. "
					"Enter the date the cheque was endorsed or transferred to the new party."
				),
				title=frappe._("Missing Handover Date"),
			)

	def _sync_holder_fields_for_endorsement(self):
		"""Keep ``holder_party_type`` / ``holder_party`` normalized while **Endorsed** (Receivable).

		Runs in ``before_save`` after validation so stripped values persist and Holder History matches.
		"""
		if self.cheque_direction != CHEQUE_DIRECTION_RECEIVABLE:
			return
		if normalize_workflow_state_value(self.workflow_state) != WORKFLOW_ENDORSED:
			return
		ht = _strip_link_name_or_none(self.holder_party_type)
		hp = _strip_link_name_or_none(self.holder_party)
		if not ht or not hp:
			return
		self.holder_party_type = ht
		self.holder_party = hp

	def _append_holder_history_on_endorsement(self):
		"""Append a **PDC Holder History** row when a Receivable PDC transitions into **Endorsed**.

		Runs from :meth:`_pdc_pre_save_workflow_sequence` (draft save and ``update_after_submit``), **after**
		transition validation, so history is not written for invalid moves.

		**Previous** holder is taken from the pre-save document (``holder_party*`` with fallback to ``party*``).
		**New** holder uses canonical ``holder_party*`` after :meth:`_sync_holder_fields_for_endorsement`.
		"""
		if not self._transitioning_to_endorsed():
			return
		new_ht = _strip_link_name_or_none(self.holder_party_type)
		new_hn = _strip_link_name_or_none(self.holder_party)
		if not new_ht or not new_hn:
			return
		before = self.get_doc_before_save()
		prev_ht, prev_hn = _resolve_holder_party_type_and_party(before)
		if prev_ht and not prev_hn:
			prev_ht = None
		self.append(
			"holder_history",
			{
				"date": now_datetime(),
				"previous_holder_type": prev_ht,
				"previous_holder": prev_hn if prev_ht else None,
				"new_holder_type": new_ht,
				"new_holder": new_hn,
				"reason": frappe._(PDC_HOLDER_HISTORY_REASON_ENDORSEMENT),
			},
		)

	def _validate_issued_workflow_state(self):
		"""**Issued** is only valid for Payable cheques (not Receivable).

		Requires ``handover_date`` (physical delivery to payee). ``received_date`` is validated separately
		as preparation / internal issue date (:meth:`_validate_received_date_required_for_payable_issued`).

		Message: :data:`PDC_VALIDATION_ISSUED_PAYABLE_ONLY` — same rule as
		:func:`get_pdc_workflow_transition_validation_error` (see :meth:`_validate_workflow_transition`).
		"""
		if normalize_workflow_state_value(self.workflow_state) != WORKFLOW_ISSUED:
			return
		if self.cheque_direction == CHEQUE_DIRECTION_RECEIVABLE:
			frappe.throw(
				frappe._(PDC_VALIDATION_ISSUED_PAYABLE_ONLY),
				title=frappe._("Invalid Issued workflow state"),
			)
		if not getattr(self, "handover_date", None):
			frappe.throw(
				frappe._(
					"Handover / Endorsement Date is mandatory when Workflow State is Issued (Payable): "
					"enter the date the cheque was physically given to the payee (not the preparation date in Received / Issued Date)."
				),
				title=frappe._("Missing Handover Date"),
			)

	def _validate_sent_to_bank_workflow_state(self):
		"""**Sent to Bank** is only valid for Receivable cheques (not Payable).

		Requires ``sent_to_bank_date`` (date handed to the bank for collection — not inferred from workflow time).

		Message: :data:`PDC_VALIDATION_SENT_TO_BANK_RECEIVABLE_ONLY` — same rule as
		:func:`get_pdc_workflow_transition_validation_error` (see :meth:`_validate_workflow_transition`).
		"""
		if normalize_workflow_state_value(self.workflow_state) != WORKFLOW_SENT_TO_BANK:
			return
		if self.cheque_direction == CHEQUE_DIRECTION_PAYABLE:
			frappe.throw(
				frappe._(PDC_VALIDATION_SENT_TO_BANK_RECEIVABLE_ONLY),
				title=frappe._("Invalid Sent to Bank workflow state"),
			)
		if not getattr(self, "sent_to_bank_date", None):
			frappe.throw(
				frappe._(
					"Sent to Bank Date is mandatory when Workflow State is Sent to Bank. "
					"Enter the date the receivable cheque was delivered or submitted to the bank for collection."
				),
				title=frappe._("Missing Sent to Bank Date"),
			)
		# Sent to Bank requires a clearing account (either per-document override or company defaults).
		acc = resolve_pdc_accounts_for_journal(self)
		if not acc.get("cheques_in_clearing"):
			frappe.throw(
				frappe._(
					"Cheques in Clearing Account is required when Workflow State is Sent to Bank. "
					"Set Post Dated Cheque → Cheques in Clearing Account or configure Default Cheques in Clearing Account in PDC Settings."
				),
				title=frappe._("Clearing account required"),
			)

	def _set_default_bank_account_for_receivable(self) -> None:
		"""If **Receivable** and **Bank Account** is empty, set company default bank (if any).

		Uses **Bank Account** rows with ``company`` = PDC company, ``is_company_account``,
		and ``is_default`` (ERPNext field — not ``is_default_account``). If several match,
		picks the first by name; if none match, leaves the field empty (no error).
		"""
		if self.cheque_direction != CHEQUE_DIRECTION_RECEIVABLE:
			return
		if _strip_link_name_or_none(self.bank_account):
			return
		if not self.company:
			return
		names = frappe.get_all(
			"Bank Account",
			filters={
				"company": self.company,
				"is_company_account": 1,
				"is_default": 1,
			},
			pluck="name",
			order_by="name asc",
			limit=1,
		)
		if names:
			self.bank_account = names[0]

	def _validate_bank_account_for_workflow_state(self):
		"""Require ``bank_account`` when the workflow stage needs a settlement bank.

		* **Payable:** Issued (Cleared is validated in :meth:`_validate_bank_account_for_cleared_workflow_state`)
		* **Receivable:** Sent to Bank (Cleared: same dedicated validator)
		"""
		if self.cheque_direction not in (CHEQUE_DIRECTION_RECEIVABLE, CHEQUE_DIRECTION_PAYABLE):
			return
		ws = normalize_workflow_state_value(self.workflow_state)
		if self.cheque_direction == CHEQUE_DIRECTION_PAYABLE:
			if ws == WORKFLOW_ISSUED and not self.bank_account:
				frappe.throw(
					frappe._(
						"Bank Account is required for Payable cheques when Workflow State is Issued."
					),
					title=frappe._("Bank Account required"),
				)
		elif self.cheque_direction == CHEQUE_DIRECTION_RECEIVABLE:
			if ws == WORKFLOW_SENT_TO_BANK and not self.bank_account:
				frappe.throw(
					frappe._(
						"Bank Account is required for Receivable cheques when Workflow State is Sent to Bank."
					),
					title=frappe._("Bank Account required"),
				)

	def _validate_bank_account_for_cleared_workflow_state(self) -> None:
		"""**Cleared:** settlement bank must be set and must be a **company** bank for this PDC company."""
		if normalize_workflow_state_value(self.workflow_state) != WORKFLOW_CLEARED:
			return
		if self.cheque_direction not in (CHEQUE_DIRECTION_RECEIVABLE, CHEQUE_DIRECTION_PAYABLE):
			return
		msg = frappe._("Bank account is required and must be a company account for clearing")
		ba = _strip_link_name_or_none(self.bank_account)
		if not ba:
			frappe.throw(msg, title=frappe._("Bank account required for clearing"))
		row = frappe.db.get_value(
			"Bank Account",
			ba,
			["is_company_account", "company"],
			as_dict=True,
		)
		if not row or not cint(row.get("is_company_account")):
			frappe.throw(msg, title=frappe._("Bank account required for clearing"))
		ba_company = (row.get("company") or "").strip()
		doc_company = (self.company or "").strip()
		if ba_company != doc_company:
			frappe.throw(msg, title=frappe._("Bank account required for clearing"))

	def _validate_bank_gl_account_for_cleared_workflow_state(self) -> None:
		"""**Cleared:** require a resolvable, real **Bank** GL account from the selected **Bank Account**.

		This is enforced at the Document layer so the workflow cannot reach **Cleared** without a
		bank-facing Journal Entry target ledger.
		"""
		if normalize_workflow_state_value(self.workflow_state) != WORKFLOW_CLEARED:
			return
		if self.cheque_direction not in (CHEQUE_DIRECTION_RECEIVABLE, CHEQUE_DIRECTION_PAYABLE):
			return
		bank_gl = _pdc_bank_gl_account(self)
		if not bank_gl:
			frappe.throw(
				frappe._("The linked **Bank Account** must have a company **Account** (GL) in ERPNext."),
				title=frappe._("Bank account required for clearing"),
			)
		if not frappe.db.exists("Account", bank_gl):
			frappe.throw(
				frappe._(
					"Bank Account {0} resolves to GL account {1}, but that Account does not exist. "
					"Select a Bank Account linked to a real Bank ledger."
				).format(self.bank_account, bank_gl),
				title=frappe._("Invalid bank ledger for clearing"),
			)
		_pdc_validate_clearing_bank_ledger_account(self, bank_gl)

	def _validate_receivable_bank_account_is_company_account(self):
		"""Receivable PDCs must link a **Bank Account** that is a company account for this PDC's company.

		Mirrors the Desk link filter in ``post_dated_cheque.js``; blocks API / import / manual bypass.
		Cleared uses :meth:`_validate_bank_account_for_cleared_workflow_state` (single user-facing message).
		"""
		if self.cheque_direction != CHEQUE_DIRECTION_RECEIVABLE:
			return
		if normalize_workflow_state_value(self.workflow_state) == WORKFLOW_CLEARED:
			return
		ba = _strip_link_name_or_none(self.bank_account)
		if not ba:
			return
		row = frappe.db.get_value(
			"Bank Account",
			ba,
			["is_company_account", "company"],
			as_dict=True,
		)
		if not row:
			return
		if not cint(row.get("is_company_account")):
			frappe.throw(
				frappe._("For receivable cheques, bank account must be a company account"),
				title=frappe._("Invalid Bank Account"),
			)
		ba_company = (row.get("company") or "").strip()
		doc_company = (self.company or "").strip()
		if ba_company != doc_company:
			frappe.throw(
				frappe._("For receivable cheques, bank account must be a company account"),
				title=frappe._("Invalid Bank Account"),
			)

	def _validate_payable_bank_account_is_company_account(self):
		"""Payable PDCs must link a **Bank Account** that is a company account for this PDC's company.

		**Cleared** always runs :meth:`_validate_bank_account_for_cleared_workflow_state` (single message);
		this covers earlier stages when a bank_account is provided.
		"""
		if self.cheque_direction != CHEQUE_DIRECTION_PAYABLE:
			return
		if normalize_workflow_state_value(self.workflow_state) == WORKFLOW_CLEARED:
			return
		ba = _strip_link_name_or_none(self.bank_account)
		if not ba:
			return
		row = frappe.db.get_value(
			"Bank Account",
			ba,
			["is_company_account", "company"],
			as_dict=True,
		)
		if not row:
			return
		if not cint(row.get("is_company_account")):
			frappe.throw(
				frappe._("For payable cheques, bank account must be a company account"),
				title=frappe._("Invalid Bank Account"),
			)
		ba_company = (row.get("company") or "").strip()
		doc_company = (self.company or "").strip()
		if ba_company != doc_company:
			frappe.throw(
				frappe._("For payable cheques, bank account must be a company account"),
				title=frappe._("Invalid Bank Account"),
			)

	def _validate_returned_workflow_state(self):
		"""**Returned** is a business return, not a bank bounce (use **Bounced** for bank rejection).

		Requires ``return_reason``. Operational ``cheque_status``: Receivable → *Returned to Customer*;
		Payable → *Returned from Payee* (see :func:`map_workflow_state_to_cheque_status`). Runs after
		``cheque_status`` sync so labels can be checked.
		"""
		if normalize_workflow_state_value(self.workflow_state) != WORKFLOW_RETURNED:
			return
		if self.cheque_direction not in (CHEQUE_DIRECTION_RECEIVABLE, CHEQUE_DIRECTION_PAYABLE):
			frappe.throw(
				frappe._(
					"Workflow State Returned requires Cheque Direction Receivable or Payable."
				),
				title=frappe._("Invalid Returned workflow state"),
			)
		if not (self.return_reason or "").strip():
			frappe.throw(
				frappe._(
					"Return Reason is mandatory when Workflow State is Returned. "
					"Returned is a business return (not a bank bounce — use Workflow State Bounced for bank rejection)."
				),
				title=frappe._("Missing Return Reason"),
			)
		if not getattr(self, "returned_date", None):
			frappe.throw(
				frappe._(
					"Returned Date is mandatory when Workflow State is Returned. "
					"Returned is a business return, not a bank bounce — use Workflow State Bounced for bank rejection."
				),
				title=frappe._("Missing Returned Date"),
			)
		status = (self.cheque_status or "").strip()
		if self.cheque_direction == CHEQUE_DIRECTION_RECEIVABLE:
			if status != CHEQUE_STATUS_RETURNED_TO_CUSTOMER:
				frappe.throw(
					frappe._(
						"For Receivable cheques, Workflow State Returned must show Cheque Status «{0}»."
					).format(CHEQUE_STATUS_RETURNED_TO_CUSTOMER),
					title=frappe._("Returned workflow state"),
				)
		elif self.cheque_direction == CHEQUE_DIRECTION_PAYABLE:
			if status != CHEQUE_STATUS_RETURNED_FROM_PAYEE:
				frappe.throw(
					frappe._(
						"For Payable cheques, Workflow State Returned must show Cheque Status «{0}»."
					).format(CHEQUE_STATUS_RETURNED_FROM_PAYEE),
					title=frappe._("Returned workflow state"),
				)

	def _validate_replacement_links_when_replaced(self):
		"""Replacement chain when ``workflow_state`` is **Replaced**.

		At least one of ``replaces_cheque`` or ``replaced_by`` must be set; both empty is invalid.
		"""
		if normalize_workflow_state_value(self.workflow_state) != WORKFLOW_REPLACED:
			return
		has_replaces = bool((self.replaces_cheque or "").strip())
		has_replaced_by = bool((self.replaced_by or "").strip())
		if has_replaces or has_replaced_by:
			return
		frappe.throw(
			frappe._(
				"When Workflow State is Replaced, set at least one of Replaces Cheque or Replaced By."
			),
			title=frappe._("Missing replacement link"),
		)

	def _sync_cheque_status_from_workflow_state(self):
		"""Set ``cheque_status`` from ``workflow_state`` using ``pdc_workflow_to_cheque_status``.

		Calls :func:`map_workflow_state_to_cheque_status` with ``cheque_direction`` and
		``workflow_state``. Skips when ``cheque_direction`` is not Receivable/Payable.
		"""
		if self.cheque_direction not in ("Receivable", "Payable"):
			return
		mapped = map_workflow_state_to_cheque_status(self.cheque_direction, self.workflow_state)
		if mapped is None:
			frappe.throw(
				frappe._(
					"There is no Cheque Status mapped for Workflow State {0} with {1} cheque. "
					"Set a valid Workflow State for this cheque direction."
				).format(self.workflow_state or "", self.cheque_direction),
				title=frappe._("Cheque Status out of sync"),
			)
		self.cheque_status = mapped

	def _validate_cheque_status_matches_workflow_state(self):
		"""Ensure ``cheque_status`` equals the mapping for current ``workflow_state`` (no manual drift)."""
		if self.cheque_direction not in ("Receivable", "Payable"):
			return
		expected = map_workflow_state_to_cheque_status(self.cheque_direction, self.workflow_state)
		if expected is None:
			frappe.throw(
				frappe._(
					"There is no Cheque Status mapped for Workflow State {0} with {1} cheque. "
					"Set a valid Workflow State for this cheque direction."
				).format(self.workflow_state or "", self.cheque_direction),
				title=frappe._("Cheque Status out of sync"),
			)
		actual = (self.cheque_status or "").strip()
		if actual != expected:
			frappe.throw(
				frappe._(
					"Cheque Status ({0}) does not match Workflow State ({1}) for a {2} cheque. "
					"Expected Cheque Status: {3}."
				).format(
					self.cheque_status or "",
					normalize_workflow_state_value(self.workflow_state),
					self.cheque_direction,
					expected,
				),
				title=frappe._("Cheque Status mismatch"),
			)

	def _validate_clearing_accounting_payload(self) -> None:
		"""If policy requires **Journal Entry** for **→Cleared**, ensure a JE payload can be built."""
		if normalize_workflow_state_value(self.workflow_state) != WORKFLOW_CLEARED:
			return
		if not getattr(self, "cleared_date", None):
			frappe.throw(
				frappe._("Cleared Date is mandatory when Workflow State is Cleared."),
				title=frappe._("Missing Cleared Date"),
			)
		prev_raw = self._get_previous_workflow_state_for_accounting()
		action = get_accounting_action(self, prev_raw)
		if action != PDC_ACCOUNTING_JOURNAL_ENTRY:
			return
		from_n = normalize_workflow_state_value(prev_raw)
		posting_date = getattr(self, "cleared_date", None)
		payload = build_pdc_journal_entry_data(self, from_n, WORKFLOW_CLEARED, posting_date=posting_date)
		if payload:
			return

		msgs: list[str] = []
		if self.cheque_direction == CHEQUE_DIRECTION_RECEIVABLE:
			if not _strip_link_name_or_none(getattr(self, "bank_account", None)):
				msgs.append(
					frappe._("Set **Bank Account** on this PDC (required to clear at the bank).")
				)
			elif not _pdc_bank_gl_account(self):
				msgs.append(
					frappe._(
						"The linked **Bank Account** must have a company **Account** (GL) in ERPNext."
					)
				)
			if not getattr(self, "cheque_amount", None):
				msgs.append(frappe._("Set **Cheque Amount**."))
			settings = _get_pdc_settings_for_company(getattr(self, "company", None))
			acc = resolve_pdc_accounts_for_journal(self, settings)
			if from_n == WORKFLOW_SENT_TO_BANK and not acc.get("cheques_in_clearing"):
				msgs.append(
					frappe._(
						"Set **Default Cheques in Clearing Account** in **PDC Settings** for this company "
						"(required to clear after **Sent to Bank**)."
					)
				)
			cred = receivable_intermediary_account_for_bank_clear(self, from_n, acc)
			if not cred:
				if from_n == WORKFLOW_REGISTERED:
					msgs.append(
						frappe._(
							"Configure **Cheques in Hand** (PDC Settings or **Account Paid To**) to build the clear Journal Entry."
						)
					)
				elif from_n == WORKFLOW_UNDER_LEGAL_ACTION:
					msgs.append(
						frappe._(
							"For **Under Legal Action** → **Cleared**, configure **Protested** and/or **Cheques in Clearing** "
							"in **PDC Settings**, or **Account Paid To** for cheques in hand."
						)
					)
		elif self.cheque_direction == CHEQUE_DIRECTION_PAYABLE:
			if not _strip_link_name_or_none(getattr(self, "bank_account", None)):
				msgs.append(frappe._("Set **Bank Account** on this PDC."))
			elif not _pdc_bank_gl_account(self):
				msgs.append(
					frappe._("The linked **Bank Account** must have a company **Account** (GL) in ERPNext.")
				)
			settings = _get_pdc_settings_for_company(getattr(self, "company", None))
			acc = resolve_pdc_accounts_for_journal(self, settings)
			if not acc.get("payable_cheque"):
				msgs.append(
					frappe._(
						"Set **Default Payable Cheque Account** in **PDC Settings** for this company."
					)
				)
			if not getattr(self, "cheque_amount", None):
				msgs.append(frappe._("Set **Cheque Amount**."))
			if not self.party_type or not self.party:
				msgs.append(frappe._("Set **Party Type** and **Party**."))

		detail = "\n".join(f"• {m}" for m in msgs) if msgs else ""
		summary = frappe._(
			"Cannot set Workflow to **Cleared** until a **{0}** can be built for transition {1} → Cleared."
		).format(frappe._("Journal Entry"), from_n)
		body = summary if not detail else f"{summary}\n{detail}"
		frappe.throw(
			body,
			title=frappe._("PDC clearing"),
		)

	def _validate_replaces_cheque(self):
		"""Optional replacement chain links: ``replaces_cheque`` / ``replaced_by`` → Post Dated Cheque."""
		for fieldname, label in (
			("replaces_cheque", frappe._("Replaces Cheque")),
			("replaced_by", frappe._("Replaced By")),
		):
			other = self.get(fieldname)
			if not other:
				continue
			if self.name and other == self.name:
				frappe.throw(
					frappe._("{0} cannot point to this same Post Dated Cheque.").format(label),
					title=frappe._("Invalid replacement link"),
				)
			other_company = frappe.db.get_value("Post Dated Cheque", other, "company")
			if other_company and self.company and other_company != self.company:
				frappe.throw(
					frappe._("{0} must belong to the same Company ({1}).").format(label, self.company),
					title=frappe._("Invalid replacement link"),
				)

	def _validate_replacement_bidirectional_conflicts(self):
		"""Do not overwrite a valid existing counterparty link (B replaces A must match A.replaced_by)."""
		rc = _strip_link_name_or_none(self.replaces_cheque)
		rb = _strip_link_name_or_none(self.replaced_by)
		if rc:
			other_rb = _strip_link_name_or_none(frappe.db.get_value("Post Dated Cheque", rc, "replaced_by"))
			if other_rb and (not self.name or other_rb != self.name):
				frappe.throw(
					frappe._(
						"Post Dated Cheque {0} is already marked as replaced by {1}. "
						"Clear that link first or choose another cheque to replace."
					).format(rc, other_rb),
					title=frappe._("Replacement link conflict"),
				)
		if rb:
			other_rc = _strip_link_name_or_none(frappe.db.get_value("Post Dated Cheque", rb, "replaces_cheque"))
			if other_rc and (not self.name or other_rc != self.name):
				frappe.throw(
					frappe._(
						"Post Dated Cheque {0} already replaces {1}. "
						"Clear Replaces Cheque on that document first or pick another replacement cheque."
					).format(rb, other_rc),
					title=frappe._("Replacement link conflict"),
				)

	def _validate_replacement_no_cycle(self):
		"""Block self-replacement loops and multi-hop cycles (e.g. A←B←C←A along ``replaces_cheque``)."""
		rc = _strip_link_name_or_none(self.replaces_cheque)
		rb = _strip_link_name_or_none(self.replaced_by)
		if rc:
			self._assert_no_replacement_cycle_along_replaces_chain(rc, self.name)
		if rb and self.name:
			self._assert_no_replacement_cycle_along_replaces_chain(self.name, rb)

	def _assert_no_replacement_cycle_along_replaces_chain(
		self,
		start: str,
		replacer_name: str | None,
		*,
		max_hops: int = 500,
	) -> None:
		"""Follow ``replaces_cheque`` from ``start`` (older chain). Fail if we revisit a node (cycle in
		data) or if ``replacer_name`` appears on that chain (would close a replacement loop).
		"""
		if not start:
			return
		visited: set[str] = set()
		cur = start
		hops = 0
		while cur:
			hops += 1
			if hops > max_hops:
				frappe.throw(
					frappe._("Replacement chain from {0} is too long; check for circular links.").format(
						start
					),
					title=frappe._("Circular replacement"),
				)
			if replacer_name and cur == replacer_name:
				frappe.throw(
					frappe._(
						"This replacement would create a circular chain: the replacer cannot appear in the "
						"replacement history of the cheque being replaced."
					),
					title=frappe._("Circular replacement"),
				)
			if cur in visited:
				frappe.throw(
					frappe._("A circular replacement chain exists involving Post Dated Cheque {0}.").format(
						cur
					),
					title=frappe._("Circular replacement"),
				)
			visited.add(cur)
			nxt = _strip_link_name_or_none(
				frappe.db.get_value("Post Dated Cheque", cur, "replaces_cheque")
			)
			if not nxt:
				break
			cur = nxt

	def _sync_replacement_bidirectional_links(self):
		"""Mirror replacement links on the other PDC and clear stale links when fields change.

		If **B** replaces **A** (``B.replaces_cheque = A``), set ``A.replaced_by = B``.
		If **A** is replaced by **B** (``A.replaced_by = B``), set ``B.replaces_cheque = A``.
		Uses ``frappe.db.set_value`` (no recursive full save). Clears the previous counterparty
		when a link is removed or repointed.
		"""
		if not self.name:
			return
		before = self.get_doc_before_save()
		prev_rc = _strip_link_name_or_none(before.get("replaces_cheque")) if before else None
		prev_rb = _strip_link_name_or_none(before.get("replaced_by")) if before else None
		cur_rc = _strip_link_name_or_none(self.replaces_cheque)
		cur_rb = _strip_link_name_or_none(self.replaced_by)

		def _clear_if_points_to_me(other_name: str, field: str) -> None:
			if not other_name or not frappe.db.exists("Post Dated Cheque", other_name):
				return
			current = _strip_link_name_or_none(frappe.db.get_value("Post Dated Cheque", other_name, field))
			if current == self.name:
				frappe.db.set_value("Post Dated Cheque", other_name, field, None)

		# Drop stale back-references when this document repoints or clears a link.
		if prev_rc and prev_rc != cur_rc:
			_clear_if_points_to_me(prev_rc, "replaced_by")
		if prev_rb and prev_rb != cur_rb:
			_clear_if_points_to_me(prev_rb, "replaces_cheque")

		# B.replaces_cheque = A  →  A.replaced_by = B
		if cur_rc and frappe.db.exists("Post Dated Cheque", cur_rc):
			existing = _strip_link_name_or_none(frappe.db.get_value("Post Dated Cheque", cur_rc, "replaced_by"))
			if existing in (None, self.name):
				frappe.db.set_value("Post Dated Cheque", cur_rc, "replaced_by", self.name)

		# A.replaced_by = B  →  B.replaces_cheque = A
		if cur_rb and frappe.db.exists("Post Dated Cheque", cur_rb):
			existing = _strip_link_name_or_none(frappe.db.get_value("Post Dated Cheque", cur_rb, "replaces_cheque"))
			if existing in (None, self.name):
				frappe.db.set_value("Post Dated Cheque", cur_rb, "replaces_cheque", self.name)

	def _set_default_party_accounts(self):
		"""Set Account Paid From/To from party default or company default if empty.

		Skipped when updating an **already submitted** document so workflow-only saves do not
		overwrite GL links (`account_paid_from` / `account_paid_to`) after submit. Initial
		**Submit** (docstatus 0 → 1) still runs this because ``_doc_before_save.docstatus`` is 0.
		"""
		if not self.company:
			return
		before = self.get_doc_before_save()
		prev_docstatus = int(getattr(before, "docstatus", 0) or 0) if before is not None else 0
		if self.docstatus == 1 and prev_docstatus == 1:
			return

		prev_direction = None
		if before:
			prev_direction = before.get("cheque_direction")

		# Receivable: Account Paid To = Cheques in Hand from PDC Settings (default / direction switch).
		if self.cheque_direction == "Receivable":
			ch = _get_cheques_in_hand_account_for_company(self.company)
			if ch and (not self.account_paid_to or prev_direction == "Payable"):
				self.account_paid_to = ch

		if not self.party_type or not self.party:
			return

		if self.cheque_direction == "Receivable" and not self.account_paid_from:
			self.account_paid_from = _get_party_account_or_company_default(
				self.party_type, self.party, self.company, "receivable"
			)

		if self.cheque_direction == "Payable":
			# After switching from Receivable, replace Cheques-in-Hand with party payable default.
			if not self.account_paid_to or prev_direction == "Receivable":
				self.account_paid_to = _get_party_account_or_company_default(
					self.party_type, self.party, self.company, "payable"
				)

	def _validate_party(self):
		if not self.party_type or not self.party:
			frappe.throw(
				frappe._("Party Type and Party are required for {0} cheque.").format(
					self.cheque_direction or ""
				)
			)
		# Optional: party_type vs direction guidance (non-blocking)
		receivable_party_types = {"Customer", "Employee", "Shareholder"}
		payable_party_types = {"Supplier", "Employee", "Shareholder"}

		if self.cheque_direction == "Receivable" and self.party_type not in receivable_party_types:
			frappe.msgprint(
				frappe._("Receivable cheques typically use Party Type: Customer."),
				indicator="orange",
				alert=True,
			)
		if self.cheque_direction == "Payable" and self.party_type not in payable_party_types:
			frappe.msgprint(
				frappe._("Payable cheques typically use Party Type: Supplier."),
				indicator="orange",
				alert=True,
			)

	def _validate_duplicate_cheque_no(self):
		if not self.cheque_no or not self.company:
			return
		filters = {
			"cheque_no": self.cheque_no,
			"company": self.company,
			"name": ["!=", self.name or ""],
		}
		if frappe.db.exists("Post Dated Cheque", filters):
			frappe.throw(
				frappe._("Cheque Number {0} already exists for company {1}.").format(
					self.cheque_no, self.company
				)
			)

	def _validate_party_immutable_after_submit(self):
		"""Party (Received From / Paid To) must not change after submit."""
		if self.docstatus != 1:
			return
		before = self.get_doc_before_save()
		if not before:
			return
		if (before.party_type != self.party_type) or (before.party != self.party):
			frappe.throw(
				frappe._(
					"Cannot change Party Type or Party after submit. Cancel the document to make changes."
				)
			)

	def get_pdc_settings(self):
		"""Get PDC Settings for the company (by name or by company field)."""
		if not self.company:
			frappe.throw(frappe._("Company is required"))
		name = frappe.db.get_value("PDC Settings", {"company": self.company}, "name")
		if not name:
			name = self.company
		if not name or not frappe.db.exists("PDC Settings", name):
			frappe.throw(
				frappe._("PDC Settings not found for company {0}. Please create PDC Settings first.").format(
					self.company
				)
			)
		return frappe.get_doc("PDC Settings", name)

	def _has_register_entry(self):
		"""Check if Register JE already exists (Receive for receivable, Payable Issue for payable)."""
		for ref in (self.journal_references or []):
			if ref.purpose in ("Receive", "Payable Issue"):
				return True
		if self.name:
			count = frappe.db.count(
				"PDC Journal Reference",
				{"parent": self.name, "parenttype": "Post Dated Cheque", "purpose": ["in", ["Receive", "Payable Issue"]]},
			)
			if count and count > 0:
				return True
		return False

	def _create_register_cheque_je(self, posting_date=None):
		"""
		Create Journal Entry when transitioning to Registered.
		Receivable: Dr Cheques in Hand, Cr Account Paid From (party receivable).
		Payable: Dr Account Paid To (party payable), Cr Cheques Payable.
		"""
		if self._has_register_entry():
			return None
		settings = self.get_pdc_settings()
		posting_date = posting_date or (getattr(self, "received_date", None) if self.cheque_direction == "Receivable" else None) or getdate()

		if self.cheque_direction == "Receivable":
			if not settings.get("default_cheques_in_hand_account"):
				frappe.throw(
					frappe._("Cheques in Hand Account is not set in PDC Settings for company {0}.").format(
						self.company
					)
				)
			if not self.account_paid_from:
				frappe.throw(
					frappe._("Account Paid From is required for Receivable cheque. Set it or select Party first.")
				)
			je = frappe.new_doc("Journal Entry")
			je.posting_date = posting_date
			je.company = self.company
			je.voucher_type = "Journal Entry"
			je.cheque_no = self.cheque_no
			je.cheque_date = self.cheque_due_date
			je.user_remark = frappe._("Cheque {0} received from party - PDC Register").format(self.cheque_no)
			je.append(
				"accounts",
				{
					"account": settings.default_cheques_in_hand_account,
					"debit_in_account_currency": self.cheque_amount,
					"party_type": self.party_type,
					"party": self.party,
				},
			)
			je.append(
				"accounts",
				{
					"account": self.account_paid_from,
					"credit_in_account_currency": self.cheque_amount,
					"party_type": self.party_type,
					"party": self.party,
				},
			)
			je.flags.ignore_permissions = True
			je.save()
			je.submit()
			self.append(
				"journal_references",
				{
					"journal_entry": je.name,
					"purpose": "Receive",
					"posting_date": posting_date,
					"amount": self.cheque_amount,
				},
			)
			return je

		if self.cheque_direction == "Payable":
			if not settings.get("default_payable_cheque_account"):
				frappe.throw(
					frappe._("Default Payable Cheque Account is not set in PDC Settings for company {0}.").format(
						self.company
					)
				)
			if not self.account_paid_to:
				frappe.throw(
					frappe._("Account Paid To is required for Payable cheque. Set it or select Party first.")
				)
			je = frappe.new_doc("Journal Entry")
			je.posting_date = posting_date
			je.company = self.company
			je.voucher_type = "Journal Entry"
			je.cheque_no = self.cheque_no
			je.cheque_date = self.cheque_due_date
			je.user_remark = frappe._("Cheque {0} issued to party - PDC Register").format(self.cheque_no)
			je.append(
				"accounts",
				{
					"account": self.account_paid_to,
					"debit_in_account_currency": self.cheque_amount,
					"party_type": self.party_type,
					"party": self.party,
				},
			)
			je.append(
				"accounts",
				{
					"account": settings.default_payable_cheque_account,
					"credit_in_account_currency": self.cheque_amount,
					"party_type": self.party_type,
					"party": self.party,
				},
			)
			je.flags.ignore_permissions = True
			je.save()
			je.submit()
			self.append(
				"journal_references",
				{
					"journal_entry": je.name,
					"purpose": "Payable Issue",
					"posting_date": posting_date,
					"amount": self.cheque_amount,
				},
			)
			return je

		return None


def on_pdc_update_after_submit(doc, method=None):
	"""Legacy ``doc_events`` hook; logic lives on :meth:`PostDatedCheque.on_update_after_submit`."""
	return
