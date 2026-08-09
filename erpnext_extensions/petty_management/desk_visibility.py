# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Re-apply Petty Management Module Def + Workspace after migrate (same pattern as Payments sidebar patch)."""


def after_migrate():
	from erpnext_extensions.patches.post_model_sync.add_petty_management_workspace import execute
	from erpnext_extensions.patches.post_model_sync.migrate_pm_workflow_v402 import execute as migrate_v402

	# Idempotent v4.0.2 workflow + Assignment Rule repair (supersedes legacy single-level repair).
	migrate_v402()
	execute()
