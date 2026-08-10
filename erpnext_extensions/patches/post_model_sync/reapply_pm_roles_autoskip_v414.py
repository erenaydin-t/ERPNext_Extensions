# Copyright (c) 2026, ERPNext Extensions contributors
"""Re-apply v4.1.4 hardening for sites that already ran migrate_pm_roles_autoskip_v414.

Idempotent: DocPerm (no Accountant delete), legacy Manager→User grants, workflow rebuild.
"""

from __future__ import annotations

from erpnext_extensions.patches.post_model_sync.migrate_pm_roles_autoskip_v414 import execute as _execute


def execute():
	_execute()
