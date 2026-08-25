# Copyright (c) 2026, ERPNext Extensions contributors
"""RELEASE 4.6.4 — Upgrade Guard annotation compatibility.

## Fixed

- IRR Upgrade Guard no longer false-negatives on annotation-only signature /
  source drift (e.g. ERPNext 16.32.1 runtime shape ``(doc) -> 'None'`` vs
  allow-list ``(doc)``).
- Shared fingerprint normalization (UVR regional + RIV rate guards) ignores
  parameter/return type hints while still failing closed on executable AST
  changes (control flow, calls, SQL, assignments, defaults, arity).

## Unchanged

- No accounting calculation changes
- No GL posting changes
- No schema / index / Redis changes
- ERPNext / Frappe major.minor allow-lists not broadened
- No permissive fallback for real upstream code changes

## Version

``4.6.3`` → ``4.6.4``
"""
