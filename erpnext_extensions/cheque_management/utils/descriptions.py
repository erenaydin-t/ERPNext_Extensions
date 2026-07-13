from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Any


class _SafeFormatDict(dict):
	"""`str.format_map` dict that never KeyErrors on missing placeholders."""

	def __missing__(self, key: str) -> str:
		# Preserve placeholder so user can spot missing fields.
		return "{" + key + "}"


def _normalize_template(template: str | None) -> str:
	return (template or "").strip()


def render_description_template(template: str | None, context: dict[str, Any]) -> str:
	"""Render a user-configured template safely.

	- Missing/unknown placeholders do not crash (they remain as `{placeholder}`).
	- Non-string values are converted to string (None -> "").
	- Invalid format strings fall back to raw template text.
	"""
	tpl = _normalize_template(template)
	if not tpl:
		return ""

	safe_ctx = _SafeFormatDict({k: ("" if v is None else v) for k, v in (context or {}).items()})
	try:
		return tpl.format_map(safe_ctx)
	except Exception:
		# Don't crash accounting; return raw template as-is.
		return tpl


@dataclass(frozen=True)
class PDCDescriptionContext:
	pdc_name: str | None
	cheque_no: str | None
	party: str | None
	party_type: str | None
	cheque_amount: Any
	cheque_due_date: Any
	workflow_state: str | None
	cheque_status: str | None
	cheque_direction: str | None
	company: str | None
	bank_account: str | None
	from_state: str | None
	to_state: str | None

	@classmethod
	def from_doc(cls, doc: Any, *, from_state: str | None = None, to_state: str | None = None):
		get = lambda k: (getattr(doc, k, None) if doc is not None else None)
		return cls(
			pdc_name=get("name"),
			cheque_no=get("cheque_no"),
			party=get("party"),
			party_type=get("party_type"),
			cheque_amount=get("cheque_amount"),
			cheque_due_date=get("cheque_due_date"),
			workflow_state=get("workflow_state"),
			cheque_status=get("cheque_status"),
			cheque_direction=get("cheque_direction"),
			company=get("company"),
			bank_account=get("bank_account"),
			from_state=from_state,
			to_state=to_state,
		)

	def as_dict(self) -> dict[str, Any]:
		return {
			"pdc_name": self.pdc_name,
			"cheque_no": self.cheque_no,
			"party": self.party,
			"party_type": self.party_type,
			"cheque_amount": self.cheque_amount,
			"cheque_due_date": self.cheque_due_date,
			"workflow_state": self.workflow_state,
			"cheque_status": self.cheque_status,
			"cheque_direction": self.cheque_direction,
			"company": self.company,
			"bank_account": self.bank_account,
			"from_state": self.from_state,
			"to_state": self.to_state,
		}


def render_pdc_je_text(
	template: str | None,
	*,
	fallback_text: str,
	context: PDCDescriptionContext,
	append_cheque_no_suffix: bool = False,
) -> str:
	"""Render a JE narration text with fallback + optional cheque_no suffix behavior.

	If `template` is empty -> return `fallback_text` (optionally with ` — cheque_no` suffix).
	If `template` is set -> render it; if suffix requested and template does not reference `{cheque_no}`,
	append the suffix (matches legacy behavior while allowing explicit placement).
	"""
	tpl = _normalize_template(template)
	out = ""
	if tpl:
		out = render_description_template(tpl, context.as_dict())
	else:
		out = fallback_text

	if append_cheque_no_suffix and (context.cheque_no or "").strip():
		if not tpl or "{cheque_no}" not in tpl:
			out = f"{out} — {context.cheque_no}"
	return out
