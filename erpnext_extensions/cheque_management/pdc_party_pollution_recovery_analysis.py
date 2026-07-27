# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Read-only recovery analysis for historical PDC Party-on-both pollution.

Identifies submitted Journal Entries linked to Post Dated Cheques where Party was
incorrectly mirrored onto internal accounts (CIH / Pool / Clearing / DPIC / Bank / Cash)
under the pre-fix ``_pdc_accounts_with_doc_party`` regression.

**This module never mutates documents.** It does not cancel, rollback, or correct data.

Usage (Administrator)::

	bench --site <site> execute \\
	  erpnext_extensions.cheque_management.pdc_party_pollution_recovery_analysis.run

Classification (Finance use):

* **A** — Safe rollback + re-forward
* **B** — Rollback available but needs manual review
* **C** — No rollback path
* **D** — Settled / terminal / Facility-linked; separate handling
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import frappe
from frappe.utils import cint

from erpnext_extensions.cheque_management.pdc_workflow_rollback import get_rollback_target_states
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_ASSIGNED_DEBT_PURCHASE,
	WORKFLOW_BOUNCED,
	WORKFLOW_CLEARED,
	WORKFLOW_CANCELLED,
	WORKFLOW_DEBT_PURCHASE_SETTLED,
	WORKFLOW_DRAFT,
	WORKFLOW_ENDORSED,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_REPLACED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
	is_workflow_transition_allowed,
	normalize_workflow_state_value,
)

CLASS_A = "A. Safe rollback + re-forward"
CLASS_B = "B. Rollback available but needs manual review"
CLASS_C = "C. No rollback path"
CLASS_D = "D. Settled / requires separate handling"

_INTERNAL_ACCOUNT_SQL = """
	(
		IFNULL(acc.account_type, '') IN ('Bank', 'Cash')
		OR jea.account LIKE '%%CIH%%'
		OR jea.account LIKE '%%POOL%%'
		OR jea.account LIKE '%%CLR%%'
		OR jea.account LIKE '%%Cheques in Hand%%'
		OR jea.account LIKE '%%Payable Pool%%'
		OR jea.account LIKE '%%خرید دین%%'
		OR jea.account LIKE '%%در جریان وصول%%'
		OR jea.account IN (
			SELECT default_cheques_in_hand_account FROM `tabPDC Settings`
			WHERE default_cheques_in_hand_account IS NOT NULL
			UNION
			SELECT default_cheques_in_clearing_account FROM `tabPDC Settings`
			WHERE default_cheques_in_clearing_account IS NOT NULL
			UNION
			SELECT default_payable_cheque_account FROM `tabPDC Settings`
			WHERE default_payable_cheque_account IS NOT NULL
			UNION
			SELECT default_protested_account FROM `tabPDC Settings`
			WHERE default_protested_account IS NOT NULL
			UNION
			SELECT default_debt_purchase_in_collection_account FROM `tabPDC Settings`
			WHERE default_debt_purchase_in_collection_account IS NOT NULL
		)
	)
"""

# Purpose → (from_state, to_state) for the edge that posted the JE (best-effort).
_PURPOSE_EDGE: dict[str, tuple[str, str]] = {
	"Receive": (WORKFLOW_DRAFT, WORKFLOW_REGISTERED),
	"Payable Issue": (WORKFLOW_DRAFT, WORKFLOW_REGISTERED),
	"Under Collection": (WORKFLOW_REGISTERED, WORKFLOW_SENT_TO_BANK),
	"Collected": (WORKFLOW_SENT_TO_BANK, WORKFLOW_CLEARED),  # may also be Registered→Cleared
	"Returned": (WORKFLOW_REGISTERED, WORKFLOW_RETURNED),  # ambiguous; review if B
	"Endorsement": (WORKFLOW_REGISTERED, WORKFLOW_ENDORSED),
	"Bounce": (WORKFLOW_SENT_TO_BANK, WORKFLOW_BOUNCED),
	"Debt Purchase Assignment": (WORKFLOW_REGISTERED, WORKFLOW_ASSIGNED_DEBT_PURCHASE),
	"Debt Purchase Settlement": (WORKFLOW_ASSIGNED_DEBT_PURCHASE, WORKFLOW_DEBT_PURCHASE_SETTLED),
	"Payable Clear": (WORKFLOW_ISSUED, WORKFLOW_CLEARED),
	"Cancel": (WORKFLOW_REGISTERED, WORKFLOW_CANCELLED),
	"Replacement": (WORKFLOW_RETURNED, WORKFLOW_REPLACED),
}


