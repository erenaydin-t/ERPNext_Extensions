# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Keep Job Card process loss scoped to its own operation.

Upstream ``StockEntry.set_process_loss_qty``
(``erpnext/stock/doctype/stock_entry/stock_entry.py``) derives the process loss
of a Manufacture / Repack entry from the parent Work Order alone::

    data = frappe.get_all(
        "Work Order Operation",
        filters={"parent": self.work_order},
        fields=[{"MAX": "process_loss_qty", "as": "process_loss_qty"}],
    )

The query is filtered by Work Order only and takes the **maximum** across every
operation row, so a loss recorded on one operation is re-applied to all the
other operations of the same routing.

That holds for the legacy model — one Manufacture entry per Work Order, loss
recorded on a single operation — but breaks the v16 semi-finished goods flow
(``track_semi_finished_goods``), where every operation posts its own Manufacture
entry from its Job Card. ``JobCard.make_stock_entry_for_semi_fg_item`` already
passes the correct, card-scoped figure (that Job Card's ``process_loss_qty``,
net of what its earlier entries consumed) and ``set_process_loss_qty`` then
overwrites it during ``validate()``. ``validate_fg_completed_qty``, later in the
same ``validate()``, sees ``fg_completed_qty != fg_qty + process_loss_qty`` and
blocks the entry with::

	Since there is a process loss of {n} units for the finished good {item},
	you should reduce the quantity by {n} units for the finished good {item}
	in the Items Table.

Concretely: on a Work Order whose first operation lost 790 units, the second
operation cannot post its Manufacture entry — those 790 units are re-applied to
a Job Card whose own process loss is 0.

This patch keeps upstream behaviour verbatim for Work Order level entries and
only skips the Work-Order-wide reset when the entry belongs to a Job Card, where
``process_loss_qty`` is already scoped to that card's operation.

The reset is skipped rather than re-filtered by ``operation_id`` on purpose:
``Work Order Operation.process_loss_qty`` aggregates every Job Card of the
operation (``JobCard.get_current_operation_data``), so an operation run over
several Job Cards would still over-apply the loss.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


def apply_patch() -> None:
	from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

	if getattr(StockEntry, "_job_card_process_loss_patched", None):
		# Idempotent: apply_monkey_patches may run on every request.
		return

	StockEntry.set_process_loss_qty = set_process_loss_qty
	StockEntry._job_card_process_loss_patched = True


def set_process_loss_qty(self):
	"""Upstream ERPNext v16 logic, minus the Work-Order-wide reset on Job Card entries."""
	if self.purpose not in ("Manufacture", "Repack"):
		return

	precision = self.precision("process_loss_qty")

	# Job Card entries already carry the process loss of their own operation,
	# set by JobCard.make_stock_entry_for_semi_fg_item.
	if self.work_order and not self.job_card:
		data = frappe.get_all(
			"Work Order Operation",
			filters={"parent": self.work_order},
			fields=[{"MAX": "process_loss_qty", "as": "process_loss_qty"}],
		)

		if data and data[0].process_loss_qty:
			process_loss_qty = data[0].process_loss_qty
			if flt(self.process_loss_qty, precision) != flt(process_loss_qty, precision):
				self.process_loss_qty = flt(process_loss_qty, precision)

				frappe.msgprint(
					_("The Process Loss Qty has reset as per job cards Process Loss Qty"), alert=True
				)

	if not self.process_loss_percentage and not self.process_loss_qty:
		self.process_loss_percentage = frappe.get_cached_value("BOM", self.bom_no, "process_loss_percentage")

	if self.process_loss_percentage and not self.process_loss_qty:
		self.process_loss_qty = flt((flt(self.fg_completed_qty) * flt(self.process_loss_percentage)) / 100)
	elif self.process_loss_qty and self.fg_completed_qty:
		self.process_loss_percentage = flt((flt(self.process_loss_qty) / flt(self.fg_completed_qty)) * 100)
