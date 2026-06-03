# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Receivable PDC **accounting model** (single reference for GL + party policy).

**Party dimension (Customer / Party receivable)**

* **Credited once** — Draft → Registered: Dr Cheques in Hand, Cr Party (registration).
* **Debited to reverse** — Registered → Returned: Dr Party, Cr Cheques in Hand.
* **Endorsement (Registered → Endorsed)** — Dr settlement GL (PDC Settings / per-PDC account) **or**
  Dr endorsed holder’s receivable (party = holder only); **Cr Cheques in Hand**. No bank, no PE,
  no second hit to the **drawer’s** receivable (already settled at registration).
* **No party** on intermediary-only moves: Sent to Bank, Cleared, Bounced, or replacement
  JEs that only reclass between pool / clearing / protested / bank GL accounts.

**Bank settlement (→ Cleared)** — always **Journal Entry**: **Dr** company **Bank** GL (from PDC Bank Account;
COA ``account_type`` must be **Bank**, same company as the PDC), **Cr** Cheques in Clearing
(from Sent to Bank), Cr Cheques in Hand (from Registered), or Cr protested/clearing/in-hand
(from Under Legal Action). No Payment Entry for Receivable clear (avoids ERPNext applying
party to the non-AR leg).
"""

from __future__ import annotations

from typing import Any

from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
	WORKFLOW_UNDER_LEGAL_ACTION,
)


def _pdc_link_name(value) -> str | None:
	if not value:
		return None
	s = str(value).strip()
	return s or None


def receivable_intermediary_account_for_bank_clear(doc: Any, from_state: str, acc: dict) -> str | None:
	"""GL account to **credit** when clearing at the bank (non-bank leg), by prior workflow state.

	May be Receivable/Payable in Chart of Accounts; JE payload carries drawer **Party** on this leg.

	* **Registered** → Cleared: **Cheques in Hand** — same resolution as registration Dr
	  (``account_paid_to`` or ``acc["cheques_in_hand"]`` from :func:`resolve_pdc_accounts_for_journal`).
	* **Sent to Bank** → Cleared: **Cheques in Clearing** (PDC Settings).
	* **Under Legal Action** → Cleared: **Protested** if set, else Clearing, else Cheques in Hand.
	"""
	if from_state == WORKFLOW_REGISTERED:
		return _pdc_link_name(getattr(doc, "account_paid_to", None)) or acc.get("cheques_in_hand")
	if from_state == WORKFLOW_SENT_TO_BANK:
		return acc.get("cheques_in_clearing")
	if from_state == WORKFLOW_UNDER_LEGAL_ACTION:
		if acc.get("protested"):
			return acc.get("protested")
		if acc.get("cheques_in_clearing"):
			return acc.get("cheques_in_clearing")
		return _pdc_link_name(getattr(doc, "account_paid_to", None)) or acc.get("cheques_in_hand")
	return None


__all__ = [
	"receivable_intermediary_account_for_bank_clear",
]
