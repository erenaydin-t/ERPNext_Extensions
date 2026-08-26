#!/usr/bin/env bash
# Run all Petty Management Playwright E2E scripts with evidence.
set -euo pipefail
export PLAYWRIGHT_BROWSERS_PATH="/home/frappe/.cache/ms-playwright"
export FRAPPE_E2E_BASE_URL="${FRAPPE_E2E_BASE_URL:-http://development.localhost:8001}"
export FRAPPE_E2E_SITE="${FRAPPE_E2E_SITE:-development.localhost}"
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
  "playwright_pm_pe_desk_cancel.mjs"
  "playwright_pm_request_cancel_delete.mjs"
  "playwright_pm_request_actions_visibility.mjs"
  "playwright_pm_request_funding_status_ux.mjs"
  "playwright_pm_request_list_permission.mjs"
  "playwright_pm_clearance_list_permission.mjs"
  "playwright_pm_visibility_role_setting.mjs"
  "playwright_pm_request_multi_approval.mjs"
  "playwright_pm_multi_pe.mjs"
  "playwright_pm_clearance_search_link_network_debug.mjs"
  "playwright_pm_clearance_settlement_lines_e2e.mjs"
  "playwright_pm_clearance_multi_approval.mjs"
  "playwright_pm_clearance_draft_pi_e2e.mjs"
  "playwright_pm_clearance_finance_role_queue.mjs"
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
