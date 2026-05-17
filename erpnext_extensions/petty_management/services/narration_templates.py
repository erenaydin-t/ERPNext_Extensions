from __future__ import annotations

"""Pure template rendering for PM accounting narrations (no Frappe import)."""

from typing import Any

from erpnext_extensions.cheque_management.utils.descriptions import render_description_template

_USER_REMARK_LABEL = "User Remark:"


def compose_accounting_narration(system_text: str, user_remark: str | None) -> str:
	"""System narration first; optional user block from source document remark."""
	system = (system_text or "").strip()
	user = (user_remark or "").strip()
	if not user:
		return system
	if not system:
		return f"{_USER_REMARK_LABEL}\n{user}"
	return f"{system}\n\n{_USER_REMARK_LABEL}\n{user}"


def render_pm_template(template: str | None, context: dict[str, Any], *, fallback: str) -> str:
	tpl = (template or "").strip()
	if not tpl:
		return fallback
	rendered = render_description_template(tpl, context).strip()
	return rendered or fallback
