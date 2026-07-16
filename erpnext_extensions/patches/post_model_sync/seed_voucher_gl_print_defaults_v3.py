# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Re-apply Voucher GL Print defaults (versioned marker on DocType field)."""

from erpnext_extensions.patches.post_model_sync.seed_voucher_gl_layout_settings import (
	apply_voucher_gl_print_defaults,
)


def execute():
	apply_voucher_gl_print_defaults(force=False)
