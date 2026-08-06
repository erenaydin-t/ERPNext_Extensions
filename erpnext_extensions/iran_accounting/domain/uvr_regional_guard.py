# Copyright (c) 2026, ERPNext Extensions contributors
"""Upgrade-guarded IRR binding for update_regional_item_valuation_rate (end of UVR).

Fail-closed twin of riv_rate_guard:
1. Explicit ERPNext/Frappe major.minor allow-list (no wildcards).
2. Fingerprint BuyingController.update_valuation_rate + vanilla
   update_regional_item_valuation_rate (signature + normalized AST/source).
3. Assert UVR still invokes update_regional_item_valuation_rate (token + AST).
4. Monkey patch installs only after every check passes.

Uses the same normalize_function_source strategy as riv_rate_guard.
No accounting / rounding / Class A·B changes — upgrade safety only.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import textwrap
from typing import Any

import frappe
from frappe import _

from erpnext_extensions.iran_accounting.domain.riv_rate_guard import (
	major_minor,
	normalize_function_source,
	source_sha256,
)

# ---------------------------------------------------------------------------
# Explicit support allow-list (major.minor). Unknown versions → BLOCK.
# Fingerprints measured on ERPNext 16.30.0 / Frappe 16.29.0 (also valid for
# 16.29.x when UVR / regional stub bodies are identical).
# ---------------------------------------------------------------------------

_SUPPORTED_ERPNEXT_MINOR = frozenset({"16.29", "16.30"})
_SUPPORTED_FRAPPE_MINOR = frozenset({"16.29", "16.30"})

_FN_FINGERPRINTS = {
	"update_valuation_rate": {
		"signature": "(self, reset_outgoing_rate=True)",
		"source_sha256": "5e898d6e97ff7b39f56c0f710b83b9e69a7c0ae08a97dae10eaf32f0c12c7bac",
		"must_contain": ("update_regional_item_valuation_rate",),
	},
	"update_regional_item_valuation_rate": {
		"signature": "(doc)",
		"source_sha256": "0148e05ecb21260fd810be4fd884e83947cc1df9899ced741c6b979acac065e4",
		"must_contain": ("allow_regional",),
	},
}


def _version_pair() -> tuple[str, str]:
	import erpnext

	return major_minor(getattr(erpnext, "__version__", "")), major_minor(
		getattr(frappe, "__version__", "")
	)


def _resolve_vanilla_regional(buying_controller):
	"""Return ERPNext's regional stub (decorated), never the Iran patch."""
	saved = getattr(buying_controller, "_iran_original_regional_valuation_rate", None)
	if saved is not None:
		return saved
	live = buying_controller.update_regional_item_valuation_rate
	mod = getattr(live, "__module__", "") or ""
	if mod.startswith("erpnext_extensions"):
		raise RuntimeError(
			_(
				"IRR Upgrade Guard: update_regional_item_valuation_rate is already replaced "
				"and no vanilla original was saved — UVR integerization patch not installed."
			)
		)
	return live


def _uvr_calls_regional_hook(fn) -> bool:
	"""True if normalized AST contains a Call to update_regional_item_valuation_rate."""
	src = textwrap.dedent(inspect.getsource(fn))
	tree = ast.parse(src)
	for node in ast.walk(tree):
		if not isinstance(node, ast.Call):
			continue
		func = node.func
		if isinstance(func, ast.Name) and func.id == "update_regional_item_valuation_rate":
			return True
		if isinstance(func, ast.Attribute) and func.attr == "update_regional_item_valuation_rate":
			return True
	return False


def collect_fingerprint_report() -> dict[str, Any]:
	"""Inspect live vanilla UVR / regional symbols for diagnostics."""
	import erpnext.controllers.buying_controller as buying_controller
	from erpnext.controllers.buying_controller import BuyingController

	uvr = BuyingController.update_valuation_rate
	regional = _resolve_vanilla_regional(buying_controller)
	erp_mm, fr_mm = _version_pair()
	methods = {}
	for name, fn in (
		("update_valuation_rate", uvr),
		("update_regional_item_valuation_rate", regional),
	):
		norm = normalize_function_source(fn)
		methods[name] = {
			"signature": str(inspect.signature(fn)),
			"source_sha256": hashlib.sha256(norm.encode()).hexdigest(),
			"normalized_source": norm,
		}
	methods["update_valuation_rate"]["calls_regional_hook"] = _uvr_calls_regional_hook(uvr)
	return {
		"erpnext_major_minor": erp_mm,
		"frappe_major_minor": fr_mm,
		"methods": methods,
	}


