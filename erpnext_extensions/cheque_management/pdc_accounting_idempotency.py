# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""PDC accounting **transition keys** and idempotent resolution.

**Canonical key** (one Journal Entry per Post Dated Cheque per workflow edge)::

    ``{cheque_name}|{cheque_direction}|{from_state}|{to_state}``

* ``cheque_name`` — trimmed PDC name (``tabPost Dated Cheque.name``).
* ``cheque_direction`` — canonical **Receivable** or **Payable** (see
  :func:`normalize_cheque_direction_for_accounting_key`).
* ``from_state`` / ``to_state`` — normalized with
  :func:`~pdc_workflow_state_machine.normalize_workflow_state_value`
  (blank/``None`` → **Draft**).

**Rules**

* A successful accounting transition may create **at most one** voucher for that key; repeated
  save / submit / ``update_after_submit`` must not insert another JE (enforced in
  ``pdc_journal_entry_service`` via :func:`get_existing_journal_entry_for_transition` and a
  per-PDC file lock while posting).
* ``journal_references`` stores the key in ``pdc_transition_key`` plus ``purpose``, ``posting_date``,
  ``amount``, and ``journal_entry`` for audit and matching.

**Legacy key** (still matched for existing DB rows)::

    ``{cheque_direction}|{from_state}|{to_state}``

(no cheque name prefix). Kept only for historical transition-key compatibility; lifecycle posting
is **Journal Entry** only.
"""

from __future__ import annotations

from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	normalize_workflow_state_value,
)


def normalize_cheque_direction_for_accounting_key(cheque_direction: str | None) -> str:
	"""Return canonical direction label used inside transition keys.

	Empty/unknown values default to **Receivable** (aligns with journal service fallback).
	"""
	s = (cheque_direction or "").strip()
	if not s:
		return CHEQUE_DIRECTION_RECEIVABLE
	low = s.lower()
	if low == "payable":
		return CHEQUE_DIRECTION_PAYABLE
	if low == "receivable":
		return CHEQUE_DIRECTION_RECEIVABLE
	return s


def build_pdc_transition_key_suffix(
	cheque_direction: str,
	from_state: str | None,
	to_state: str | None,
) -> str:
	"""Return ``direction|from|to`` only (legacy persisted form; unique per PDC when combined with parent)."""
	d = normalize_cheque_direction_for_accounting_key(cheque_direction)
	f = normalize_workflow_state_value(from_state)
	t = normalize_workflow_state_value(to_state)
	return f"{d}|{f}|{t}"


def build_pdc_accounting_transition_key(
	cheque_name: str,
	cheque_direction: str,
	from_state: str | None,
	to_state: str | None,
) -> str:
	"""Full idempotency key: ``cheque_name|cheque_direction|from_state|to_state``."""
	name = (cheque_name or "").strip()
	suffix = build_pdc_transition_key_suffix(cheque_direction, from_state, to_state)
	return f"{name}|{suffix}"


def stored_transition_key_matches(
	stored: str | None,
	cheque_name: str,
	cheque_direction: str,
	from_state: str | None,
	to_state: str | None,
) -> bool:
	"""True if ``stored`` matches the canonical full key or the legacy suffix (or is empty for legacy PE)."""
	if stored is None:
		return False
	s = str(stored).strip()
	if not s:
		return False
	full = build_pdc_accounting_transition_key(cheque_name, cheque_direction, from_state, to_state)
	suffix = build_pdc_transition_key_suffix(cheque_direction, from_state, to_state)
	return s == full or s == suffix


__all__ = [
	"build_pdc_accounting_transition_key",
	"build_pdc_transition_key_suffix",
	"normalize_cheque_direction_for_accounting_key",
	"stored_transition_key_matches",
]
