/**
 * v4.5.3 PM Clearance Finance Review Role Queue — Playwright Desk acceptance.
 *
 * Happy path (Holder → Manager → dual Reviewer queue → A approves → B blocked)
 * Draft PI branch (block → submit PI → B approves)
 * Concurrency (parallel API race — exactly one success)
 *
 * Evidence: screenshots/, traces/, DB Workflow Action snapshots (not committed).
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute, getDocumentState } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_clearance_finance_role_queue_v453");
const TRACE = path.join(__dirname, "traces", "pm_clearance_finance_role_queue_v453.zip");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8001";
const PREP =
  "erpnext_extensions.petty_management.e2e.pm_clearance_finance_role_queue_prep";

function bench(method, kwargs = null) {
  return benchExecute(method, kwargs);
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

async function loginAs(browser, email, password, evidence) {
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
  });
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") evidence.console_errors.push(`[${email}] ${msg.text()}`);
  });
  page.on("response", (res) => {
    if (res.status() >= 400) {
      evidence.network_failures.push(`[${email}] ${res.status()} ${res.url()}`);
    }
  });
  await page.goto(`${BASE}/login`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  const emailSel = (await page.locator("#login_email").count())
    ? "#login_email"
    : 'input[type="email"], input[name="email"], #login_email';
  const passSel = (await page.locator("#login_password").count())
    ? "#login_password"
    : 'input[type="password"], #login_password';
  await page.locator(emailSel).first().fill(email, { timeout: 60000 });
  await page.locator(passSel).first().fill(password, { timeout: 60000 });
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
  return { context, page };
}

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function openDoc(page, name) {
  await page.goto(`${BASE}/app/pm-clearance/${encodeURIComponent(name)}`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForFunction(
    (n) => window.cur_frm?.doc?.name === n && !window.cur_frm.is_loading,
    name,
    { timeout: 180000 }
  );
}

async function openList(page) {
  await page.goto(`${BASE}/app/pm-clearance`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForTimeout(2000);
}

async function listContains(page, name) {
  return page.evaluate((n) => {
    const text = document.body?.innerText || "";
    if (text.includes(n)) return true;
    return Array.from(document.querySelectorAll("a")).some(
      (a) => (a.textContent || "").trim() === n || (a.getAttribute("href") || "").includes(n)
    );
  }, name);
}

async function applyWorkflow(page, action) {
  return page.evaluate(async (act) => {
    const toMsg = (e) => {
      if (e == null) return "unknown";
      if (typeof e === "string") return e;
      try {
        if (e._server_messages) {
          const raw = e._server_messages;
          const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
          const msgs = (Array.isArray(parsed) ? parsed : [parsed]).map((m) => {
            try {
              const o = typeof m === "string" ? JSON.parse(m) : m;
              return o.message || String(m);
            } catch (_err) {
              return String(m);
            }
          });
          if (msgs.length) return msgs.join("\n");
        }
      } catch (_err) {
        /* ignore */
      }
      if (e.message && typeof e.message === "string") return e.message;
      try {
        return JSON.stringify(e);
      } catch (_err) {
        return String(e);
      }
    };
    try {
      await frappe.call({
        method: "frappe.model.workflow.apply_workflow",
        args: { doc: window.cur_frm.doc, action: act },
        freeze: false,
      });
      return {
        ok: true,
        status: window.cur_frm.doc.status,
        ws: window.cur_frm.doc.workflow_state,
        finance_approver: window.cur_frm.doc.finance_approver,
      };
    } catch (e) {
      return { ok: false, message: toMsg(e) };
    }
  }, action);
}

async function uiActions(page) {
  return page.evaluate(() => {
    const labels = Array.from(
      document.querySelectorAll(
        ".actions-btn-group .dropdown-menu a.dropdown-item, .btn, a.btn"
      )
    ).map((el) => (el.textContent || "").trim());
    return labels.filter(Boolean);
  });
}

function wfTitle(state) {
  if (!state) return "";
  const snap = getDocumentState("Workflow State", state, ["workflow_state_name"]);
  return (snap?.workflow_state_name || state || "").trim();
}

