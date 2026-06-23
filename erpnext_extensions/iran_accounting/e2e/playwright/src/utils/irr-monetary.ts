/** IRR monetary cells must not show fractional amounts (quantity columns exempt). */

const MONETARY_HEADER = /incoming rate|outgoing rate|avg rate|valuation rate|balance value|value change|stock value|incoming value|outgoing value|amount|debit|credit|balance(?! qty)/i;
const QUANTITY_HEADER = /in qty|out qty|balance qty|actual qty|qty after|transfer qty|^qty$/i;

export function isQuantityColumn(header: string): boolean {
  const h = header.trim().toLowerCase();
  if (QUANTITY_HEADER.test(h)) return true;
  if (MONETARY_HEADER.test(h)) return false;
  return false;
}

export function isMonetaryColumn(header: string): boolean {
  const h = header.trim().toLowerCase();
  if (QUANTITY_HEADER.test(h)) return false;
  return MONETARY_HEADER.test(h);
}

/** Detect IRR-style monetary decimals in display text (e.g. 12,663.84). */
export function cellHasIrrMonetaryDecimal(text: string): boolean {
  const s = (text || "").trim();
  if (!s || s === "—" || s === "-") return false;
  const normalized = s.replace(/\s/g, "");
  if (/^\d+\.\d+$/.test(normalized)) return true;
  if (/^\d{1,3}(,\d{3})+\.\d+/.test(normalized)) return true;
  if (/[\d,]+\.\d{2,}/.test(normalized) && /[₨﷼]|irr|ریال/i.test(s)) return true;
  if (/^\d{4,}\.\d+/.test(normalized.replace(/,/g, ""))) return true;
  return /,\d{3}\.\d+/.test(normalized);
}

export function findMonetaryDecimalViolations(
  headers: string[],
  rows: string[][]
): { row: number; column: string; value: string }[] {
  const monetaryIdx = headers
    .map((h, i) => (isMonetaryColumn(h) ? i : -1))
    .filter((i) => i >= 0);
  const hits: { row: number; column: string; value: string }[] = [];
  rows.forEach((cells, rowIdx) => {
    for (const colIdx of monetaryIdx) {
      const val = cells[colIdx] ?? "";
      if (cellHasIrrMonetaryDecimal(val)) {
        hits.push({ row: rowIdx, column: headers[colIdx], value: val });
      }
    }
  });
  return hits;
}
