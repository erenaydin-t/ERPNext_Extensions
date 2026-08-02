# Copyright (c) 2026, ERPNext Extensions contributors
"""Non-trivial IRR fixtures that force repeating valuation rates and rounding.

Avoid round thousands (1000/2000/4000/5000) unless testing whole-number behaviour.

Rate-first contract: rates are ROUND_HALF_UP integers; amounts = qty × integer_rate
(+ capitalized costs). Fractional AMT/QTY pairs below document the *pre-contract*
mathematical ratios; INT_* constants are the post-contract expected values.
"""

from __future__ import annotations

from decimal import Decimal

from erpnext_extensions.iran_accounting.tests.hardening.decimal_money import (
	integer_valuation_rate,
	quantize_money,
	rate_first_amount,
)

# Canonical pairs: amount / qty → repeating valuation_rate (legacy mathematical)
QTY_A = Decimal("7")
AMT_A = Decimal("1234")  # 1234/7 = 176.285714... (not rate-first basic_amount)
RATE_A = AMT_A / QTY_A
INT_RATE_A = quantize_money(RATE_A, 0)  # 176
BASIC_A = rate_first_amount(QTY_A, INT_RATE_A, precision=0)  # 1232

QTY_B = Decimal("11")
AMT_B = Decimal("1237")  # 1237/11 = 112.454545...
RATE_B = AMT_B / QTY_B
INT_RATE_B = quantize_money(RATE_B, 0)  # 112
BASIC_B = rate_first_amount(QTY_B, INT_RATE_B, precision=0)  # 1232

QTY_C = Decimal("13")
AMT_C = Decimal("5113")  # 5113/13 = 393.307692...
RATE_C = AMT_C / QTY_C
INT_RATE_C = quantize_money(RATE_C, 0)  # 393
BASIC_C = rate_first_amount(QTY_C, INT_RATE_C, precision=0)  # 5109

QTY_D = Decimal("7")
AMT_D = Decimal("2479")  # 2479/7 = 354.142857...
RATE_D = AMT_D / QTY_D
INT_RATE_D = quantize_money(RATE_D, 0)  # 354
BASIC_D = rate_first_amount(QTY_D, INT_RATE_D, precision=0)  # 2478

QTY_E = Decimal("7")
AMT_E = Decimal("1371")  # 1371/7 = 195.857142... preferred residual example
RATE_E = AMT_E / QTY_E
# For residual demo: amount stays 1371, valuation_rate=196, residual=-1
VAL_RATE_E = integer_valuation_rate(AMT_E, QTY_E, precision=0)  # 196
RESIDUAL_E = AMT_E - VAL_RATE_E * QTY_E  # -1

ADD_COST = Decimal("137")
LCV_AMT = Decimal("59")

# Cap with INT_RATE_A + ADD_COST
CAP_BASIC_A = BASIC_A  # 1232
CAP_AMOUNT_A = CAP_BASIC_A + ADD_COST  # 1369
CAP_VAL_RATE_A = integer_valuation_rate(CAP_AMOUNT_A, QTY_A, precision=0)  # 196
CAP_RESIDUAL_A = CAP_AMOUNT_A - CAP_VAL_RATE_A * QTY_A  # -3

# Cap with INT_RATE_B + LCV
CAP_BASIC_B = BASIC_B  # 1232
CAP_AMOUNT_B = CAP_BASIC_B + LCV_AMT  # 1291
CAP_VAL_RATE_B = integer_valuation_rate(CAP_AMOUNT_B, QTY_B, precision=0)

# Alternate UOM: qty in transaction UOM, transfer_qty in stock UOM
ALT_QTY = Decimal("2")
ALT_CONV = Decimal("5.5")  # transfer_qty = 11
ALT_TRANSFER = ALT_QTY * ALT_CONV  # 11
ALT_BASIC_RATE = INT_RATE_B  # stock UOM integer rate
ALT_BASIC_AMOUNT = BASIC_B  # 11 × 112 = 1232

# Manufacture residual ±1 case (no material capitalization)
RESIDUAL_OUT = Decimal("5113")
RESIDUAL_FG_STALE = Decimal("5114")  # one IRR off

# Reported production magnitudes (intentional whole-number regression case)
PROD_OUTGOING = Decimal("3482885707")
PROD_ADD = Decimal("2558380216")
PROD_FG = Decimal("6041265923")
PROD_QTY = Decimal("3150")
PROD_INT_RATE = quantize_money(PROD_OUTGOING / PROD_QTY, 0)
PROD_BASIC = rate_first_amount(PROD_QTY, PROD_INT_RATE, precision=0)
PROD_AMOUNT = PROD_BASIC + PROD_ADD
PROD_VAL_RATE = integer_valuation_rate(PROD_AMOUNT, PROD_QTY, precision=0)

# MAT-STE-2026-03516 regression fixture
STE_03516_QTY = Decimal("1245")
STE_03516_RAW_RATE = Decimal("2207006.162248996")
STE_03516_INT_RATE = quantize_money(STE_03516_RAW_RATE, 0)  # 2207006
STE_03516_AMOUNT = rate_first_amount(STE_03516_QTY, STE_03516_INT_RATE, precision=0)  # 2747722470
STE_03516_LEGACY_AMOUNT = Decimal("2747722672")  # product-first bug result
STE_03516_DELTA = STE_03516_LEGACY_AMOUNT - STE_03516_AMOUNT  # 202

IRR_PRECISION = 0
STOCK_QTY_PRECISION = 6