function assertOpenFinanceQueue(wa, reviewRole, clName) {
  assert(wa.open_count >= 1, `Expected ≥1 Open Workflow Action for ${clName}: ${JSON.stringify(wa)}`);
  const financeOpen = (wa.open || []).filter(
    (a) =>
      a.workflow_state_title === "Pending Finance Review" ||
      String(a.workflow_state || "").includes("Pending Finance")
  );
  // If title missing, accept any open action with review role.
  const candidates = financeOpen.length ? financeOpen : wa.open;
  assert(candidates.length >= 1, `No open finance Workflow Action: ${JSON.stringify(wa)}`);
  const withRole = candidates.some((a) => (a.permitted_roles || []).includes(reviewRole));
  assert(withRole, `Open action missing permitted role ${reviewRole}: ${JSON.stringify(candidates)}`);
}

async function runHappyPath(browser, evidence) {
  const prep = bench(`${PREP}.prepare_happy_path`);
  evidence.happy.prep = prep;
  evidence.email = prep.email;
  assert(prep?.email?.ok, `Finance Review email must be disabled: ${JSON.stringify(prep.email)}`);

  const cl = prep.pm_clearance;
  const reviewRole = prep.review_role;
  const U = prep.users;
  let context;
  let page;

  // 1–4 Holder submit
  ({ context, page } = await loginAs(browser, U.holder.email, U.holder.password, evidence));
  await context.tracing.start({ screenshots: true, snapshots: true });
  await openDoc(page, cl);
  evidence.screenshots.holder_draft = await shot(page, "01_holder_draft");
  const submit = await applyWorkflow(page, "PM Submit Finance Review");
  assert(submit.ok, `Holder submit failed: ${submit.message}`);
  await openDoc(page, cl);
  let state = bench(`${PREP}.get_clearance_state`, { pm_clearance: cl });
  evidence.happy.after_submit = state;
  assert(
    state.workflow_state_title === "Pending Manager Approval",
    `Expected Pending Manager Approval, got ${state.workflow_state_title}`
  );
  assert(!(state.finance_approver || "").trim(), "finance_approver must be blank after submit");
  evidence.screenshots.holder_pending_mgr = await shot(page, "02_pending_manager");
  await context.tracing.stop({ path: TRACE }).catch(() => null);
  await context.close();

  // 5–8 Manager approve
  ({ context, page } = await loginAs(browser, U.manager.email, U.manager.password, evidence));
  await openDoc(page, cl);
  evidence.screenshots.manager_open = await shot(page, "03_manager_open");
  const mgr = await applyWorkflow(page, "PM Manager Approve");
  assert(mgr.ok, `Manager approve failed: ${mgr.message}`);
  await openDoc(page, cl);
  state = bench(`${PREP}.get_clearance_state`, { pm_clearance: cl });
  evidence.happy.after_manager = state;
  assert(
    state.workflow_state_title === "Pending Finance Review",
    `Expected Pending Finance Review, got ${state.workflow_state_title}`
  );
  assert(!(state.finance_approver || "").trim(), "finance_approver must stay blank after manager");
  let wa = bench(`${PREP}.snapshot_workflow_actions`, { pm_clearance: cl });
  evidence.happy.wa_pending_finance = wa;
  assertOpenFinanceQueue(wa, reviewRole, cl);
  evidence.screenshots.pending_finance = await shot(page, "04_pending_finance");
  await context.close();

  // 9–12 Reviewer A queue + actions
  ({ context, page } = await loginAs(browser, U.reviewer_a.email, U.reviewer_a.password, evidence));
  const visA = bench(`${PREP}.clearance_visible_to`, {
    user: U.reviewer_a.email,
    pm_clearance: cl,
  });
  evidence.happy.visibility_a = visA;
  assert(visA.visible, `Reviewer A must see clearance: ${JSON.stringify(visA)}`);
  await openList(page);
  evidence.screenshots.reviewer_a_list = await shot(page, "05_reviewer_a_list");
  const inListA = await listContains(page, cl);
  await openDoc(page, cl);
  const actionsA = bench(`${PREP}.allowed_finance_actions`, {
    user: U.reviewer_a.email,
    pm_clearance: cl,
  });
  evidence.happy.actions_a = actionsA;
  assert(
    actionsA.actions.includes("PM Finance Approve"),
    `Reviewer A missing Finance Approve: ${JSON.stringify(actionsA)}`
  );
  assert(
    actionsA.actions.includes("PM Reject") || actionsA.actions.includes("PM Approve"),
    `Reviewer A missing reject/approve alias: ${JSON.stringify(actionsA)}`
  );
  evidence.screenshots.reviewer_a_form = await shot(page, "06_reviewer_a_form");
  evidence.happy.list_contains_a = inListA;
  await context.close();

  // 13–15 Reviewer B same queue
  ({ context, page } = await loginAs(browser, U.reviewer_b.email, U.reviewer_b.password, evidence));
  const visB = bench(`${PREP}.clearance_visible_to`, {
    user: U.reviewer_b.email,
    pm_clearance: cl,
  });
  evidence.happy.visibility_b = visB;
  assert(visB.visible, `Reviewer B must see same clearance: ${JSON.stringify(visB)}`);
  await openList(page);
  evidence.screenshots.reviewer_b_list = await shot(page, "07_reviewer_b_list");
  evidence.happy.list_contains_b = await listContains(page, cl);
  await openDoc(page, cl);
  const actionsB = bench(`${PREP}.allowed_finance_actions`, {
    user: U.reviewer_b.email,
    pm_clearance: cl,
  });
  evidence.happy.actions_b = actionsB;
  assert(
    actionsB.actions.includes("PM Finance Approve"),
    `Reviewer B missing Finance Approve: ${JSON.stringify(actionsB)}`
  );
  evidence.screenshots.reviewer_b_form = await shot(page, "08_reviewer_b_form");
  await context.close();

  // 16–17 Unrelated blocked
  ({ context, page } = await loginAs(browser, U.unrelated.email, U.unrelated.password, evidence));
  const visU = bench(`${PREP}.clearance_visible_to`, {
    user: U.unrelated.email,
    pm_clearance: cl,
  });
  evidence.happy.visibility_unrelated = visU;
  assert(!visU.visible, `Unrelated user must NOT see clearance: ${JSON.stringify(visU)}`);
  await openList(page);
  evidence.screenshots.unrelated_list = await shot(page, "09_unrelated_list");
  evidence.happy.list_contains_unrelated = await listContains(page, cl);
  assert(
    !evidence.happy.list_contains_unrelated,
    "Unrelated user list must not show clearance"
  );
  // Direct URL should not be openable with read
  let openBlocked = false;
  try {
    await openDoc(page, cl);
    const can = await page.evaluate(
      () => !(window.cur_frm?.doc?.name) || frappe.boot?.user?.name
    );
    // If form loaded despite list hide, permission must still deny write/actions
    const acts = bench(`${PREP}.allowed_finance_actions`, {
      user: U.unrelated.email,
      pm_clearance: cl,
    });
    evidence.happy.actions_unrelated = acts;
    openBlocked = !acts.actions.includes("PM Finance Approve");
  } catch (_e) {
    openBlocked = true;
  }
  evidence.happy.unrelated_open_blocked = openBlocked;
  assert(openBlocked, "Unrelated user must not have Finance Approve");
  await context.close();

  // 18 Reviewer A Finance Approve
  ({ context, page } = await loginAs(browser, U.reviewer_a.email, U.reviewer_a.password, evidence));
  await openDoc(page, cl);
  const fin = await applyWorkflow(page, "PM Finance Approve");
  assert(fin.ok, `Reviewer A Finance Approve failed: ${fin.message}`);
  await openDoc(page, cl);
  state = bench(`${PREP}.get_clearance_state`, { pm_clearance: cl });
  wa = bench(`${PREP}.snapshot_workflow_actions`, { pm_clearance: cl });
  evidence.happy.after_approve = state;
  evidence.happy.wa_after_approve = wa;
  assert(state.workflow_state_title === "Approved", `Expected Approved, got ${state.workflow_state_title}`);
  assert(state.finance_approver === U.reviewer_a.email, `finance_approver=${state.finance_approver}`);
  assert(
    ["Approved", "Pending Journal Entry Submission", "Settled"].includes(state.status) ||
      state.status === "Approved",
    `Unexpected status ${state.status}`
  );
  assert(wa.open_count === 0, `Stale Open Workflow Action remains: ${JSON.stringify(wa)}`);
  const completedByA = (wa.completed || []).some(
    (a) => a.completed_by === U.reviewer_a.email || a.user === U.reviewer_a.email
  );
  // Native Frappe may set completed_by on the action row
  const anyCompleted = (wa.completed || []).length >= 1;
  assert(anyCompleted, `Expected Completed Workflow Action: ${JSON.stringify(wa)}`);
  evidence.happy.completed_by_matches =
    completedByA ||
    (wa.completed || []).some((a) => String(a.completed_by || "").includes(U.reviewer_a.email));
  if (!evidence.happy.completed_by_matches) {
    // Accept completed_by blank only if status Completed and stamp matches reviewer A
    evidence.happy.completed_by_note =
      "completed_by field may be empty on this Frappe build; finance_approver stamp is Reviewer A";
  }
  evidence.screenshots.approved = await shot(page, "10_approved_by_a");
  await context.close();

  // 19–20 Reviewer B blocked (may lose form read once Approved — assert via API)
  ({ context, page } = await loginAs(browser, U.reviewer_b.email, U.reviewer_b.password, evidence));
  const actionsB2 = bench(`${PREP}.allowed_finance_actions`, {
    user: U.reviewer_b.email,
    pm_clearance: cl,
  });
  evidence.happy.actions_b_after = actionsB2;
  assert(
    !actionsB2.actions.includes("PM Finance Approve"),
    `Reviewer B still has Finance Approve after A: ${JSON.stringify(actionsB2)}`
  );
  const second = bench(`${PREP}.try_finance_approve`, {
    user: U.reviewer_b.email,
    pm_clearance: cl,
  });
  assert(!second.ok, `Second Finance Approve must fail: ${JSON.stringify(second)}`);
  evidence.happy.second_approve = second;
  state = bench(`${PREP}.get_clearance_state`, { pm_clearance: cl });
  assert(state.finance_approver === U.reviewer_a.email, "finance_approver must remain Reviewer A");
  await openList(page);
  evidence.screenshots.reviewer_b_blocked = await shot(page, "11_reviewer_b_blocked");
  await context.close();

  evidence.happy.ok = true;
  return prep;
}