def _parse_transition_key(key: str | None) -> tuple[str | None, str | None, str | None]:
	"""Return (direction, from_state, to_state) from ``pdc|direction|from|to`` key."""
	parts = [p.strip() for p in (key or "").split("|") if p.strip()]
	if len(parts) >= 4:
		return parts[1], parts[2], parts[3]
	return None, None, None


def _find_polluted_journal_rows() -> list[dict[str, Any]]:
	"""One row per (PDC, polluted JE) with latest matching Journal Reference metadata."""
	return frappe.db.sql(
		f"""
		SELECT
			pdc.name AS pdc_name,
			pdc.cheque_no,
			pdc.party_type,
			pdc.party,
			pdc.cheque_direction,
			pdc.workflow_state,
			pdc.cheque_status,
			pdc.docstatus,
			pdc.company,
			pdc.is_opening_import,
			pdc.debt_purchase_facility,
			pdc.debt_purchase_repayment,
			je.name AS journal_entry,
			je.posting_date AS je_posting_date,
			je.creation AS je_creation,
			pjr.name AS journal_reference,
			pjr.purpose,
			pjr.pdc_transition_key,
			pjr.idx AS ref_idx,
			(
				SELECT COUNT(*)
				FROM `tabJournal Entry Account` jea2
				INNER JOIN `tabAccount` acc2 ON acc2.name = jea2.account
				WHERE jea2.parent = je.name
				  AND (IFNULL(jea2.party, '') != '' OR IFNULL(jea2.party_type, '') != '')
				  AND IFNULL(acc2.account_type, '') NOT IN ('Receivable', 'Payable')
			) AS polluted_line_count
		FROM `tabPost Dated Cheque` pdc
		INNER JOIN `tabPDC Journal Reference` pjr
			ON pjr.parent = pdc.name AND pjr.parenttype = 'Post Dated Cheque'
		INNER JOIN `tabJournal Entry` je
			ON je.name = pjr.journal_entry AND je.docstatus = 1
		WHERE EXISTS (
			SELECT 1
			FROM `tabJournal Entry Account` jea
			INNER JOIN `tabAccount` acc ON acc.name = jea.account
			WHERE jea.parent = je.name
			  AND (IFNULL(jea.party, '') != '' OR IFNULL(jea.party_type, '') != '')
			  AND IFNULL(acc.account_type, '') NOT IN ('Receivable', 'Payable')
			  AND {_INTERNAL_ACCOUNT_SQL}
		)
		ORDER BY pdc.name ASC, pjr.idx DESC
		""",
		as_dict=True,
	)


def _latest_ref(pdc_name: str) -> dict[str, Any] | None:
	rows = frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["name", "journal_entry", "purpose", "pdc_transition_key", "idx", "posting_date"],
		order_by="idx desc",
		limit=1,
	)
	return rows[0] if rows else None


def _forward_reexecutable(direction: str, from_state: str, to_state: str) -> bool:
	if not from_state or not to_state:
		return False
	return is_workflow_transition_allowed(direction, from_state, to_state)


