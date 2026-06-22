export function env(name: string, fallback = ""): string {
  return process.env[name]?.trim() || fallback;
}

export const config = {
  baseURL: env("FRAPPE_E2E_BASE_URL", "http://development.localhost:8000"),
  user: env("FRAPPE_E2E_USER", "Administrator"),
  password: env("FRAPPE_E2E_PASSWORD", "admin"),
  company: env("FRAPPE_E2E_COMPANY", "ESPAD"),
  mtfmStockEntry: env("E2E_MTFM_STOCK_ENTRY"),
  benchRoot: env("FRAPPE_BENCH_ROOT", "/workspace/development/frappe-bench"),
  site: env("FRAPPE_SITE", "development.localhost"),
};
