import type { Page } from "@playwright/test";
import path from "path";
import fs from "fs";

const SCREEN_DIR = path.join(__dirname, "../../test-results/screenshots");

export async function captureStep(page: Page, step: string): Promise<string> {
  fs.mkdirSync(SCREEN_DIR, { recursive: true });
  const safe = step.replace(/[^\w-]+/g, "_").slice(0, 80);
  const file = path.join(SCREEN_DIR, `${Date.now()}_${safe}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return file;
}
