# IRR rate-first rounding contract (version 3.8.3)

## Scope

Code + tests only. No historical production repair. No production repost.

Requested label was 3.7.7; develop was already at 3.8.2 → release **3.8.3**.

## Contract

For company currency IRR:

1. `integer_rate = ROUND_HALF_UP(raw_rate, 0)`
2. `basic_amount = ROUND_HALF_UP(transfer_qty × integer_rate, 0)`
3. `amount = ROUND_HALF_UP(basic_amount + additional_cost + LCV, 0)`
4. `valuation_rate = ROUND_HALF_UP(amount / transfer_qty, 0)`
5. **Amount is authoritative.** Residual = `amount − valuation_rate × qty` may be non-zero (±1 typical). Never force `amount := valuation_rate × qty`.

## Round Off residual GL (Phase 1.1)

```
rate_derived_amount = ROUND_HALF_UP(qty × integer_valuation_rate, 0)
rounding_residual   = authoritative_amount − rate_derived_amount
```

- SLE / inventory GL keep `authoritative_amount`
- When residual ≠ 0, post to `Company.round_off_account` / `Company.round_off_cost_center`
- Reclassify the same magnitude from a non-Stock GL leg (inventory unchanged)
- Round Off signed debit: incoming → `−residual`; outgoing → `+residual`
- Zero residual → no Round Off residual line
- Zero-value transfer GL path is skipped (isolated)
- Remarks marker: `IRR rate rounding residual`

## Residual rule (preferred)

Example: amount=1371, qty=7 → valuation_rate=196 → 196×7=1372 → residual=−1.

- SLE `stock_value_difference` = 1371
- Inventory GL = 1371
- Round Off Debit = 1 (incoming)

## Detection

Read-only: `domain/irr_rate_first_detector.py` → `detect_fractional_irr_stock_entry_rates`.
