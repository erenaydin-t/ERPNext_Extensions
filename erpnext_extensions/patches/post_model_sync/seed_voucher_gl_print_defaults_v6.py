# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Seed Default Amount Display Scale = Raw (Account Explorer + print fallback) — version 6."""

from erpnext_extensions.patches.post_model_sync.seed_voucher_gl_layout_settings import (
	apply_voucher_gl_print_defaults,
)


def execute():
	apply_voucher_gl_print_defaults(force=False)
