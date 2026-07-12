"""Live E2E: Facility Management monetary precision DECIMAL(30,9).

bench --site development.localhost execute \\
  erpnext_extensions.facility_management.run_live_facility_precision_e2e.run
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from decimal import Decimal

import frappe

from erpnext_extensions.facility_management.facility_monetary import parse_facility_amount
from erpnext_extensions.facility_management.facility_precision import (
	TABLES_AND_COLUMNS,
	TARGET_PRECISION,
	TARGET_SCALE,
)

P1_PRINCIPAL = Decimal("123456789012345.123456789")
P1_PROFIT = Decimal("98765432109876.123456789")
P2_PRINCIPAL = Decimal("1234567890123.123456789")
P2_PROFIT = Decimal("987654321234.123456789")


def _log(title: str, payload):
	print(f"\n=== {title} ===")
	print(json.dumps(payload, indent=2, default=str))


def _schema_snapshot() -> list[dict]:
	db_name = frappe.db.sql("SELECT DATABASE()")[0][0]
	tables = list(TABLES_AND_COLUMNS.keys())
	placeholders = ", ".join(["%s"] * len(tables))
	return frappe.db.sql(
		f"""
		SELECT TABLE_NAME, COLUMN_NAME, NUMERIC_PRECISION, NUMERIC_SCALE, COLUMN_TYPE
		FROM INFORMATION_SCHEMA.COLUMNS
		WHERE TABLE_SCHEMA = %s
		  AND TABLE_NAME IN ({placeholders})
		  AND DATA_TYPE = 'decimal'
		ORDER BY TABLE_NAME, COLUMN_NAME
		""",
		(db_name, *tables),
		as_dict=True,
	)


def _decimal_char_from_db(table: str, column: str, name: str) -> str | None:
	row = frappe.db.sql(
		f"SELECT CAST(`{column}` AS CHAR) AS v FROM `{table}` WHERE name = %s",
		(name,),
	)
	if not row or row[0][0] is None:
		return None
	return str(row[0][0])


def _ensure_core_je_gl_decimal_30_9() -> None:
	"""Repayment JE uses Journal Entry Account + GL Entry (must be DECIMAL(30,9) for FM-Precision-2)."""
	from erpnext_extensions.patches.post_model_sync.expand_currency_precision import execute as expand_je
	from erpnext_extensions.patches.post_model_sync.expand_gl_entry_amount_precision import (
		execute as expand_gl,
	)

	expand_je()
	expand_gl()
	frappe.db.commit()


from erpnext_extensions.facility_management.facility_e2e_context import site_e2e_context


def _site_accounts():
	ctx = site_e2e_context()
	return {
		"company": ctx["company"],
		"bank": ctx["bank"],
		"bank_gl": ctx["bank_gl"],
		"loan_payable": ctx["loan_payable"],
		"deferred": ctx["deferred"],
		"interest": ctx.get("interest") or ctx["deferred"],
	}


def _new_facility(ctx, suffix: str, principal: Decimal, profit: Decimal):
	doc = frappe.new_doc("Facility")
	doc.facility_name = f"FM Precision {suffix}"
	doc.company = ctx["company"]
	doc.bank = ctx["bank"]
	doc.contract_date = frappe.utils.today()
	doc.receive_date = frappe.utils.today()
	doc.principal_amount = str(principal)
	doc.profit_amount = str(profit)
	doc.loan_payable_account = ctx["loan_payable"]
	doc.bank_account = ctx["bank_gl"]
	doc.deferred_loan_interest_account = ctx["deferred"]
	doc.penalty_expense_account = ctx["interest"]
	doc.status = "Draft"
	doc.flags.facility_exact_currency = {
		"principal_amount": str(principal),
		"profit_amount": str(profit),
	}
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc


def _je_amount_rows(je_name: str) -> list[dict]:
	rows = frappe.db.sql(
		"""
		SELECT account,
			CAST(debit_in_account_currency AS CHAR) AS debit,
			CAST(credit_in_account_currency AS CHAR) AS credit
		FROM `tabJournal Entry Account`
		WHERE parent = %s
		ORDER BY idx ASC
		""",
		(je_name,),
		as_dict=True,
	)
	return rows


def _gl_amount_rows(je_name: str) -> list[dict]:
	return frappe.db.sql(
		"""
		SELECT account,
			CAST(debit AS CHAR) AS debit,
			CAST(credit AS CHAR) AS credit
		FROM `tabGL Entry`
		WHERE voucher_type = 'Journal Entry' AND voucher_no = %s AND is_cancelled = 0
		ORDER BY idx ASC
		""",
		(je_name,),
		as_dict=True,
	)


def run():
	frappe.set_user("Administrator")
	errors: list[str] = []
	results: dict = {"tests": {}}
	suffix = str(int(time.time()))

	_log("INFORMATION_SCHEMA (before tests)", _schema_snapshot())

	ctx = _site_accounts()

	# FM-Precision-1 — Facility storage only (no Receipt JE; amount exceeds default JE header if posted as one line)
	fac = _new_facility(ctx, suffix, P1_PRINCIPAL, P1_PROFIT)
	db_p = _decimal_char_from_db("tabFacility", "principal_amount", fac.name)
	db_pf = _decimal_char_from_db("tabFacility", "profit_amount", fac.name)
	t1 = {
		"facility": fac.name,
		"expected_principal": str(P1_PRINCIPAL),
		"expected_profit": str(P1_PROFIT),
		"db_principal_char": db_p,
		"db_profit_char": db_pf,
		"principal_exact": parse_facility_amount(db_p) == P1_PRINCIPAL,
		"profit_exact": parse_facility_amount(db_pf) == P1_PROFIT,
	}
	results["tests"]["FM-Precision-1"] = t1
	_log("FM-Precision-1 Facility save + DB exact", t1)
	if not t1["principal_exact"] or not t1["profit_exact"]:
		errors.append(f"FM-Precision-1: DB mismatch {t1}")

	_ensure_core_je_gl_decimal_30_9()

	# FM-Precision-2 — Repayment JE + GL (separate Active opening facility; limits fit DECIMAL(30,9))
	fac2 = _new_facility(ctx, f"rep-{suffix}", P1_PRINCIPAL, P1_PROFIT)
	fac2.is_opening_facility = 1
	fac2.status = "Active"
	fac2.save(ignore_permissions=True)
	frappe.db.commit()

	rep = frappe.new_doc("Facility Repayment")
	rep.facility = fac2.name
	rep.posting_date = frappe.utils.today()
	rep.principal_amount = str(P2_PRINCIPAL)
	rep.profit_amount = str(P2_PROFIT)
	rep.flags.facility_exact_currency = {
		"principal_amount": str(P2_PRINCIPAL),
		"profit_amount": str(P2_PROFIT),
	}
	rep.insert(ignore_permissions=True)
	rep.submit()
	frappe.db.commit()
	rep.reload()

	je_rows = _je_amount_rows(rep.journal_entry)
	gl_rows = _gl_amount_rows(rep.journal_entry)
	je_has_p = any(parse_facility_amount(r["debit"]) == P2_PRINCIPAL for r in je_rows)
	je_has_pf = any(parse_facility_amount(r["debit"]) == P2_PROFIT for r in je_rows)
	gl_has_p = any(parse_facility_amount(r["debit"]) == P2_PRINCIPAL for r in gl_rows)
	gl_has_pf = any(parse_facility_amount(r["debit"]) == P2_PROFIT for r in gl_rows)

	t2 = {
		"facility": fac2.name,
		"repayment": rep.name,
		"journal_entry": rep.journal_entry,
		"je_rows": je_rows,
		"gl_rows": gl_rows,
		"je_principal_exact": je_has_p,
		"je_profit_exact": je_has_pf,
		"gl_principal_exact": gl_has_p,
		"gl_profit_exact": gl_has_pf,
	}
	results["tests"]["FM-Precision-2"] = t2
	_log("FM-Precision-2 Repayment JE + GL exact", t2)
	if not all([je_has_p, je_has_pf, gl_has_p, gl_has_pf]):
		errors.append(f"FM-Precision-2: JE/GL amount mismatch {t2}")

	# FM-Precision-3 — migrate + schema unchanged at 30,9
	frappe.db.commit()
	frappe.db.close()
	lock_path = frappe.get_site_path("locks", "bench_migrate.lock")
	if os.path.exists(lock_path):
		os.remove(lock_path)
	migrate_proc = subprocess.run(
		["bench", "--site", "development.localhost", "migrate"],
		cwd="/workspace/development/frappe-bench",
		capture_output=True,
		text=True,
		timeout=3600,
	)
	frappe.init(site="development.localhost")
	frappe.connect()
	frappe.set_user("Administrator")
	schema_after = _schema_snapshot()
	bad_cols = [
		r
		for r in schema_after
		if (r.get("NUMERIC_PRECISION") or 0) < TARGET_PRECISION
		or (r.get("NUMERIC_SCALE") or 0) < TARGET_SCALE
	]
	t3 = {
		"migrate_exit_code": migrate_proc.returncode,
		"migrate_stderr_tail": (migrate_proc.stderr or "")[-2000:],
		"migrate_stdout_tail": (migrate_proc.stdout or "")[-2000:],
		"schema_decimal_columns": schema_after,
		"columns_below_target": bad_cols,
	}
	results["tests"]["FM-Precision-3"] = t3
	_log("FM-Precision-3 migrate + INFORMATION_SCHEMA", t3)
	if migrate_proc.returncode != 0:
		errors.append(f"FM-Precision-3: migrate failed exit {migrate_proc.returncode}")
	if bad_cols:
		errors.append(f"FM-Precision-3: columns below DECIMAL(30,9): {bad_cols}")

	# Property setters evidence
	ps = frappe.get_all(
		"Property Setter",
		filters={
			"doc_type": ("in", ["Facility", "Facility Repayment", "Facility Repayment Schedule"]),
			"property": "length",
		},
		fields=["doc_type", "field_name", "value"],
		order_by="doc_type, field_name",
	)
	results["property_setters_length"] = ps
	_log("Property Setters (length=30)", ps)

	results["errors"] = errors
	results["passed"] = not errors
	_log("SUMMARY", results)
	if errors:
		frappe.throw("Facility precision E2E failed:\n" + "\n".join(errors))
	print("\nFacility Management precision E2E FM-Precision-1..3 PASSED")
	return results
