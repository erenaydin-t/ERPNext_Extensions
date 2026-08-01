# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Release notes — erpnext_extensions 3.8.0 Consignment Stock."""

# Consignment Stock (inbound raw materials)
#
# Features
# - Stock Entry Type flags: Consignment Receipt / Consignment Return
# - Consignment Stock Settings (per company):
#     Temporary Clearing Account (intermediate consignment liability clearing)
#     Valuation Difference Account (receipt settlement value vs actual return valuation)
#     Default Consignment Warehouse (UI convenience only)
#     Allow Zero Receipt Rate
# - Inventory / Warehouse Account: resolved from selected Warehouse via standard
#   ERPNext warehouse-account map (erpnext.stock.get_warehouse_account_map;
#   not stored on Settings)
# - Compatibility assumption (3.8.0): Company.enable_item_wise_inventory_account
#   must remain disabled. Item-wise inventory accounts are NOT covered; enabling
#   them for a consignment company is unsupported in this release.
# - Cost Center / Finance Book: standard ERPNext behavior only (not forced from Settings);
#   JE builders copy Stock Entry finance_book only when explicitly set; cost center only
#   when all SE item rows share one cost center
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
# - Item-wise inventory accounts (Company.enable_item_wise_inventory_account)
#
# Setup
# 1. bench migrate
# 2. Create Temporary Clearing + Valuation Difference accounts;
#    set Warehouse.account (or company default inventory account) for consignment WH
# 3. Configure Consignment Stock Settings per company
# 4. Create Stock Entry Types with consignment flags
#
# Cancellation order: Settlement JE → Return SE → Recognition JE → Receipt SE
#
# Migration note (settings redesign within 3.8.0)
# Removed Settings fields: consignment_inventory_account, default_cost_center,
# default_finance_book. Existing Settings documents are preserved; old values are
# not migrated (intentionally retired). Patch:
# remove_obsolete_consignment_settings_fields (idempotent).
