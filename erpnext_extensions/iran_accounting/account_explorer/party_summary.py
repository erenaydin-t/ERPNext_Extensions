# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

from frappe import _

from erpnext_extensions.iran_accounting.account_explorer.constants import (
	PARTY_SORTABLE_FIELDS,
	VIRTUAL_PARTY_UNSPECIFIED_KEY,
)
from erpnext_extensions.iran_accounting.account_explorer.measures import measures_from_opening_period, zero_measures
from erpnext_extensions.iran_accounting.account_explorer.pagination import paginate_summary_rows, sort_rows
from erpnext_extensions.iran_accounting.account_explorer.party_opening import (
	get_party_opening_balances,
	get_party_period_balances,
	get_unspecified_party_measures,
)
from erpnext_extensions.iran_accounting.account_explorer.party_sources import (
	enrich_party_rows,
	get_identifier_warnings,
	get_party_source_config_map,
	get_enabled_party_types,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec

_SORT_FIELDS_REQUIRING_FULL_ENRICHMENT = frozenset({"display_title", "party_identifier"})


def _needs_full_party_enrichment(spec: AccountExplorerQuerySpec) -> bool:
	field = spec.pagination.sort_field
	if field not in PARTY_SORTABLE_FIELDS:
		field = "display_code"
	return field in _SORT_FIELDS_REQUIRING_FULL_ENRICHMENT


def build_party_summary(spec: AccountExplorerQuerySpec) -> dict:
	party_types = get_enabled_party_types()
	if spec.party_scope.party_type:
		party_types = [spec.party_scope.party_type]

	opening = get_party_opening_balances(spec, party_types)
	period = get_party_period_balances(spec, party_types)
	keys = set(opening.keys()) | set(period.keys())
	source_by_type = get_party_source_config_map()

	rows: list[dict] = []
	for party_type, party in sorted(keys):
		opening_debit, opening_credit = opening.get((party_type, party), (0.0, 0.0))
		period_debit, period_credit = period.get((party_type, party), (0.0, 0.0))
		rows.append(
			{
				"row_key": f"party:{party_type}:{party}",
				"party_type": party_type,
				"party": party,
				"display_code": party,
				"display_title": party,
				"party_identifier": None,
				"is_virtual_group": 0,
				"drill_down_enabled": 1,
				**measures_from_opening_period(
					opening_debit, opening_credit, period_debit, period_credit
				),
			}
		)

	if not spec.party_scope.selected_party:
		unspecified = get_unspecified_party_measures(spec, party_types)
		if any(unspecified.values()):
			rows.append(
				{
					"row_key": VIRTUAL_PARTY_UNSPECIFIED_KEY,
					"party_type": "",
					"party": "",
					"display_code": "__UNSPECIFIED__",
					"display_title": _("Unspecified Party"),
					"party_identifier": None,
					"is_virtual_group": 1,
					"drill_down_enabled": 0,
					**measures_from_opening_period(
						unspecified["opening_debit"],
						unspecified["opening_credit"],
						unspecified["period_debit"],
						unspecified["period_credit"],
					),
				}
			)

	if _needs_full_party_enrichment(spec):
		enrich_party_rows(rows, source_by_type=source_by_type)

	rows = sort_rows(rows, spec, PARTY_SORTABLE_FIELDS)
	result = paginate_summary_rows(rows, spec)

	if not _needs_full_party_enrichment(spec):
		enrich_party_rows(result["rows"], source_by_type=source_by_type)

	result["warnings"] = sorted(set(get_identifier_warnings()))
	return result
