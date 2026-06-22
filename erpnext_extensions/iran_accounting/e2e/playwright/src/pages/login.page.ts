import type { Page } from "@playwright/test";

export class LoginPage {
  constructor(private readonly page: Page) {}

  async login(email: string, password: string): Promise<void> {
    const apiLogin = await this.page.request.post("/api/method/login", {
      form: { usr: email, pwd: password },
    });
    if (apiLogin.ok()) {
      const body = await apiLogin.json();
      if (body.message === "Logged In" || body.message?.home_page) {
        await this.page.goto("/desk", { waitUntil: "domcontentloaded" });
        await this.waitForDeskSession();
        return;
      }
    }
    await this.page.goto("/login", { waitUntil: "domcontentloaded" });
    await this.page.locator("#login_email").fill(email);
    await this.page.locator("#login_password").fill(password);
    await this.page.locator("button.btn-login").first().click();
    await this.page.waitForURL(/\/(app|desk)/, { timeout: 120_000 });
    await this.waitForDeskSession();
  }

  private async waitForDeskSession(): Promise<void> {
    await this.page.waitForFunction(
      () => {
        const w = window as unknown as { frappe?: { session?: { user?: string } } };
        return !!w.frappe?.session?.user && w.frappe.session.user !== "Guest";
      },
      { timeout: 120_000 }
    );
  }
}
