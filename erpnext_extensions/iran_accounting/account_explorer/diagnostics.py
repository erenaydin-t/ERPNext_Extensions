# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe
from frappe import _

from erpnext_extensions.iran_accounting.account_explorer.account_hierarchy import (
	account_matches_configured_level,
	configured_level_lengths,
	load_company_accounts,
	normalize_account_number,
)
from erpnext_extensions.iran_accounting.account_explorer.dimension_discovery import get_discovered_dimensions
from erpnext_extensions.iran_accounting.account_explorer.party_sources import get_enabled_party_sources
from erpnext_extensions.iran_accounting.account_explorer.permissions import (
	assert_company_allowed,
	assert_diagnostics_allowed,
)
from erpnext_extensions.iran_accounting.account_explorer.query_builder import get_enabled_levels
from erpnext_extensions.iran_accounting.account_explorer.unified_party_registry import (
	get_active_unified_parties,
	get_uap_members,
	get_unified_party_types,
)

MAX_SAMPLES = 10
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _finding(
	*,
	category: str,
	check_id: str,
	severity: str,
	title: str,
	message: str,
	count: int = 0,
	samples: list[dict] | None = None,
) -> dict:
	return {
		"category": category,
		"check_id": check_id,
		"severity": severity,
		"title": title,
		"message": message,
		"count": count,
		"samples": (samples or [])[:MAX_SAMPLES],
	}


def _ok_finding(category: str, check_id: str, title: str) -> dict:
	return _finding(
		category=category,
		check_id=check_id,
		severity="info",
		title=title,
		message=_("No issues found."),
		count=0,
	)


def run_account_diagnostics(company: str) -> list[dict]:
	findings: list[dict] = []
	accounts = load_company_accounts(company)
	configured_lengths = configured_level_lengths(get_enabled_levels())
	by_normalized: dict[str, list[dict]] = defaultdict(list)

	missing_number: list[dict] = []
	invalid_length: list[dict] = []
	prefix_mismatch: list[dict] = []

	for account in accounts:
		if account.disabled:
			continue
		normalized = normalize_account_number(account.account_number)
		if not account.is_group and not normalized:
			missing_number.append(
				{"account": account.name, "account_name": account.account_name, "account_number": account.account_number}
			)
		if normalized:
			by_normalized[normalized].append(account)
		if normalized and not account_matches_configured_level(normalized, configured_lengths):
			if normalized.isdigit():
				invalid_length.append(
					{
						"account": account.name,
						"account_name": account.account_name,
						"account_number": account.account_number,
						"code_length": len(normalized),
					}
				)

	accounts_by_name = {row.name: row for row in accounts}
	for account in accounts:
		if account.disabled or not account.parent_account:
			continue
		normalized = normalize_account_number(account.account_number)
		parent = accounts_by_name.get(account.parent_account)
		if not normalized or not parent:
			continue
		parent_normalized = normalize_account_number(parent.account_number)
		if parent_normalized and normalized.isdigit() and parent_normalized.isdigit():
			if not normalized.startswith(parent_normalized):
				prefix_mismatch.append(
					{
						"account": account.name,
						"account_number": account.account_number,
						"parent_account": account.parent_account,
						"parent_account_number": parent.account_number,
					}
				)

	duplicate_codes: list[dict] = []
	for normalized, rows in by_normalized.items():
		if len(rows) > 1:
			duplicate_codes.append(
				{
					"normalized_code": normalized,
					"accounts": ", ".join(row.name for row in rows[:5]),
					"count": len(rows),
				}
			)

	if missing_number:
		findings.append(
			_finding(
				category="accounts",
				check_id="missing_account_number",
				severity="warning",
				title=_("Missing Account Number"),
				message=_("Leaf accounts without account numbers cannot participate in level grouping."),
				count=len(missing_number),
				samples=missing_number,
			)
		)
	else:
		findings.append(_ok_finding("accounts", "missing_account_number", _("Missing Account Number")))

	if invalid_length:
		findings.append(
			_finding(
				category="accounts",
				check_id="invalid_level_length",
				severity="warning",
				title=_("Invalid Account Level Length"),
				message=_("Numeric account codes must match configured Account Explorer level lengths."),
				count=len(invalid_length),
				samples=invalid_length,
			)
		)
	else:
		findings.append(_ok_finding("accounts", "invalid_level_length", _("Invalid Account Level Length")))

	if duplicate_codes:
		findings.append(
			_finding(
				category="accounts",
				check_id="duplicate_account_codes",
				severity="error",
				title=_("Duplicate Account Codes"),
				message=_("Multiple accounts share the same normalized account number."),
				count=len(duplicate_codes),
				samples=duplicate_codes,
			)
		)
	else:
		findings.append(_ok_finding("accounts", "duplicate_account_codes", _("Duplicate Account Codes")))

	if prefix_mismatch:
		findings.append(
			_finding(
				category="accounts",
				check_id="tree_code_mismatch",
				severity="warning",
				title=_("Tree / Code Prefix Mismatch"),
				message=_("Child account numbers do not extend their parent account number prefix."),
				count=len(prefix_mismatch),
				samples=prefix_mismatch,
			)
		)
	else:
		findings.append(_ok_finding("accounts", "tree_code_mismatch", _("Tree / Code Prefix Mismatch")))

	return findings


