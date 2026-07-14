#!/usr/bin/env python3
"""Read-only production investigation for Stock Entry GL submit failures.

Uses only environment variables (never prints secrets):
  ERP_BASE_URL, ERP_API_KEY, ERP_API_SECRET

Writes sanitized JSON report to path in STE_REPORT_PATH or stdout.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error

# Allow running without bench when only REST fallback is needed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from erpnext_extensions.iran_accounting.stock_gl_consistency.debug_stock_entry_ledger_drift_api import (  # noqa: E402
	_api_get,
	_resource_url,
	debug_stock_entry_ledger_drift_api,
)


def _redact(obj):
	if isinstance(obj, dict):
		return {k: _redact(v) for k, v in obj.items() if k not in ("api_key", "api_secret")}
	if isinstance(obj, list):
		return [_redact(x) for x in obj]
	return obj


def fetch_error_logs(base_url: str, api_key: str, api_secret: str, voucher: str) -> list[dict]:
	out = []
	for term in (voucher, "Incorrect number of General Ledger Entries found"):
		try:
			resp = _api_get(
				base_url,
				api_key,
				api_secret,
				"/api/resource/" + __import__("urllib.parse").quote("Error Log"),
				{
					"fields": json.dumps(["name", "creation", "error", "method"]),
					"filters": json.dumps([["error", "like", f"%{term}%"]]),
					"order_by": "creation desc",
					"limit_page_length": 5,
				},
			)
			for row in resp.get("data") or []:
				out.append(
					{
						"name": row.get("name"),
						"creation": row.get("creation"),
						"method": row.get("method"),
						"error_excerpt": (row.get("error") or "")[:4000],
					}
				)
		except urllib.error.HTTPError:
			pass
	return out


def fetch_stock_entry_summary(base_url: str, api_key: str, api_secret: str, voucher: str) -> dict:
	se = _api_get(
		base_url,
		api_key,
		api_secret,
		_resource_url(base_url, "Stock Entry", voucher).replace(base_url.rstrip("/"), ""),
	)
	data = se.get("data") or se
	wh_seen = set()
	wh_accounts = []
	for row in data.get("items") or []:
		for field in ("s_warehouse", "t_warehouse"):
			wh = row.get(field)
			if not wh or wh in wh_seen:
				continue
			wh_seen.add(wh)
			try:
				wdoc = _api_get(
					base_url,
					api_key,
					api_secret,
					_resource_url(base_url, "Warehouse", wh).replace(base_url.rstrip("/"), ""),
				).get("data")
				acc = (wdoc or {}).get("account")
				acc_meta = None
				if acc:
					acc_meta = _api_get(
						base_url,
						api_key,
						api_secret,
						_resource_url(base_url, "Account", acc).replace(base_url.rstrip("/"), ""),
					).get("data")
				wh_accounts.append(
					{
						"warehouse": wh,
						"company": (wdoc or {}).get("company"),
						"account": acc,
						"disabled": (wdoc or {}).get("disabled"),
						"account_type": (acc_meta or {}).get("account_type"),
						"is_group": (acc_meta or {}).get("is_group"),
					}
				)
			except urllib.error.HTTPError:
				wh_accounts.append({"warehouse": wh, "fetch_error": True})

	items = []
	for row in sorted(data.get("items") or [], key=lambda x: x.get("idx") or 0):
		items.append(
			{
				"name": row.get("name"),
				"idx": row.get("idx"),
				"item_code": row.get("item_code"),
				"qty": row.get("qty"),
				"transfer_qty": row.get("transfer_qty"),
				"conversion_factor": row.get("conversion_factor"),
				"basic_rate": row.get("basic_rate"),
				"basic_amount": row.get("basic_amount"),
				"amount": row.get("amount"),
				"valuation_rate": row.get("valuation_rate"),
				"s_warehouse": row.get("s_warehouse"),
				"t_warehouse": row.get("t_warehouse"),
				"expense_account": row.get("expense_account"),
				"cost_center": row.get("cost_center"),
				"department": row.get("department"),
				"has_batch_no": row.get("has_batch_no"),
				"has_serial_no": row.get("has_serial_no"),
				"serial_and_batch_bundle": row.get("serial_and_batch_bundle"),
			}
		)

	accounts = [w.get("account") for w in wh_accounts if w.get("account")]
	same_account = len(set(accounts)) == 1 and len(accounts) >= 2

	return {
		"name": data.get("name"),
		"docstatus": data.get("docstatus"),
		"workflow_state": data.get("workflow_state"),
		"company": data.get("company"),
		"stock_entry_type": data.get("stock_entry_type"),
		"purpose": data.get("purpose"),
		"posting_date": data.get("posting_date"),
		"posting_time": data.get("posting_time"),
		"add_to_transit": data.get("add_to_transit"),
		"is_additional_transfer_entry": data.get("is_additional_transfer_entry"),
		"total_incoming_value": data.get("total_incoming_value"),
		"total_outgoing_value": data.get("total_outgoing_value"),
		"value_difference": data.get("value_difference"),
		"total_additional_costs": data.get("total_additional_costs"),
		"cost_center": data.get("cost_center"),
		"department": data.get("department"),
		"item_count": len(items),
		"items": items,
		"warehouse_accounts": wh_accounts,
		"source_target_share_same_stock_account": same_account,
	}


def main() -> int:
	voucher = os.environ.get("STE_VOUCHER", "MAT-STE-2026-03077")
	base = os.environ.get("ERP_BASE_URL", "").rstrip("/")
	key = os.environ.get("ERP_API_KEY", "")
	secret = os.environ.get("ERP_API_SECRET", "")
	if not base or not key or not secret:
		print(
			json.dumps(
				{
					"error": "missing_env",
					"required": ["ERP_BASE_URL", "ERP_API_KEY", "ERP_API_SECRET"],
					"voucher": voucher,
				}
			),
			file=sys.stderr,
		)
		return 2

	report = {
		"voucher": voucher,
		"base_url": base,
		"document": fetch_stock_entry_summary(base, key, secret, voucher),
		"drift": debug_stock_entry_ledger_drift_api(base, key, secret, voucher),
		"error_logs": fetch_error_logs(base, key, secret, voucher),
	}
	report = _redact(report)
	out_path = os.environ.get("STE_REPORT_PATH")
	payload = json.dumps(report, indent=2, ensure_ascii=False, default=str)
	if out_path:
		with open(out_path, "w", encoding="utf-8") as f:
			f.write(payload)
	else:
		print(payload)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
