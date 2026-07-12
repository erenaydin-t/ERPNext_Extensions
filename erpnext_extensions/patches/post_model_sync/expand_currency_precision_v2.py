# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Re-apply currency / amount column precision expansion (idempotent).

Registered as a new patch so sites with the original patch already in Patch Log
still run this logic once on migrate.
"""

from erpnext_extensions.patches.post_model_sync.expand_currency_precision import (
	execute as expand_currency_precision_execute,
)


def execute():
	expand_currency_precision_execute()