def assert_erpnext_uvr_regional_patch_supported() -> None:
	"""Fail-closed upgrade guard. Raises if versions/fingerprints are unsupported."""
	import erpnext
	import erpnext.controllers.buying_controller as buying_controller
	from erpnext.controllers.buying_controller import BuyingController

	erp_ver = getattr(erpnext, "__version__", "")
	fr_ver = getattr(frappe, "__version__", "")
	erp_mm, fr_mm = major_minor(erp_ver), major_minor(fr_ver)

	if erp_mm not in _SUPPORTED_ERPNEXT_MINOR:
		raise RuntimeError(
			_(
				"IRR Upgrade Guard: update_valuation_rate fingerprint unsupported on ERPNext {0}. "
				"UVR integerization patch not installed. Allow-list: {1}."
			).format(erp_ver, ", ".join(sorted(_SUPPORTED_ERPNEXT_MINOR)))
		)
	if fr_mm not in _SUPPORTED_FRAPPE_MINOR:
		raise RuntimeError(
			_(
				"IRR Upgrade Guard: Frappe {0} is not on the explicit support allow-list ({1}). "
				"UVR integerization patch not installed."
			).format(fr_ver, ", ".join(sorted(_SUPPORTED_FRAPPE_MINOR)))
		)

	if not hasattr(BuyingController, "update_valuation_rate"):
		raise RuntimeError(
			_(
				"IRR Upgrade Guard: BuyingController.update_valuation_rate missing on ERPNext {0}. "
				"UVR integerization patch not installed."
			).format(erp_ver)
		)
	if not hasattr(buying_controller, "update_regional_item_valuation_rate"):
		raise RuntimeError(
			_(
				"IRR Upgrade Guard: update_regional_item_valuation_rate missing on ERPNext {0}. "
				"UVR integerization patch not installed."
			).format(erp_ver)
		)

	uvr = BuyingController.update_valuation_rate
	regional = _resolve_vanilla_regional(buying_controller)
	targets = {
		"update_valuation_rate": uvr,
		"update_regional_item_valuation_rate": regional,
	}

	errors: list[str] = []
	for name, expected in _FN_FINGERPRINTS.items():
		fn = targets[name]
		sig = str(inspect.signature(fn))
		if sig != expected["signature"]:
			errors.append(f"{name}: signature {sig!r} != {expected['signature']!r}")
			continue
		norm = normalize_function_source(fn)
		digest = hashlib.sha256(norm.encode()).hexdigest()
		if digest != expected["source_sha256"]:
			errors.append(
				f"{name}: source fingerprint {digest} != allow-list {expected['source_sha256']}"
			)
		for token in expected.get("must_contain") or ():
			if token not in norm:
				errors.append(f"{name}: normalized source missing required token {token!r}")

	if not _uvr_calls_regional_hook(uvr):
		errors.append(
			"update_valuation_rate: AST does not call update_regional_item_valuation_rate "
			"(regional hook removed or bypassed)"
		)

	if errors:
		raise RuntimeError(
			_(
				"IRR Upgrade Guard: update_valuation_rate fingerprint unsupported on ERPNext {0}. "
				"UVR integerization patch not installed.\n{1}"
			).format(erp_ver, "\n".join(errors))
		)


# Re-export for diagnostics / tests that mirror riv_rate_guard API surface.
__all__ = [
	"_FN_FINGERPRINTS",
	"_SUPPORTED_ERPNEXT_MINOR",
	"_SUPPORTED_FRAPPE_MINOR",
	"assert_erpnext_uvr_regional_patch_supported",
	"collect_fingerprint_report",
	"major_minor",
	"normalize_function_source",
	"source_sha256",
]
