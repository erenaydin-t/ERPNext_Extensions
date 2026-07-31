# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Release notes — erpnext_extensions 3.8.0 Consignment Stock."""

# Consignment Stock (inbound raw materials)
#
# Features
# - Stock Entry Type flags: Consignment Receipt / Consignment Return
# - Consignment Stock Settings (per company): Inventory, Temporary Clearing,
#   Valuation Difference, default Cost Center / Finance Book / warehouse
# - Consignment Receipt: manual basic_rate, party Dynamic Link, expense_account
#   forced to Temporary Clearing (standard SE GL — no duplicate inventory JE)
# - Recognition JE (always draft): Dr Temp / Cr Party via get_party_account
# - Consignment Return: requires submitted Recognition JE + receipt row refs
# - Settlement JE (always draft): Dr Party (R), ± Diff (A−R), Cr Temp (A)
# - Additional Costs blocked on consignment Stock Entries
# - JE Account reference_type Property Setter adds Stock Entry option
#   (builders do NOT set it on party lines — avoids Payment Ledger locks)
# - Document links: SE custom JE fields + custom_consignment_je_role + remarks
#
# Out of scope
# - Return without receipt reference
# - Desk dashboard overrides
# - Auto-submit of Journal Entries
#
# Setup
# 1. bench migrate
# 2. Create COA accounts + consignment warehouse (warehouse account = inventory)
# 3. Configure Consignment Stock Settings per company
# 4. Create Stock Entry Types with consignment flags
#
# Cancellation order: Settlement JE → Return SE → Recognition JE → Receipt SE