def _classify_row(
	*,
	workflow_state: str,
	docstatus: int,
	direction: str,
	is_opening_import: int,
	debt_purchase_facility: str | None,
	debt_purchase_repayment: str | None,
	purpose: str | None,
	transition_key: str | None,
	rollback_targets: list[str],
	polluted_je_count_on_pdc: int,
) -> tuple[str, str, bool, bool, bool]:
	"""Return (class, notes, rollback_possible, forward_after_rollback, manual_approval)."""
	ws = normalize_workflow_state_value(workflow_state)
	key_dir, key_from, key_to = _parse_transition_key(transition_key)
	edge = _PURPOSE_EDGE.get((purpose or "").strip())
	from_state = key_from or (edge[0] if edge else None)
	to_state = key_to or (edge[1] if edge else None)

	manual = True  # Finance always reviews before recovery; flag distinguishes extra review
	notes: list[str] = []

	# D — terminal / Facility settled
	if ws == WORKFLOW_DEBT_PURCHASE_SETTLED or (debt_purchase_repayment or "").strip():
		notes.append("Debt Purchase Settled / Facility Repayment linked — cancel Facility Repayment first.")
		return CLASS_D, "; ".join(notes), False, False, True
	if ws in (WORKFLOW_CLEARED, WORKFLOW_CANCELLED, WORKFLOW_REPLACED):
		notes.append(f"Terminal workflow state {ws}.")
		return CLASS_D, "; ".join(notes), False, False, True
	if ws == WORKFLOW_ENDORSED:
		notes.append("Endorsed has no outgoing transitions; recovery needs special review.")
		return CLASS_D, "; ".join(notes), bool(rollback_targets), False, True

	if cint(docstatus) != 1:
		notes.append(f"docstatus={docstatus}; rollback engine requires submitted PDC.")
		return CLASS_C, "; ".join(notes), False, False, True

	if not rollback_targets:
		notes.append("No rollback targets returned by get_rollback_target_states.")
		return CLASS_C, "; ".join(notes), False, False, True

	rollback_possible = bool(from_state and from_state in rollback_targets)
	if not rollback_possible and from_state:
		notes.append(
			f"Inferred prior state {from_state!r} not in rollback targets {rollback_targets}."
		)
	elif not from_state:
		notes.append("Could not infer prior state from transition key/purpose.")
		rollback_possible = bool(rollback_targets)
		# Prefer safest common targets
		if WORKFLOW_REGISTERED in rollback_targets:
			from_state = WORKFLOW_REGISTERED
		elif WORKFLOW_DRAFT in rollback_targets:
			from_state = WORKFLOW_DRAFT

	forward_ok = False
	if from_state and to_state:
		forward_ok = _forward_reexecutable(direction or key_dir or "", from_state, to_state)
		if not forward_ok:
			notes.append(f"Forward edge {from_state} → {to_state} not currently allowed.")
	elif from_state and purpose:
		# After rollback to from_state, can we reach current ws again?
		forward_ok = _forward_reexecutable(direction, from_state, ws)
		if forward_ok:
			to_state = ws
		else:
			notes.append(f"Forward from {from_state} to current {ws} not allowed.")

	if cint(is_opening_import):
		notes.append("Opening-import PDC — baseline constraints apply.")
		return CLASS_B, "; ".join(notes), rollback_possible, forward_ok, True

	if polluted_je_count_on_pdc > 1:
		notes.append(f"{polluted_je_count_on_pdc} polluted JEs on this PDC — multi-step recovery.")
		return CLASS_B, "; ".join(notes), rollback_possible, forward_ok, True

	if (purpose or "") in ("Returned", "Collected", "Bounce", "Replacement", "Cancel"):
		notes.append(f"Purpose {purpose!r} can map to multiple edges — confirm transition key.")
		return CLASS_B, "; ".join(notes), rollback_possible, forward_ok, True

	if (debt_purchase_facility or "").strip() and ws != WORKFLOW_DEBT_PURCHASE_SETTLED:
		notes.append("Unexpected debt_purchase_facility link while not Settled.")
		return CLASS_B, "; ".join(notes), rollback_possible, forward_ok, True

	if rollback_possible and forward_ok:
		notes.append(
			f"Rollback to {from_state}, then re-apply {from_state} → {to_state or ws} under fixed Party code."
		)
		# Safe path still needs Finance approval before execution
		return CLASS_A, "; ".join(notes), True, True, True

	if rollback_possible:
		notes.append("Rollback targets exist but forward re-execution not confirmed.")
		return CLASS_B, "; ".join(notes), True, False, True

	return CLASS_C, "; ".join(notes) or "Rollback not viable for inferred edge.", False, False, True


