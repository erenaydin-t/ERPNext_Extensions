#!/usr/bin/env bash
# Run all Petty Management Playwright E2E scripts; capture exit codes and log paths.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
E2E_DIR="$ROOT/erpnext_extensions/petty_management/e2e"
OUT="${1:-/tmp/pm_playwright_regression.txt}"
LOCK="${PM_REGRESSION_LOCK:-/tmp/pm_regression.lock}"
exec 8>"$LOCK"
if ! flock -n 8; then
  echo "PM bench regression lock held ($LOCK). Run Playwright after unit/smoke finishes." >&2
  exit 2
fi
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/home/frappe/.cache/ms-playwright}"
export FRAPPE_E2E_BASE_URL="${FRAPPE_E2E_BASE_URL:-http://development.localhost:8000}"
export FRAPPE_BENCH_ROOT="${FRAPPE_BENCH_ROOT:-/workspace/development/frappe-bench}"

SCRIPTS=(
  playwright_pm_request_form_smoke.mjs
  playwright_pm_request_pe_list_e2e.mjs
  playwright_pm_multi_pe.mjs
  playwright_pm_clearance_search_link_network_debug.mjs
  playwright_pm_clearance_settlement_lines_e2e.mjs
)

{
  echo "=== PM Playwright regression $(date -Iseconds) ==="
  FAIL=0
  for s in "${SCRIPTS[@]}"; do
    echo "--- $s ---"
    if (cd "$E2E_DIR" && node "$s" 2>&1); then
      echo "RESULT $s OK"
    else
      echo "RESULT $s FAIL"
      FAIL=1
    fi
  done
  echo "=== PLAYWRIGHT SUMMARY exit=$FAIL ==="
  exit "$FAIL"
} | tee "$OUT"