def run_dimension_diagnostics(company: str) -> list[dict]:
	findings: list[dict] = []
	gl_meta = frappe.get_meta("GL Entry")
	discovered = {row["fieldname"] for row in get_discovered_dimensions()}
	missing_on_gl: list[dict] = []
	missing_metadata: list[dict] = []

	try:
		from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
			get_accounting_dimensions,
		)

		for row in get_accounting_dimensions(as_list=False) or []:
			fieldname = row.fieldname
			if not fieldname:
				continue
			if not gl_meta.has_field(fieldname):
				missing_on_gl.append(
					{
						"fieldname": fieldname,
						"label": row.label,
						"document_type": row.document_type,
					}
				)
			elif fieldname not in discovered:
				missing_metadata.append(
					{
						"fieldname": fieldname,
						"label": row.label,
						"document_type": row.document_type,
					}
				)
	except Exception:
		pass

	if missing_on_gl:
		findings.append(
			_finding(
				category="dimensions",
				check_id="dimension_field_missing_on_gl",
				severity="error",
				title=_("Dimension Field Missing on GL Entry"),
				message=_("Configured accounting dimensions are not present on GL Entry."),
				count=len(missing_on_gl),
				samples=missing_on_gl,
			)
		)
	else:
		findings.append(
			_ok_finding("dimensions", "dimension_field_missing_on_gl", _("Dimension Field Missing on GL Entry"))
		)

	if missing_metadata:
		findings.append(
			_finding(
				category="dimensions",
				check_id="dimension_not_discovered",
				severity="warning",
				title=_("Dimension Not Discovered"),
				message=_("GL Entry fields exist but are not exposed for Account Explorer dimension analysis."),
				count=len(missing_metadata),
				samples=missing_metadata,
			)
		)
	else:
		findings.append(_ok_finding("dimensions", "dimension_not_discovered", _("Dimension Not Discovered")))

	if not discovered:
		findings.append(
			_finding(
				category="dimensions",
				check_id="no_discovered_dimensions",
				severity="info",
				title=_("No Discovered Dimensions"),
				message=_("No accounting dimensions are currently available for analysis."),
				count=0,
			)
		)

	return findings


def run_party_diagnostics(company: str) -> list[dict]:
	findings: list[dict] = []
	missing_identifier: list[dict] = []
	invalid_identifier_field: list[dict] = []

	for row in get_enabled_party_sources():
		if not row.identifier_field:
			missing_identifier.append({"party_type": row.party_type, "label": row.label or row.party_type})
			continue
		meta = frappe.get_meta(row.party_type)
		if not meta.has_field(row.identifier_field):
			invalid_identifier_field.append(
				{
					"party_type": row.party_type,
					"identifier_field": row.identifier_field,
				}
			)

	if missing_identifier:
		findings.append(
			_finding(
				category="party",
				check_id="missing_identifier_mapping",
				severity="warning",
				title=_("Missing Party Identifier Mapping"),
				message=_("Enabled party sources should define an identifier field for unified reporting."),
				count=len(missing_identifier),
				samples=missing_identifier,
			)
		)
	else:
		findings.append(
			_ok_finding("party", "missing_identifier_mapping", _("Missing Party Identifier Mapping"))
		)

	if invalid_identifier_field:
		findings.append(
			_finding(
				category="party",
				check_id="invalid_identifier_field",
				severity="error",
				title=_("Invalid Party Identifier Field"),
				message=_("Configured identifier fields are missing on the party DocType."),
				count=len(invalid_identifier_field),
				samples=invalid_identifier_field,
			)
		)
	else:
		findings.append(_ok_finding("party", "invalid_identifier_field", _("Invalid Party Identifier Field")))

	return findings