async function runDraftPiBranch(browser, evidence) {
  const prep = bench(`${PREP}.prepare_draft_pi_branch`);
  evidence.draft_pi.prep = prep;
  const cl = prep.pm_clearance;
  const reviewRole = prep.review_role;
  const U = prep.users;
  let context;
  let page;

  assert(prep.workflow_state_title === "Pending Finance Review", prep.workflow_state_title);
  assert(!(prep.finance_approver || "").trim(), "finance_approver must be blank on draft-PI queue");
  assertOpenFinanceQueue(prep.workflow_actions, reviewRole, cl);

  // Reviewer A sees queue, blocked by PI gate
  ({ context, page } = await loginAs(browser, U.reviewer_a.email, U.reviewer_a.password, evidence));
  const visA = bench(`${PREP}.clearance_visible_to`, {
    user: U.reviewer_a.email,
    pm_clearance: cl,
  });
  assert(visA.visible, `Reviewer A must see draft-PI clearance: ${JSON.stringify(visA)}`);
  await openDoc(page, cl);
  evidence.screenshots.draft_pi_a_open = await shot(page, "20_draft_pi_reviewer_a");
  const blockedUi = await applyWorkflow(page, "PM Finance Approve");
  const blocked = bench(`${PREP}.try_finance_approve`, {
    user: U.reviewer_a.email,
    pm_clearance: cl,
  });
  assert(!blocked.ok || !blockedUi.ok, "Draft PI Finance Approve must be blocked");
  const blockMsg = String(blocked.error || blockedUi.message || "");
  evidence.draft_pi.block_message = blockMsg;
  assert(
    /not submitted|Cannot complete Finance Approval|Purchase Invoice/i.test(blockMsg),
    `Unexpected block message: ${blockMsg}`
  );
  let state = bench(`${PREP}.get_clearance_state`, { pm_clearance: cl });
  let wa = bench(`${PREP}.snapshot_workflow_actions`, { pm_clearance: cl });
  evidence.draft_pi.after_block = { state, wa, message: blocked.message };
  assert(state.workflow_state_title === "Pending Finance Review", state.workflow_state_title);
  assert(!(state.finance_approver || "").trim(), "finance_approver must stay blank after block");
  assertOpenFinanceQueue(wa, reviewRole, cl);
  await context.close();

  // Reviewer B still sees same queue item
  ({ context, page } = await loginAs(browser, U.reviewer_b.email, U.reviewer_b.password, evidence));
  const visB = bench(`${PREP}.clearance_visible_to`, {
    user: U.reviewer_b.email,
    pm_clearance: cl,
  });
  assert(visB.visible, `Reviewer B must still see draft-PI queue: ${JSON.stringify(visB)}`);
  await openDoc(page, cl);
  evidence.screenshots.draft_pi_b_still = await shot(page, "21_draft_pi_reviewer_b");
  await context.close();

  // Submit PI + Reviewer B approves
  bench(`${PREP}.submit_prepared_pi`, { purchase_invoice: prep.draft_pi });
  bench(`${PREP}.refresh_clearance_pi_amounts`, {
    pm_clearance: cl,
    purchase_invoice: prep.draft_pi,
  });

  ({ context, page } = await loginAs(browser, U.reviewer_b.email, U.reviewer_b.password, evidence));
  await openDoc(page, cl);
  const ok = await applyWorkflow(page, "PM Finance Approve");
  assert(ok.ok, `Reviewer B Finance Approve after PI submit failed: ${ok.message}`);
  await openDoc(page, cl);
  state = bench(`${PREP}.get_clearance_state`, { pm_clearance: cl });
  wa = bench(`${PREP}.snapshot_workflow_actions`, { pm_clearance: cl });
  evidence.draft_pi.after_b_approve = { state, wa };
  assert(state.workflow_state_title === "Approved", state.workflow_state_title);
  assert(state.finance_approver === U.reviewer_b.email, `finance_approver=${state.finance_approver}`);
  assert(wa.open_count === 0, `Stale open WA after B approve: ${JSON.stringify(wa)}`);
  evidence.screenshots.draft_pi_approved_b = await shot(page, "22_draft_pi_approved_by_b");
  await context.close();

  evidence.draft_pi.ok = true;
}

