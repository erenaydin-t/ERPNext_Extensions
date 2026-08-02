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

## Residual rule (preferred)

Example: amount=1371, qty=7 → valuation_rate=196 → 196×7=1372 → residual=−1.

- SLE `stock_value_difference` = 1371
- GL inventory movement = 1371
- Stored `valuation_rate` = 196

## Detection

Read-only: `domain/irr_rate_first_detector.py` → `detect_fractional_irr_stock_entry_rates`.
