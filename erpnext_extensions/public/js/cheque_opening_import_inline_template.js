// Safe, idempotent inline template action renderer for Cheque Opening Import.
// Loaded via hooks.doctype_js (separate from the auto-loaded doctype JS file).

(function () {
	"use strict";

	// Namespace so repeated loads don't redeclare top-level const/let.
	window.erpnext_extensions = window.erpnext_extensions || {};
	window.erpnext_extensions.cheque_opening_import =
		window.erpnext_extensions.cheque_opening_import || {};

	const ns = window.erpnext_extensions.cheque_opening_import;

	ns.download_template_url = function () {
		const method =
			"erpnext_extensions.cheque_management.doctype.cheque_opening_import.cheque_opening_import.download_import_template";
		// `frappe.utils.get_full_url` is not available client-side on some versions.
		// Relative URL is sufficient (session cookie is sent automatically).
		return `/api/method/${method}`;
	};

	ns.render_inline_template_actions = function (frm) {
		try {
			const wrapper = frm?.fields_dict?.import_template_actions_html?.$wrapper;
			if (!wrapper || !wrapper.length) return;

			wrapper.html(`
				<div class="coi-template-actions" style="margin-top: 8px;">
					<button class="btn btn-default btn-sm" type="button">
						${__("Download Template")}
					</button>
				</div>
			`);

			wrapper.find("button").on("click", () => {
				const url = ns.download_template_url();
				// Prefer same-tab navigation so popup blockers don't break downloads.
				try {
					window.location.href = url;
				} catch (e) {
					console.error("Cheque Opening Import: download navigation failed", e);
					frappe.msgprint({
						title: __("Download Template"),
						message: __(
							'Could not start the download automatically. <a href="{0}" target="_blank" rel="noopener noreferrer">Click here</a> to download the template.',
							[url]
						),
						indicator: "orange",
					});
				}
			});
		} catch (e) {
			// Never break form rendering.
			console.error("Cheque Opening Import: inline template render failed", e);
		}
	};
})();