def analyze_party_pollution_recovery(*, write_files: bool = True) -> dict[str, Any]:
	"""Build the full read-only recovery analysis report."""
	raw = _find_polluted_journal_rows()

	# Group by PDC; keep one analysis row per (pdc, journal_entry) using highest ref idx
	seen_je: set[tuple[str, str]] = set()
	by_pdc_polluted_jes: dict[str, set[str]] = {}
	unique_rows: list[dict[str, Any]] = []
	for row in raw:
		key = (row.pdc_name, row.journal_entry)
		by_pdc_polluted_jes.setdefault(row.pdc_name, set()).add(row.journal_entry)
		if key in seen_je:
			continue
		seen_je.add(key)
		unique_rows.append(row)

	report_rows: list[dict[str, Any]] = []
	for row in unique_rows:
		pdc_name = row.pdc_name
		try:
			targets = get_rollback_target_states(pdc_name) if cint(row.docstatus) == 1 else []
		except Exception as exc:
			targets = []
			target_error = f"{type(exc).__name__}: {exc}"
		else:
			target_error = None

		latest = _latest_ref(pdc_name)
		polluted_on_pdc = len(by_pdc_polluted_jes.get(pdc_name, ()))
		classification, notes, rb_ok, fwd_ok, needs_approval = _classify_row(
			workflow_state=row.workflow_state or "",
			docstatus=cint(row.docstatus),
			direction=(row.cheque_direction or "").strip(),
			is_opening_import=cint(row.is_opening_import),
			debt_purchase_facility=row.debt_purchase_facility,
			debt_purchase_repayment=row.debt_purchase_repayment,
			purpose=row.purpose,
			transition_key=row.pdc_transition_key,
			rollback_targets=targets,
			polluted_je_count_on_pdc=polluted_on_pdc,
		)
		if target_error:
			notes = f"{notes}; rollback target lookup error: {target_error}".strip("; ")

		key_dir, key_from, key_to = _parse_transition_key(row.pdc_transition_key)
		report_rows.append(
			{
				"pdc_name": pdc_name,
				"cheque_no": row.cheque_no,
				"party_type": row.party_type,
				"party": row.party,
				"cheque_direction": row.cheque_direction,
				"current_workflow_state": row.workflow_state,
				"cheque_status": row.cheque_status,
				"docstatus": cint(row.docstatus),
				"company": row.company,
				"is_opening_import": cint(row.is_opening_import),
				"debt_purchase_facility": row.debt_purchase_facility,
				"debt_purchase_repayment": row.debt_purchase_repayment,
				"linked_journal_entry": row.journal_entry,
				"je_posting_date": str(row.je_posting_date) if row.je_posting_date else None,
				"je_creation": str(row.je_creation) if row.je_creation else None,
				"polluted_line_count": cint(row.polluted_line_count),
				"polluted_je_count_on_pdc": polluted_on_pdc,
				"affected_journal_reference": row.journal_reference,
				"affected_purpose": row.purpose,
				"affected_transition_key": row.pdc_transition_key,
				"inferred_from_state": key_from,
				"inferred_to_state": key_to,
				"last_pdc_journal_reference": latest.name if latest else None,
				"last_transition_purpose": latest.purpose if latest else None,
				"last_transition_key": latest.pdc_transition_key if latest else None,
				"last_journal_entry": latest.journal_entry if latest else None,
				"rollback_targets": targets,
				"rollback_to_previous_possible": rb_ok,
				"forward_transition_after_rollback": fwd_ok,
				"manual_approval_required": needs_approval,
				"classification": classification,
				"notes": notes,
			}
		)

	# Prefer one summary line per PDC (most recent polluted JE / highest severity class)
	_class_rank = {CLASS_D: 0, CLASS_C: 1, CLASS_B: 2, CLASS_A: 3}
	by_pdc: dict[str, list[dict[str, Any]]] = {}
	for r in report_rows:
		by_pdc.setdefault(r["pdc_name"], []).append(r)

	pdc_summaries: list[dict[str, Any]] = []
	for pdc_name, rows in sorted(by_pdc.items()):
		primary = sorted(
			rows,
			key=lambda r: (_class_rank.get(r["classification"], 9), r.get("je_creation") or ""),
		)[0]
		summary = dict(primary)
		summary["all_polluted_journal_entries"] = sorted({r["linked_journal_entry"] for r in rows})
		summary["affected_purposes"] = sorted({r["affected_purpose"] for r in rows if r["affected_purpose"]})
		pdc_summaries.append(summary)

	counts = Counter(r["classification"] for r in pdc_summaries)
	report = {
		"generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
		"site": getattr(frappe.local, "site", None),
		"read_only": True,
		"actions_executed": False,
		"definition": {
			"pollution": (
				"Submitted JE linked via PDC Journal Reference with Party on internal "
				"non-Receivable/Payable accounts (CIH/Pool/Clearing/DPIC/Bank/Cash)."
			),
			"classes": {
				"A": CLASS_A,
				"B": CLASS_B,
				"C": CLASS_C,
				"D": CLASS_D,
			},
			"recovery_hint_A": (
				"After Finance approval: Rollback Workflow State to inferred prior state "
				"(cancels polluted JE), then re-apply the same forward workflow action so a "
				"new JE posts under the corrected Party-placement code. Does not rewrite history."
			),
		},
		"totals": {
			"affected_pdc_count": len(pdc_summaries),
			"affected_je_count": len({r["linked_journal_entry"] for r in report_rows}),
			"affected_je_pdc_pairs": len(report_rows),
			"by_classification": dict(counts),
		},
		"documents": pdc_summaries,
		"je_detail_rows": report_rows,
	}

	if write_files:
		_write_report_files(report)
	return report


