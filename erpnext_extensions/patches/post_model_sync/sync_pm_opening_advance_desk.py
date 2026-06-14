"""Re-sync Petty Management desk (sidebar, cards, shortcuts) after PM Opening Advance links were added."""

from __future__ import annotations

from erpnext_extensions.patches.post_model_sync.add_petty_management_workspace import (
	execute as sync_petty_management_workspace,
)


def execute():
	sync_petty_management_workspace()
