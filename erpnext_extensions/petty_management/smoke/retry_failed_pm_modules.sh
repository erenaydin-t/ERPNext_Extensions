#!/usr/bin/env bash
# Re-run PM modules that failed in batch regression (after fixes / without parallel contention).
set -euo pipefail
BENCH="${FRAPPE_BENCH_ROOT:-/workspace/development/frappe-bench}"
SITE="${FRAPPE_SITE:-development.localhost}"
cd "$BENCH"

MODULES=(
  erpnext_extensions.petty_management.tests.test_pm_clearance_smoke
  erpnext_extensions.petty_management.tests.test_pm_holder_ux
  erpnext_extensions.petty_management.tests.test_pm_opening_advance
  erpnext_extensions.petty_management.tests.test_pm_opening_advance_over_allocation
  erpnext_extensions.petty_management.tests.test_pm_production_hardening
  erpnext_extensions.petty_management.tests.test_pm_request_action_flags_uat
)

FAIL=0
for m in "${MODULES[@]}"; do
  echo "--- RETRY $m ---"
  if bench --site "$SITE" run-tests --module "$m" --skip-before-tests; then
    echo "RESULT $m OK"
  else
    echo "RESULT $m FAIL"
    FAIL=1
  fi
done
exit "$FAIL"
