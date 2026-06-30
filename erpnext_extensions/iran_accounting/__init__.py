# Copyright (c) 2026, ERPNext Extensions contributors
"""Iranian Rial (IRR) accounting and zero-value stock transfer GL corrections.

Important: do not apply monkey patches at import time.
Frappe loads app modules during boot, hooks resolution, and background jobs. Applying
patches here creates circular imports (package -> monkey_patches -> package) and can
surface as non-deterministic ImportError during document lifecycle operations.
"""

from erpnext_extensions.iran_accounting.monkey_patches import apply_monkey_patches  # noqa: F401
