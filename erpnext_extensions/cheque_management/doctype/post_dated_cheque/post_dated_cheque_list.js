frappe.listview_settings["Post Dated Cheque"] = {
	get_indicator(doc) {
		const ws = (doc.workflow_state || "").trim();
		const cs = (doc.cheque_status || "").trim();
		const state = ws || cs;

		const red = ["Bounced", "Returned", "Returned to Customer", "Returned from Payee"].includes(
			state
		);
		const green = ["Cleared"].includes(state);
		const orange = ["Sent to Bank", "In Clearing"].includes(state) || cs === "In Clearing";
		const blue = ["Registered", "Issued"].includes(state);

		if (green) return [__("Cleared"), "green", `cheque_status,=,Cleared`];
		if (red) return [__(state), "red", [`cheque_status,=,${state}`, `workflow_state,=,${state}`]];
		if (orange) return [__("In Clearing"), "orange", "cheque_status,=,In Clearing"];
		if (blue) return [__(state), "blue", `workflow_state,=,${state}`];
		if ((ws || cs) === "Draft") return [__("Draft"), "gray", "workflow_state,=,Draft"];
		return [__(ws || cs || "—"), "gray", ""];
	},

	onload(listview) {
		const dt = frappe.datetime;

		const set_due_range = (from, to) => {
			listview.filter_area.clear();
			if (from) listview.filter_area.add(["Post Dated Cheque", "cheque_due_date", ">=", from]);
			if (to) listview.filter_area.add(["Post Dated Cheque", "cheque_due_date", "<=", to]);
			listview.refresh();
		};

		listview.page.add_menu_item(__("Due Today"), () => {
			const d = dt.get_today();
			set_due_range(d, d);
		});

		listview.page.add_menu_item(__("Due This Week"), () => {
			set_due_range(dt.week_start(), dt.week_end());
		});

		listview.page.add_menu_item(__("Overdue"), () => {
			listview.filter_area.clear();
			listview.filter_area.add(["Post Dated Cheque", "cheque_due_date", "<", dt.get_today()]);
			listview.filter_area.add(["Post Dated Cheque", "cheque_status", "!=", "Cleared"]);
			listview.refresh();
		});

		listview.page.add_menu_item(__("Near Due (next 7 days)"), () => {
			set_due_range(dt.get_today(), dt.add_days(dt.get_today(), 7));
		});

		listview.page.add_menu_item(__("Cleared"), () => {
			listview.filter_area.clear();
			listview.filter_area.add(["Post Dated Cheque", "cheque_status", "=", "Cleared"]);
			listview.refresh();
		});

		listview.page.add_menu_item(__("Bounced"), () => {
			listview.filter_area.clear();
			listview.filter_area.add(["Post Dated Cheque", "cheque_status", "=", "Bounced"]);
			listview.refresh();
		});

		listview.page.add_menu_item(__("In Clearing"), () => {
			listview.filter_area.clear();
			listview.filter_area.add(["Post Dated Cheque", "cheque_status", "=", "In Clearing"]);
			listview.refresh();
		});

		listview.page.add_menu_item(__("At Bank"), () => {
			listview.filter_area.clear();
			listview.filter_area.add(["Post Dated Cheque", "is_at_bank", "=", 1]);
			listview.refresh();
		});

		// Lightweight operational counts (no heavy dashboard).
		const refresh_counts = async () => {
			try {
				const [at_bank, overdue_recv] = await Promise.all([
					frappe.db.count("Post Dated Cheque", {
						cheque_direction: "Receivable",
						is_at_bank: 1,
					}),
					frappe.db.count("Post Dated Cheque", {
						cheque_direction: "Receivable",
						cheque_due_date: ["<", dt.get_today()],
						cheque_status: ["!=", "Cleared"],
					}),
				]);
				listview.page.set_indicator(
					__("Receivable At Bank: {0} · Overdue Receivable: {1}", [at_bank || 0, overdue_recv || 0]),
					(overdue_recv || 0) > 0 ? "orange" : "blue"
				);
			} catch (e) {
				// ignore
			}
		};

		refresh_counts();
		listview.on("after_refresh", refresh_counts);
	},
};

