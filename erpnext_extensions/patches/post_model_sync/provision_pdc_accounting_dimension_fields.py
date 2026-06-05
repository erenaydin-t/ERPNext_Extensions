"""Ensure Accounting Dimension custom fields exist on Post Dated Cheque (idempotent)."""

from erpnext_extensions.cheque_management.pdc_accounting_dimensions import (
	provision_post_dated_cheque_accounting_dimensions,
)


def execute():
	provision_post_dated_cheque_accounting_dimensions()
