# erpnext_extensions 3.8.1 — Material Loan (Outbound)

## Summary

Adds **Material Loan** to `consignment_stock`: company-owned materials temporarily held by Customer/Supplier (or mapped Party Types), with Temporary Clearing Stock Entries and draft-first Recognition / Settlement Journal Entries.

## Accounting

- Issue SE: Dr Material Loan Temporary Clearing / Cr Warehouse  
- Recognition JE: Dr mapped Party Material Loan Account / Cr Temporary Clearing  
- Return SE: Dr Warehouse / Cr Temporary Clearing (frozen issue rate)  
- Settlement JE: Dr Temporary Clearing / Cr Party ± Valuation Difference (D = A − R)

Customer → dedicated Receivable mapping; Supplier → dedicated Payable mapping. No default Debtors/Creditors. No `reference_type=Stock Entry` on party JE lines (PLE-safe).

## Unchanged

- Inbound Consignment Stock 3.8.0  
- Warehouse-map inventory accounts (`enable_item_wise_inventory_account = 0`)  
- No Settings inventory / cost center / finance book fields  

## Compatibility

ERPNext 16.30+, perpetual inventory, iran_accounting Stock Entry hook order preserved.
