// Copyright (c) 2025, Farbod Siyahpoosh and contributors
// For license information, please see license.txt

frappe.ui.form.on("Post Dated Cheque", {
	refresh: function (frm) {},

	party: function (frm) {
		set_default_party_accounts(frm);
	},
	party_type: function (frm) {
		set_default_party_accounts(frm);
	},
	cheque_direction: function (frm) {
		set_default_party_accounts(frm);
	},
	company: function (frm) {
		set_default_party_accounts(frm);
	},
});

function set_default_party_accounts(frm) {
	if (!frm.doc.company || !frm.doc.party_type || !frm.doc.party || !frm.doc.cheque_direction) {
		return;
	}
	frappe.call({
		method: "erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.get_default_party_accounts",
		args: {
			party_type: frm.doc.party_type,
			party: frm.doc.party,
			company: frm.doc.company,
			cheque_direction: frm.doc.cheque_direction,
		},
		callback: function (r) {
			if (r.message && !r.exc) {
				if (r.message.account_paid_from) {
					frm.set_value("account_paid_from", r.message.account_paid_from);
				}
				if (r.message.account_paid_to) {
					frm.set_value("account_paid_to", r.message.account_paid_to);
				}
			}
		},
	});
}
