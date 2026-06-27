app_name = "erpnext_extensions"
__version__ = "2.8.0"

# Load IRR accounting patches when the app is imported on the bench worker / console.
try:
	import erpnext_extensions.iran_accounting  # noqa: F401
except Exception:
	pass