def run_unified_party_diagnostics(company: str) -> list[dict]:
	findings: list[dict] = []
	if not frappe.get_single_value("Iran Accounting Settings", "unified_party_enabled"):
		return findings

	allowed_types = set(get_unified_party_types())
	empty_members: list[dict] = []
	invalid_member_type: list[dict] = []

	for uap in get_active_unified_parties(company):
		members = get_uap_members(uap.name)
		if not members:
			empty_members.append(
				{"unified_party": uap.name, "unified_name": uap.unified_name, "company": uap.company}
			)
		for member in members:
			if member.party_type and member.party_type not in allowed_types:
				invalid_member_type.append(
					{
						"unified_party": uap.name,
						"party_type": member.party_type,
						"party": member.party,
					}
				)

	if empty_members:
		findings.append(
			_finding(
				category="unified_party",
				check_id="empty_unified_party",
				severity="warning",
				title=_("Unified Party Without Members"),
				message=_("Active Unified Accounting Parties should contain at least one member."),
				count=len(empty_members),
				samples=empty_members,
			)
		)
	else:
		findings.append(
			_ok_finding("unified_party", "empty_unified_party", _("Unified Party Without Members"))
		)

	if invalid_member_type:
		findings.append(
			_finding(
				category="unified_party",
				check_id="invalid_member_party_type",
				severity="warning",
				title=_("Unified Party Member Type Not Enabled"),
				message=_("Unified party members reference party types that are not enabled for unified analysis."),
				count=len(invalid_member_type),
				samples=invalid_member_type,
			)
		)
	else:
		findings.append(
			_ok_finding("unified_party", "invalid_member_party_type", _("Unified Party Member Type Not Enabled"))
		)

	return findings


def run_currency_diagnostics(company: str) -> list[dict]:
	findings: list[dict] = []
	blank_currency = frappe.db.count("GL Entry", {"company": company, "account_currency": ["in", ("", None)]})
	if blank_currency:
		samples = frappe.db.sql(
			"""
			select name, posting_date, voucher_type, voucher_no, account_currency
			from `tabGL Entry`
			where company = %s and ifnull(account_currency, '') = ''
			order by posting_date desc
			limit %s
			""",
			(company, MAX_SAMPLES),
			as_dict=True,
		)
		findings.append(
			_finding(
				category="currency",
				check_id="blank_account_currency",
				severity="warning",
				title=_("Blank Account Currency"),
				message=_("GL Entry rows with blank account_currency reduce currency analysis quality."),
				count=blank_currency,
				samples=samples,
			)
		)
	else:
		findings.append(_ok_finding("currency", "blank_account_currency", _("Blank Account Currency")))

	invalid_currencies = frappe.db.sql(
		"""
		select distinct gle.account_currency as currency
		from `tabGL Entry` gle
		left join `tabCurrency` c on c.name = gle.account_currency
		where gle.company = %s
			and ifnull(gle.account_currency, '') != ''
			and c.name is null
		limit %s
		""",
		(company, MAX_SAMPLES),
		as_dict=True,
	)
	if invalid_currencies:
		findings.append(
			_finding(
				category="currency",
				check_id="invalid_currency_values",
				severity="error",
				title=_("Invalid Currency Values"),
				message=_("GL Entry references currencies that do not exist in the Currency master."),
				count=len(invalid_currencies),
				samples=invalid_currencies,
			)
		)
	else:
		findings.append(_ok_finding("currency", "invalid_currency_values", _("Invalid Currency Values")))

	return findings


def _summarize_findings(findings: list[dict]) -> dict[str, int]:
	summary = {"error": 0, "warning": 0, "info": 0}
	for row in findings:
		severity = row.get("severity") or "info"
		if severity in summary and row.get("count", 0) > 0 and severity != "info":
			summary[severity] += 1
		elif severity == "info" and row.get("count", 0) == 0 and "No issues" in (row.get("message") or ""):
			summary["info"] += 1
	return summary


def run_account_explorer_diagnostics(company: str) -> dict[str, Any]:
	assert_diagnostics_allowed()
	if not company:
		frappe.throw(_("Company is required."))
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} does not exist").format(company))
	assert_company_allowed(company)

	findings: list[dict] = []
	findings.extend(run_account_diagnostics(company))
	findings.extend(run_dimension_diagnostics(company))
	findings.extend(run_party_diagnostics(company))
	findings.extend(run_unified_party_diagnostics(company))
	findings.extend(run_currency_diagnostics(company))
	findings.sort(key=lambda row: (SEVERITY_ORDER.get(row.get("severity"), 9), row.get("category"), row.get("check_id")))

	return {
		"company": company,
		"generated_at": frappe.utils.now_datetime(),
		"read_only": 1,
		"findings": findings,
		"summary": _summarize_findings(findings),
	}