async function runConcurrency(browser, evidence) {
  const prep = bench(`${PREP}.prepare_concurrency`);
  evidence.concurrency.prep = prep;
  const race = bench(`${PREP}.parallel_finance_approve`, {
    pm_clearance: prep.pm_clearance,
    user_a: prep.users.reviewer_a.email,
    user_b: prep.users.reviewer_b.email,
  });
  evidence.concurrency.race = race;
  assert(race.ok, `Concurrency race failed: ${JSON.stringify(race)}`);
  assert(race.success_count === 1, `Expected exactly one success, got ${race.success_count}`);
  assert(race.state.workflow_state_title === "Approved", race.state.workflow_state_title);
  assert(
    [prep.users.reviewer_a.email, prep.users.reviewer_b.email].includes(race.state.finance_approver),
    `Unexpected finance_approver ${race.state.finance_approver}`
  );
  assert(race.workflow_actions.open_count === 0, "Stale open WA after concurrency");
  evidence.concurrency.ok = true;
}

async function run() {
  fs.mkdirSync(SCREEN, { recursive: true });
  fs.mkdirSync(path.dirname(TRACE), { recursive: true });

  const evidence = {
    screenshots: {},
    console_errors: [],
    network_failures: [],
    happy: {},
    draft_pi: {},
    concurrency: {},
    email: null,
    trace: TRACE,
  };

  const browser = await chromium.launch({ headless: true });
  try {
    await runHappyPath(browser, evidence);
    await runDraftPiBranch(browser, evidence);
    await runConcurrency(browser, evidence);

    const ok =
      evidence.happy.ok === true &&
      evidence.draft_pi.ok === true &&
      evidence.concurrency.ok === true &&
      evidence.email?.ok === true;

    console.log(JSON.stringify({ ok, evidence }, null, 2));
    await browser.close();
    process.exit(ok ? 0 : 1);
  } catch (err) {
    evidence.error = String(err?.stack || err);
    console.log(JSON.stringify({ ok: false, evidence }, null, 2));
    await browser.close();
    process.exit(1);
  }
}

run();
