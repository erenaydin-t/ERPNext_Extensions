# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

MODULE = "Asset Usage Depreciation"

MODE_NORMAL = "Normal"
MODE_PERCENTAGE = "Percentage"
MODE_NO_DEPRECIATION = "No Depreciation"

HANDLING_EXTEND = "Extend Depreciation Schedule"
HANDLING_REDISTRIBUTE = "Redistribute Within Remaining Schedule"

COMPANY_FIELD_REDUCED_HANDLING = "custom_reduced_depreciation_handling"

MAX_MODE_A_EXTENSION_PERIODS = 1200

# ---------------------------------------------------------------------------
# LOCKED DEFAULT USAGE RULE
# ---------------------------------------------------------------------------
# If no submitted Asset Usage Period covers a given date, the effective
# depreciation mode is Normal (100%). This is the central timeline fallback.
#
# Applies when:
#   - the Asset has no Usage Period records at all
#   - the date is before the first Usage Period
#   - there is a gap between two Usage Periods
#   - a closed period has ended and no later period covers the date
#
# Do NOT create automatic Normal Usage Period rows on Asset creation.
# Do NOT require explicit Normal records to establish the default state.
# Explicit Normal records are optional status-change markers only.
#
# factor_on_date / day_weighted_factor MUST return this factor for uncovered dates.
DEFAULT_USAGE_FACTOR = 1.0
