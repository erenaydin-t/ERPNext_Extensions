frappe.provide("erpnext_extensions.account_explorer");

/**
 * Popup-safe one-click Voucher GL Print.
 * Opens the blank window synchronously on the user gesture, then fills it
 * after the async render call. Never opens a second window after await.
 */
erpnext_extensions.account_explorer.VoucherGLPrint = {
	API_METHOD: "erpnext_extensions.iran_accounting.account_explorer.render_voucher_gl_print",
	REPORT_NAME: "Voucher GL Print",
	READY_FLAG: "__voucher_gl_print_ready",
	READY_EVENT: "voucher-gl-print-ready",
	/** Fixed policy for this release: open preview only (no auto window.print). */
	BEHAVIOR: "open_preview",

	open(opts = {}) {
		const normalized = this.normalize_opts(opts);
		if (!normalized.company || !normalized.voucher_type || !normalized.voucher_no) {
			frappe.msgprint(__("Voucher type and voucher number are required for Print GL."));
			return { mode: "invalid", window: null };
		}

		// Synchronous open while still in the click gesture stack.
		const print_window = window.open("", "_blank");
		if (!print_window) {
			this.show_fallback(normalized);
			return { mode: "fallback", window: null };
		}

		try {
			// Soften opener coupling; blank document has no referrer policy hooks here.
			print_window.opener = null;
		} catch (error) {
			/* noop */
		}

		this.write_loading_document(print_window, normalized);
		this.fetch_and_fill(print_window, normalized);
		return { mode: "popup", window: print_window };
	},

	normalize_opts(opts) {
		const scale = this.normalize_amount_scale_enum(
			opts.user_amount_scale || opts.amount_scale_preference || null
		);
		const profile_scale = this.normalize_amount_scale_enum(opts.amount_scale || null, true);
		return {
			company: opts.company || null,
			voucher_type: opts.voucher_type || null,
			voucher_no: opts.voucher_no || null,
			layout: opts.layout || null,
			letterhead: opts.letterhead || null,
			language: opts.language || frappe.boot?.lang || null,
			print_format: opts.print_format || null,
			orientation: opts.orientation || null,
			finance_book: opts.finance_book || null,
			include_opening_entries: cint(opts.include_opening_entries ?? 1),
			include_cancelled_entries: cint(opts.include_cancelled_entries ?? 0),
			user_amount_scale: scale,
			amount_scale: profile_scale,
			auto_print: !!opts.auto_print && this.BEHAVIOR === "open_preview_and_print",
			api_method: opts.api_method || this.API_METHOD,
			report_name: opts.report_name || this.REPORT_NAME,
			rtl: !!(opts.rtl ?? (frappe.boot?.lang_direction === "rtl" || document.dir === "rtl")),
		};
	},

	/**
	 * Pass stable enum values only (never localized labels).
	 * @param {string|null} value
	 * @param {boolean} allow_use_default — include "Use Default" for print profile
	 */
	normalize_amount_scale_enum(value, allow_use_default = false) {
		if (value === null || value === undefined || value === "") {
			return null;
		}
		const raw = String(value).trim();
		const key = raw.toLowerCase().replace(/[\s-]+/g, "_");
		const map = {
			raw: "Raw",
			normal: "Raw",
			auto: "Auto",
			thousands: "Thousands",
			millions: "Millions",
			billions: "Billions",
			trillions: "Trillions",
			use_default: "Use Default",
			default: "Use Default",
		};
		const resolved = map[key] || null;
		if (!resolved) {
			return null;
		}
		if (resolved === "Use Default" && !allow_use_default) {
			return null;
		}
		return resolved;
	},

	escape_html(value) {
		return frappe.utils.escape_html(String(value ?? ""));
	},

	build_filters(opts) {
		const filters = {
			company: opts.company,
			voucher_type: opts.voucher_type,
			voucher_no: opts.voucher_no,
			include_opening_entries: opts.include_opening_entries,
			include_cancelled_entries: opts.include_cancelled_entries,
			finance_book: opts.finance_book || null,
		};
		if (opts.print_format) {
			filters.print_format = opts.print_format;
		}
		if (opts.layout) {
			filters.layout = opts.layout;
		}
		if (opts.letterhead) {
			filters.letterhead = opts.letterhead;
		}
		if (opts.language) {
			filters.language = opts.language;
		}
		if (opts.orientation) {
			filters.orientation = opts.orientation;
		}
		if (opts.user_amount_scale) {
			filters.user_amount_scale = opts.user_amount_scale;
		}
		if (opts.amount_scale && opts.amount_scale !== "Use Default") {
			filters.amount_scale = opts.amount_scale;
		}
		return filters;
	},

	/**
	 * Permission-protected report route — identity + print options only (no HTML / GL rows).
	 */
	build_report_url(opts) {
		const filters = this.build_filters(opts);
		const params = new URLSearchParams();
		Object.entries(filters).forEach(([key, value]) => {
			if (value === null || value === undefined || value === "") {
				return;
			}
			params.set(key, String(value));
		});
		const path = `/app/query-report/${encodeURIComponent(opts.report_name)}?${params.toString()}`;
		return frappe.urllib.get_full_url(path);
	},

	write_document(print_window, html) {
		print_window.document.open();
		print_window.document.write(html);
		print_window.document.close();
	},

	write_loading_document(print_window, opts) {
		const dir = opts.rtl ? "rtl" : "ltr";
		const voucher_label = this.escape_html(`${opts.voucher_type} ${opts.voucher_no}`);
		const title = this.escape_html(__("Accounting Voucher Package"));
		const module_name = this.escape_html(__("Iran Accounting"));
		const preparing = this.escape_html(__("Preparing document for print…"));
		const step_load = this.escape_html(__("Loading"));
		const step_render = this.escape_html(__("Rendering"));
		const step_ready = this.escape_html(__("Ready"));
		const close_label = this.escape_html(__("Close"));
		this.write_document(
			print_window,
			`<!DOCTYPE html><html lang="${this.escape_html(
				opts.language || "en"
			)}" dir="${dir}"><head><meta charset="utf-8"><title>${title}</title>
<style>
body{font-family:Vazirmatn,IRANSansX,Tahoma,DejaVu Sans,sans-serif;margin:0;padding:48px 24px;background:#edf1f5;color:#182029;direction:${dir};text-align:center}
.sheet{max-width:440px;margin:0 auto;background:#fff;border:2px solid #1a2430;padding:32px 24px 28px}
.brand{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#5c6670;margin-bottom:10px;font-weight:700}
h1{font-size:18px;margin:0 0 8px;font-weight:800}
.voucher{font-size:13px;color:#334e68;margin:0 0 22px;font-weight:600}
.steps{display:flex;justify-content:center;gap:10px;margin:0 0 18px;font-size:11px;color:#5c6670}
.steps span{padding:4px 10px;border:1px solid #c9d0d7;background:#f7f8fa}
.steps .active{border-color:#1a3f5c;color:#1a3f5c;font-weight:700;background:#eef2f6}
.spinner{width:26px;height:26px;border:3px solid #d9e2ec;border-top-color:#1a3f5c;border-radius:50%;margin:0 auto 14px;animation:spin .75s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.status{font-size:13px;margin:0 0 16px}
a{color:#1a3f5c;font-size:12px}
</style></head><body>
<div class="sheet" role="status" aria-live="polite">
<div class="brand">${module_name}</div>
<div class="spinner" aria-hidden="true"></div>
<h1>${title}</h1>
<p class="voucher">${voucher_label}</p>
<div class="steps"><span class="active">${step_load}</span><span>${step_render}</span><span>${step_ready}</span></div>
<p class="status">${preparing}</p>
<p><a href="javascript:window.close()">${close_label}</a></p>
</div>
<script>window.${this.READY_FLAG}=false;</script>
</body></html>`
		);
	},

	write_error_document(print_window, opts, message) {
		if (!print_window || print_window.closed) {
			return;
		}
		const dir = opts.rtl ? "rtl" : "ltr";
		const safe = this.escape_html(message || __("Unable to prepare Print GL."));
		const title = this.escape_html(__("Print GL failed"));
		this.write_document(
			print_window,
			`<!DOCTYPE html><html dir="${dir}"><head><meta charset="utf-8"><title>${title}</title>
<style>body{font-family:Tahoma,sans-serif;padding:32px;direction:${dir};color:#7a1f1f;background:#fff5f5}
.box{max-width:480px;margin:0 auto;border:1px solid #f5c2c0;background:#fff;padding:20px;border-radius:8px}
a{color:#0b6e4f}</style></head><body>
<div class="box"><h1>${title}</h1><p>${safe}</p>
<p><a href="javascript:window.close()">${this.escape_html(__("Close"))}</a></p></div>
</body></html>`
		);
	},

	fetch_and_fill(print_window, opts) {
		const filters = this.build_filters(opts);
		frappe.call({
			method: opts.api_method,
			args: {
				company: opts.company,
				voucher_type: opts.voucher_type,
				voucher_no: opts.voucher_no,
				filters: JSON.stringify(filters),
			},
			callback: (response) => {
				const html = response?.message;
				if (print_window.closed) {
					frappe.show_alert({
						message: __("Print window was closed before Print GL finished."),
						indicator: "orange",
					});
					return;
				}
				if (!html) {
					const message = __("Print GL preview is empty.");
					this.write_error_document(print_window, opts, message);
					frappe.msgprint(message);
					return;
				}
				this.write_document(print_window, html);
				this.await_print_ready(print_window).then((ready) => {
					if (!ready || print_window.closed) {
						return;
					}
					try {
						print_window.focus();
					} catch (error) {
						/* noop */
					}
					if (opts.auto_print) {
						try {
							print_window.print();
						} catch (error) {
							/* preview remains usable */
						}
					}
				});
			},
			error: (response) => {
				const message =
					response?.message ||
					response?._server_messages ||
					__("Unable to prepare Print GL.");
				const text = typeof message === "string" ? message : __("Unable to prepare Print GL.");
				if (!print_window.closed) {
					this.write_error_document(print_window, opts, text);
				}
				frappe.msgprint({
					title: __("Print GL"),
					message: text,
					indicator: "red",
				});
			},
		});
	},

	await_print_ready(print_window) {
		const flag = this.READY_FLAG;
		const event_name = this.READY_EVENT;
		return new Promise((resolve) => {
			const started = Date.now();
			let settled = false;
			const finish = (ok) => {
				if (settled) {
					return;
				}
				settled = true;
				resolve(!!ok);
			};
			try {
				print_window.addEventListener?.(event_name, () => finish(true), { once: true });
			} catch (error) {
				/* noop */
			}
			const tick = () => {
				try {
					if (print_window.closed) {
						finish(false);
						return;
					}
					if (print_window[flag]) {
						const fonts = print_window.document?.fonts?.ready;
						if (fonts?.then) {
							fonts.then(() => finish(true)).catch(() => finish(true));
						} else {
							finish(true);
						}
						return;
					}
					if (print_window.document?.readyState === "complete" && Date.now() - started > 400) {
						// Fallback readiness when template flag is absent.
						finish(true);
						return;
					}
				} catch (error) {
					finish(false);
					return;
				}
				if (Date.now() - started > 20000) {
					finish(true);
					return;
				}
				setTimeout(tick, 50);
			};
			tick();
		});
	},

	open_in_current_tab(opts) {
		const url = this.build_report_url(opts);
		window.location.href = url;
	},

	show_fallback(opts) {
		const url = this.build_report_url(opts);
		const dialog = new frappe.ui.Dialog({
			title: __("Print GL"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p>${__(
						"A print window could not be opened automatically. Choose a fallback:"
					)}</p>
<p class="text-muted">${frappe.utils.escape_html(opts.voucher_type)} ${frappe.utils.escape_html(
						opts.voucher_no
					)}</p>
<p><a class="btn btn-default btn-xs" target="_blank" rel="noopener noreferrer" href="${frappe.utils.escape_html(
						url
					)}">${__("Open Report Link")}</a></p>`,
				},
			],
			primary_action_label: __("Open Print Preview"),
			primary_action: () => {
				dialog.hide();
				const retry = window.open("", "_blank");
				if (!retry) {
					frappe.msgprint(__("Still blocked. Use Open in Current Tab or the report link."));
					return;
				}
				this.write_loading_document(retry, opts);
				this.fetch_and_fill(retry, opts);
			},
			secondary_action_label: __("Open in Current Tab"),
			secondary_action: () => {
				dialog.hide();
				this.open_in_current_tab(opts);
			},
		});
		dialog.show();
		dialog.$wrapper.find(".modal-footer").append(
			$('<button type="button" class="btn btn-default btn-sm">')
				.text(__("Copy Print URL"))
				.on("click", async () => {
					try {
						await navigator.clipboard.writeText(url);
						frappe.show_alert({ message: __("Print URL copied"), indicator: "green" });
					} catch (error) {
						frappe.msgprint(url);
					}
				})
		);
	},
};
