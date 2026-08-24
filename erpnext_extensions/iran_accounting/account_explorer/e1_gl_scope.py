# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""E1 Trial-Balance GL SQL narrowing for Account Explorer drills (v4.6.1).

Root / company-wide explorer keeps ERPNext company-wide scans.
Account-tree drills push ``included_account_names`` into GL WHERE clauses.
"""

from __future__ import annotations

from erpnext_extensions.iran_accounting.account_explorer.account_hierarchy import load_company_accounts
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec


def resolve_narrowed_gl_accounts(spec: AccountExplorerQuerySpec) -> list[str] | None:
	"""Return account names for SQL narrowing, or ``None`` for full-company queries.

	Uses the already-resolved ``included_account_names`` (ERPNext lft/rgt descendants
	via ``resolve_account_scope``). When that set covers the whole company chart,
	returns ``None`` so opening / period / policy-aux paths stay company-wide.
	"""
	scoped = list(spec.included_account_names or [])
	if not scoped:
		return None

	company_accounts = load_company_accounts(spec.company)
	company_names = {row.name for row in company_accounts}
	if not company_names:
		return None

	scoped_set = set(scoped)
	# Full company (root explorer): do not force account filtering.
	if scoped_set >= company_names or len(scoped_set) >= len(company_names):
		return None

	# Preserve resolution order for stable SQL parameter binding.
	return [name for name in scoped if name in company_names]
