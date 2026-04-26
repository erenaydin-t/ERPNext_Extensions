from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

ALLOCATION_MODE_ADVANCE = "advance"


_ALLOWED_ORDERS = ("Purchase Order", "Sales Order")


def _require_order(dt: str, nm: str) -> None:
	if dt not in _ALLOWED_ORDERS:
		frappe.throw(_("Only Purchase Order or Sales Order are allowed."), title=_("PDC Advance Ceiling"))
	if not nm:
		frappe.throw(_("Order name is required."), title=_("PDC Advance Ceiling"))


def get_order_advance_ceiling_amount(order_doctype: str, order_name: str) -> float:
	"""v1 ceiling baseline: Order.grand_total."""
	_require_order(order_doctype, order_name)
	val = frappe.db.get_value(order_doctype, order_name, "grand_total")
	return flt(val)


def get_order_reserved_advance_pdc_amount(
	order_doctype: str,
	order_name: str,
	*,
	exclude_pdc: str | None = None,
) -> float:
	"""Total *active* advance PDC commitments against an order.

	Active commitment (v1):
	- PDC allocation_mode = advance
	- PDC docstatus != 2 (not cancelled)
	- PDC instrument_dead = 0
	- Allocation rows reference the order (PO/SO)
	- Includes Draft + Submitted PDCs (draft reserves capacity)
	"""
	_require_order(order_doctype, order_name)
	excl = (exclude_pdc or "").strip() or None

	filters = ""
	params: list = [ALLOCATION_MODE_ADVANCE, order_doctype, order_name, ALLOCATION_MODE_ADVANCE]
	if excl:
		filters = " AND p.name != %s"
		params.append(excl)

	row = frappe.db.sql(
		f"""
		SELECT SUM(COALESCE(a.amount, 0)) AS amt
		FROM `tabPDC Allocation` a
		INNER JOIN `tabPost Dated Cheque` p
		  ON p.name = a.parent
		 AND a.parenttype = 'Post Dated Cheque'
		WHERE a.allocation_mode = %s
		  AND a.reference_doctype = %s
		  AND a.reference_name = %s
		  AND p.allocation_mode = %s
		  AND COALESCE(p.docstatus, 0) != 2
		  AND COALESCE(p.instrument_dead, 0) = 0
		  {filters}
		""",
		tuple(params),
		as_dict=True,
	)
	return flt((row[0] or {}).get("amt")) if row else 0.0


def get_order_remaining_advance_capacity(
	order_doctype: str,
	order_name: str,
	*,
	exclude_pdc: str | None = None,
) -> float:
	ceiling = get_order_advance_ceiling_amount(order_doctype, order_name)
	used = get_order_reserved_advance_pdc_amount(order_doctype, order_name, exclude_pdc=exclude_pdc)
	return flt(max(0.0, flt(ceiling) - flt(used)))


__all__ = [
	"get_order_advance_ceiling_amount",
	"get_order_reserved_advance_pdc_amount",
	"get_order_remaining_advance_capacity",
]

