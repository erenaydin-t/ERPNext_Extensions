frappe.listview_settings["Asset Request"] = {
	add_fields: ["status", "fulfillment_status", "required_date"],
	get_indicator(doc) {
		const map = {
			Draft: [__("Draft"), "gray", "status,=,Draft"],
			"Pending Manager Approval": [__("Pending Manager"), "orange", "status,=,Pending Manager Approval"],
			"Pending Planning Approval": [__("Pending Planning"), "orange", "status,=,Pending Planning Approval"],
			"Pending CEO Approval": [__("Pending CEO"), "orange", "status,=,Pending CEO Approval"],
			Approved: [__("Approved"), "blue", "status,=,Approved"],
			"Partially Fulfilled": [__("Partially Fulfilled"), "blue", "status,=,Partially Fulfilled"],
			Fulfilled: [__("Fulfilled"), "green", "status,=,Fulfilled"],
			Rejected: [__("Rejected"), "red", "status,=,Rejected"],
			Cancelled: [__("Cancelled"), "gray", "status,=,Cancelled"],
		};
		return map[doc.status] || [__(doc.status), "gray"];
	},
};
