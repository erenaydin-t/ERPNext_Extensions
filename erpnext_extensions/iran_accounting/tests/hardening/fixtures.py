# Copyright (c) 2026, ERPNext Extensions contributors
"""Non-trivial IRR fixtures that force repeating valuation rates and rounding.

Avoid round thousands (1000/2000/4000/5000) unless testing whole-number behaviour.
"""

from __future__ import annotations

from decimal import Decimal

# Canonical pairs: amount / qty → repeating valuation_rate
QTY_A = Decimal("7")
AMT_A = Decimal("1234")  # 1234/7 = 176.285714...
RATE_A = AMT_A / QTY_A

QTY_B = Decimal("11")
AMT_B = Decimal("1237")  # 1237/11 = 112.454545...
RATE_B = AMT_B / QTY_B

QTY_C = Decimal("13")
AMT_C = Decimal("5113")  # 5113/13 = 393.307692...
RATE_C = AMT_C / QTY_C

QTY_D = Decimal("7")
AMT_D = Decimal("2479")  # 2479/7 = 354.142857...
RATE_D = AMT_D / QTY_D

QTY_E = Decimal("7")
AMT_E = Decimal("1371")  # 1371/7 = 195.857142...
RATE_E = AMT_E / QTY_E

ADD_COST = Decimal("137")
LCV_AMT = Decimal("59")

# Alternate UOM: qty in transaction UOM, transfer_qty in stock UOM
ALT_QTY = Decimal("2")
ALT_CONV = Decimal("5.5")  # transfer_qty = 11
ALT_TRANSFER = ALT_QTY * ALT_CONV  # 11
ALT_BASIC_RATE = RATE_B  # stock UOM rate
ALT_BASIC_AMOUNT = AMT_B  # round(11 * RATE_B) composition target = 1237

# Manufacture residual ±1 case (no material capitalization)
RESIDUAL_OUT = Decimal("5113")
RESIDUAL_FG_STALE = Decimal("5114")  # one IRR off

# Reported production magnitudes (intentional whole-number regression case)
PROD_OUTGOING = Decimal("3482885707")
PROD_ADD = Decimal("2558380216")
PROD_FG = Decimal("6041265923")
PROD_QTY = Decimal("3150")

IRR_PRECISION = 0
STOCK_QTY_PRECISION = 6
