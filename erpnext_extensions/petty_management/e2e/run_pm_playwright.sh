#!/usr/bin/env bash
# Run all Petty Management Playwright E2E scripts with evidence.
set -euo pipefail
export PLAYWRIGHT_BROWSERS_PATH="/home/frappe/.cache/ms-playwright"
if [ ! -d "$PLAYWRIGHT_BROWSERS_PATH" ]; then
  echo "Missing Playwright browsers at $PLAYWRIGHT_BROWSERS_PATH" >&2
  exit 2
fi
ROOT="/workspace/development/frappe-bench/apps/erpnext_extensions/erpnext_extensions"
E2E="$ROOT/petty_management/e2e"
OUT="${1:-/tmp/pm_playwright_results.txt}"

SCRIPTS=(
  "playwright_pm_request_form_smoke.mjs"
  "playwright_pm_request_pe_list_e2e.mjs"
  "playwright_pm_multi_pe.mjs"
  "playwright_pm_clearance_search_link_network_debug.mjs"
  "playwright_pm_clearance_settlement_lines_e2e.mjs"
)

{
  echo "=== PM Playwright $(date -Iseconds) ==="
  FAIL=0
  for s in "${SCRIPTS[@]}"; do
    echo "--- $s ---"
    if (cd "$E2E" && node "$s" 2>&1); then
      echo "RESULT $s OK"
    else
      echo "RESULT $s FAIL"
      FAIL=1
    fi
  done
  echo "=== PLAYWRIGHT SUMMARY exit=$FAIL ==="
  exit "$FAIL"
} | tee "$OUT"
