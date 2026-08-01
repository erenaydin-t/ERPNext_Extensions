# Material Loan — Final Implementation Plan (Locked 3.8.1)

**Status:** Approved — implementation in progress  
**Date:** 2026-08-01  

All decisions in the user approval message are locked. This plan executes P0→P5.

## Locked summary

- SE Issue: Dr Temp / Cr Warehouse; SE Return: Dr Warehouse / Cr Temp  
- Recognition JE: Dr Party map / Cr Temp (draft-first)  
- Settlement JE: Dr Temp / Cr Party ± Diff (D=A−R)  
- Party Type → Account child table; Customer=Receivable, Supplier=Payable; no trade defaults  
- Separate physical / recognition / settlement statuses  
- Recognition submitted before any Return  
- PLE-safe: no SE reference on party JE lines  
- Reports: Outstanding Material Loans, Material Loan Ledger, Material Loan Aging  
- Inbound 3.8.0 unchanged; 43 tests green  
- No commit until pre-commit report approved  

## Phases

| Phase | Scope |
| --- | --- |
| P0 | Settings child + fields, SET/SE fields, patches |
| P1 | Issue + freeze + Recognition |
| P2 | Return refs + qty + frozen rates |
| P3 | Settlement + Diff + status + cancellation |
| P4 | Repost + reports + UI/API |
| P5 | Tests + migrate + build + evidence + pre-commit report |

## Package

`consignment_stock/material_loan/` — additive; inbound services untouched.
