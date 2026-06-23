import dns from "dns";
import { URL } from "url";

export function deskBaseUrlResolvable(baseUrl: string): boolean {
  try {
    const host = new URL(baseUrl).hostname;
    dns.lookupSync(host);
    return true;
  } catch {
    return false;
  }
}
