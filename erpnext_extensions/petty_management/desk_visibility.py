# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Re-apply Petty Management Module Def + Workspace after migrate (same pattern as Payments sidebar patch)."""


def after_migrate():
	from erpnext_extensions.patches.post_model_sync.add_petty_management_workspace import execute
	from erpnext_extensions.patches.post_model_sync.add_petty_management_workflows import (
		repair_pm_clearance_workflow,
		repair_pm_request_workflow,
	)

	repair_pm_request_workflow()
	repair_pm_clearance_workflow()
	execute()
