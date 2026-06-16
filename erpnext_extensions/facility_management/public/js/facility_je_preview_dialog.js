// Copyright (c) 2026, ERPNext Extensions contributors

frappe.provide("erpnext_extensions.facility_management.je_preview");

erpnext_extensions.facility_management.je_preview.show_facility_je_preview_dialog = function (
	data,
	title
) {
	const payload = data || {};
	if (payload.exc || payload._server_messages) {
		return;
	}
	if (payload.error) {
		frappe.msgprint({ title: __("Preview failed"), message: payload.error, indicator: "red" });
		return;
	}
	if (!payload.balanced) {
		frappe.msgprint({
			title: __("Not balanced"),
			message: __("Total debit {0} ≠ total credit {1}", [payload.total_debit, payload.total_credit]),
			indicator: "orange",
		});
	}
	const rows = (payload.rows || [])
		.map(
			(row) => `<tr>
			<td>${frappe.utils.escape_html(row.row_label || "")}</td>
			<td>${frappe.utils.escape_html(row.account || "")}</td>
			<td class="text-right">${row.debit || ""}</td>
			<td class="text-right">${row.credit || ""}</td>
			<td>${frappe.utils.escape_html(row.facility || "")}</td>
			<td>${frappe.utils.escape_html(row.department || "")}</td>
			<td>${frappe.utils.escape_html(row.cost_center || "")}</td>
			<td>${frappe.utils.escape_html(row.bank_dimension || "")}</td>
			<td>${frappe.utils.escape_html(row.bank_account_dimension || "")}</td>
			<td>${frappe.utils.escape_html(row.user_remark || "")}</td>
		</tr>`
		)
		.join("");
	const dialogTitle =
		title ||
		__("Journal Entry Preview") + ` (${payload.voucher_type || "Bank Entry"})`;
	const d = new frappe.ui.Dialog({
		title: dialogTitle,
		size: "extra-large",
	});
	d.$body.html(`
		<div class="mb-2 text-muted small">
			<div><strong>${__("Voucher Type")}:</strong> ${frappe.utils.escape_html(payload.voucher_type || "")}</div>
			<div><strong>${__("Posting Date")}:</strong> ${frappe.utils.escape_html(payload.posting_date || "")}</div>
			<div><strong>${__("Remarks")}:</strong> ${frappe.utils.escape_html(payload.remarks || "")}</div>
		</div>
		<div class="table-responsive">
			<table class="table table-bordered table-sm">
				<thead><tr>
					<th>${__("Row")}</th><th>${__("Account")}</th><th>${__("Debit")}</th><th>${__("Credit")}</th>
					<th>${__("Facility")}</th><th>${__("Department")}</th><th>${__("Cost Center")}</th>
					<th>${__("Bank Dimension")}</th><th>${__("Bank Account Dimension")}</th><th>${__("Row Description")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
				<tfoot><tr>
					<th colspan="2">${__("Totals")}</th>
					<th class="text-right">${payload.total_debit}</th>
					<th class="text-right">${payload.total_credit}</th>
					<th colspan="6"></th>
				</tr></tfoot>
			</table>
		</div>
	`);
	d.show();
};
