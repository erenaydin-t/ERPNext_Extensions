# Copyright (c) 2026, ERPNext Extensions contributors
"""Runtime bootstrap: worker guard + monkey patches (never at import time)."""

from __future__ import annotations


def apply() -> None:
	from erpnext_extensions.iran_accounting.worker.guard import ensure_runtime_ready

	ensure_runtime_ready()
	from erpnext_extensions.iran_accounting.integration.monkey_patches import apply_monkey_patches

	apply_monkey_patches()
