frappe.provide("erpnext_extensions.account_explorer");

/**
 * Print GL controller bridge — keeps Account Explorer surgery to includes only.
 * Installs after Controller is defined (include this file at the end of account_explorer.js).
 */
(function () {
	const ns = erpnext_extensions.account_explorer;
	const Proto = ns.Controller && ns.Controller.prototype;
	if (!Proto || Proto.__voucher_gl_print_bridge_installed) {
		return;
	}
	Proto.__voucher_gl_print_bridge_installed = true;

	const PRINT_GL_SPEC = {
		key: "print_gl",
		label: __("Print GL"),
		title: __("Print every GL Entry row for this voucher"),
	};

	function print_gl_enabled(controller) {
		return controller.metadata?.show_print_gl !== 0;
	}

	function print_gl_button_html() {
		return `<span class="ae-voucher-action-sep" aria-hidden="true">|</span><button type="button" class="btn btn-xs btn-default ae-voucher-action ae-voucher-action--print_gl" data-action="print_gl" title="${frappe.utils.escape_html(
			PRINT_GL_SPEC.title
		)}">${frappe.utils.escape_html(PRINT_GL_SPEC.label)}</button>`;
	}

	function inject_print_gl_into_actions_html(html) {
		if (!html || html.includes("ae-voucher-action--print_gl")) {
			return html;
		}
		const btn = print_gl_button_html();
		// Prefer after Print Voucher / Print action.
		const after_print = html.replace(
			/(class="[^"]*ae-voucher-action--print[^"]*"[^>]*>[\s\S]*?<\/button>)/,
			`$1${btn}`
		);
		if (after_print !== html) {
			return after_print;
		}
		// Else before Copy Link.
		const before_copy = html.replace(
			/(<span[^>]*ae-voucher-action-sep[^>]*>\|<\/span><button[^>]*ae-voucher-action--copy)/,
			`${btn}$1`
		);
		if (before_copy !== html) {
			return before_copy;
		}
		// Else before closing actions container.
		return html.replace(/<\/div>\s*$/, `${btn}</div>`);
	}

	Proto.open_voucher_gl_print = function open_voucher_gl_print(opts = {}) {
		return erpnext_extensions.account_explorer.VoucherGLPrint.open(opts);
	};

	Proto.navigate_print_gl = function navigate_print_gl(row) {
		if (this.metadata?.show_print_gl === 0) {
			frappe.msgprint(__("Print GL is disabled in Iran Accounting Settings."));
			return;
		}
		const profile_scale = this.metadata?.voucher_gl_amount_scale || null;
		this.open_voucher_gl_print({
			company: this.document_scope?.company,
			voucher_type: row?.voucher_type,
			voucher_no: row?.voucher_no,
			layout: this.metadata?.voucher_gl_layout || null,
			print_format: this.metadata?.voucher_gl_print_format || null,
			language: frappe.boot?.lang || null,
			finance_book: this.document_scope?.finance_book || null,
			include_opening_entries: cint(this.document_scope?.status?.include_opening_entries ?? 1),
			include_cancelled_entries: cint(this.document_scope?.status?.include_cancelled_entries ?? 0),
			rtl: this.is_page_rtl?.() || document.dir === "rtl",
			// Stable enum only — current Account Explorer Numbers preference.
			user_amount_scale: this.number_format_mode || "auto",
			// Print profile Amount Scale (Use Default → fall through to user pref).
			amount_scale: profile_scale,
		});
	};

	const original_build_html = Proto.build_voucher_actions_html;
	if (typeof original_build_html === "function") {
		Proto.build_voucher_actions_html = function build_voucher_actions_html_with_print_gl(row) {
			const html = original_build_html.call(this, row);
			if (!print_gl_enabled(this)) {
				return html;
			}
			return inject_print_gl_into_actions_html(html);
		};
	}

	const original_handle = Proto.handle_voucher_row_action;
	if (typeof original_handle === "function") {
		Proto.handle_voucher_row_action = function handle_voucher_row_action_with_print_gl(row, action) {
			if (action === "print_gl") {
				this.navigate_print_gl(row);
				return;
			}
			return original_handle.call(this, row, action);
		};
	}

	const original_render_bar = Proto.render_voucher_action_bar;
	if (typeof original_render_bar === "function") {
		Proto.render_voucher_action_bar = function render_voucher_action_bar_with_print_gl(
			$container,
			row,
			options = {}
		) {
			original_render_bar.call(this, $container, row, options);
			if (!print_gl_enabled(this) || !$container || !$container.length) {
				return;
			}
			if ($container.find(".ae-voucher-action--print_gl").length) {
				return;
			}
			const $btn = $('<button type="button" class="btn btn-xs btn-default ae-voucher-action">')
				.addClass("ae-voucher-action--print_gl")
				.attr("data-action", "print_gl")
				.text(PRINT_GL_SPEC.label)
				.attr("title", PRINT_GL_SPEC.title)
				.on("click", (e) => {
					e.stopPropagation();
					this.navigate_print_gl(row);
				});
			const $sep = $('<span class="ae-voucher-action-sep" aria-hidden="true">|</span>');
			const $print = $container.find(".ae-voucher-action--print").first();
			const $copy = $container.find(".ae-voucher-action--copy").first();
			if ($print.length) {
				$sep.insertAfter($print);
				$btn.insertAfter($sep);
			} else if ($copy.length) {
				$btn.insertBefore($copy);
				$sep.insertBefore($btn);
			} else {
				$container.append($sep).append($btn);
			}
		};
	}
})();