def _write_report_files(report: dict[str, Any]) -> dict[str, str]:
	base = Path(frappe.get_app_path("erpnext_extensions")) / "cheque_management" / "release_reports"
	base.mkdir(parents=True, exist_ok=True)
	json_path = base / "PDC_PARTY_POLLUTION_RECOVERY_ANALYSIS.json"
	md_path = base / "PDC_PARTY_POLLUTION_RECOVERY_ANALYSIS.md"

	json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
	md_path.write_text(_format_markdown(report), encoding="utf-8")
	return {"json": str(json_path), "markdown": str(md_path)}


def _format_markdown(report: dict[str, Any]) -> str:
	lines: list[str] = [
		"# PDC Party Pollution Recovery Analysis",
		"",
		f"- Generated: `{report['generated_at']}`",
		f"- Site: `{report.get('site')}`",
		"- Mode: **read-only** (no documents modified)",
		"",
		"## Totals",
		"",
		f"- Affected PDCs: **{report['totals']['affected_pdc_count']}**",
		f"- Affected submitted JEs: **{report['totals']['affected_je_count']}**",
		"",
		"### By classification",
		"",
	]
	for cls, n in sorted(report["totals"]["by_classification"].items()):
		lines.append(f"- {cls}: **{n}**")
	lines.extend(
		[
			"",
			"## Classification guide",
			"",
			"| Class | Meaning |",
			"|---|---|",
			f"| A | {CLASS_A} |",
			f"| B | {CLASS_B} |",
			f"| C | {CLASS_C} |",
			f"| D | {CLASS_D} |",
			"",
			f"**Recommended A path:** {report['definition']['recovery_hint_A']}",
			"",
			"## Documents",
			"",
			"| Class | PDC | Cheque | Party | State | Polluted JE | JE posting | Purpose | Rollback targets | Forward after RB | Approval | Notes |",
			"|---|---|---|---|---|---|---|---|---|---|---|---|",
		]
	)
	for d in report["documents"]:
		party = f"{d.get('party_type') or ''}:{d.get('party') or ''}"
		targets = ", ".join(d.get("rollback_targets") or []) or "—"
		lines.append(
			"| {cls} | `{pdc}` | {cheque} | {party} | {state} | `{je}` | {post} | {purpose} | {targets} | {fwd} | {appr} | {notes} |".format(
				cls=d["classification"].split(".")[0],
				pdc=d["pdc_name"],
				cheque=d.get("cheque_no") or "",
				party=party,
				state=d.get("current_workflow_state") or "",
				je=d.get("linked_journal_entry") or "",
				post=d.get("je_posting_date") or "",
				purpose=d.get("affected_purpose") or "",
				targets=targets.replace("|", "/"),
				fwd="yes" if d.get("forward_transition_after_rollback") else "no",
				appr="yes" if d.get("manual_approval_required") else "no",
				notes=(d.get("notes") or "").replace("|", "/"),
			)
		)
	lines.extend(
		[
			"",
			"## Important",
			"",
			"- Do **not** execute rollback from this report without Finance approval.",
			"- Rollback **cancels** the polluted JE; it does not rewrite Party in place.",
			"- Correct Party matrix appears only after **re-forward** under the Party-placement fix.",
			"- Class D (Debt Purchase Settled) requires Facility Repayment cancel before PDC rollback.",
			"",
		]
	)
	return "\n".join(lines)


def run() -> dict[str, Any]:
	"""Bench entrypoint: analyze and write release_reports files; return summary."""
	frappe.set_user("Administrator")
	report = analyze_party_pollution_recovery(write_files=True)
	summary = {
		"generated_at": report["generated_at"],
		"totals": report["totals"],
		"files": {
			"markdown": "erpnext_extensions/cheque_management/release_reports/PDC_PARTY_POLLUTION_RECOVERY_ANALYSIS.md",
			"json": "erpnext_extensions/cheque_management/release_reports/PDC_PARTY_POLLUTION_RECOVERY_ANALYSIS.json",
		},
		"sample_A": [d["pdc_name"] for d in report["documents"] if d["classification"] == CLASS_A][:10],
		"sample_B": [d["pdc_name"] for d in report["documents"] if d["classification"] == CLASS_B][:10],
		"sample_C": [d["pdc_name"] for d in report["documents"] if d["classification"] == CLASS_C][:10],
		"sample_D": [d["pdc_name"] for d in report["documents"] if d["classification"] == CLASS_D][:10],
	}
	print(json.dumps(summary, indent=2, default=str))
	return summary


__all__ = [
	"CLASS_A",
	"CLASS_B",
	"CLASS_C",
	"CLASS_D",
	"analyze_party_pollution_recovery",
	"run",
]
