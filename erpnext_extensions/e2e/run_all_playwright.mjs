#!/usr/bin/env node
/**
 * Run erpnext_extensions Playwright suites with isolation-aware scheduling.
 *
 *   node erpnext_extensions/e2e/run_all_playwright.mjs
 *   node erpnext_extensions/e2e/run_all_playwright.mjs --serial
 *   node erpnext_extensions/e2e/run_all_playwright.mjs --parallel --jobs 3
 *   node erpnext_extensions/e2e/run_all_playwright.mjs --grep pdc_workflow
 */
import { execSync } from "child_process";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { discoverScripts, registryByScript, tagsForScript } from "./playwright_suites.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");

function parseArgs(argv) {
	const opts = {
		serial: false,
		parallel: false,
		jobs: 2,
		grep: null,
		retries: 1,
	};
	for (let i = 2; i < argv.length; i++) {
		const a = argv[i];
		if (a === "--serial") {
			opts.serial = true;
		} else if (a === "--parallel") {
			opts.parallel = true;
		} else if (a === "--jobs" && argv[i + 1]) {
			opts.jobs = Math.max(1, parseInt(argv[++i], 10) || 2);
		} else if (a === "--grep" && argv[i + 1]) {
			opts.grep = argv[++i];
		} else if (a === "--retries" && argv[i + 1]) {
			opts.retries = Math.max(0, parseInt(argv[++i], 10) || 0);
		}
	}
	if (!opts.serial && !opts.parallel) {
		opts.serial = true;
	}
	return opts;
}

function parseOutcome(text) {
	const m = text.match(/"all_ok"\s*:\s*(true|false)/) || text.match(/"pass"\s*:\s*(true|false)/);
	return m ? m[1] === "true" : null;
}

function runScriptOnce(absPath, timeoutMs) {
	const started = Date.now();
	try {
		const out = execSync(`node "${absPath}"`, {
			encoding: "utf8",
			maxBuffer: 80 * 1024 * 1024,
			timeout: timeoutMs,
		});
		return {
			exit_code: 0,
			all_ok: parseOutcome(out),
			elapsed_ms: Date.now() - started,
			stdout_tail: out.slice(-4000),
		};
	} catch (e) {
		const text = `${e.stdout || ""}\n${e.stderr || ""}`;
		return {
			exit_code: e.status ?? 1,
			all_ok: parseOutcome(text),
			elapsed_ms: Date.now() - started,
			stdout_tail: text.slice(-4000),
			error: String(e.message || e).slice(0, 500),
		};
	}
}

function runScript(absPath, { retries }) {
	let last = runScriptOnce(absPath, 45 * 60 * 1000);
	for (let r = 0; r < retries && last.exit_code !== 0 && last.all_ok !== true; r++) {
		const retry = runScriptOnce(absPath, 45 * 60 * 1000);
		last = { ...retry, retried: r + 1 };
	}
	return last;
}

function filterScripts(scripts, grep) {
	if (!grep) {
		return scripts;
	}
	const g = grep.toLowerCase();
	return scripts.filter((s) => s.toLowerCase().includes(g));
}

function schedule(scripts, opts) {
	const fast = [];
	const serial = [];
	for (const rel of scripts) {
		const tags = tagsForScript(rel);
		if (opts.serial || tags.includes("SERIAL") || tags.includes("ACCOUNTING") || tags.includes("ROLLBACK")) {
			serial.push(rel);
		} else if (tags.includes("FAST") || tags.includes("UI_ONLY")) {
			fast.push(rel);
		} else {
			serial.push(rel);
		}
	}
	if (opts.serial) {
		return { parallelBatch: [], serialQueue: [...fast, ...serial] };
	}
	return { parallelBatch: fast, serialQueue: serial };
}

async function runParallel(batch, jobs, retries) {
	const results = new Map();
	let idx = 0;
	async function worker() {
		while (idx < batch.length) {
			const i = idx++;
			const rel = batch[i];
			const abs = path.join(ROOT, rel);
			results.set(rel, runScript(abs, { retries }));
		}
	}
	const workers = Array.from({ length: Math.min(jobs, batch.length) }, () => worker());
	await Promise.all(workers);
	return results;
}

const opts = parseArgs(process.argv);
const allDiscovered = discoverScripts(ROOT);
const registry = registryByScript();
const scripts = filterScripts(
	allDiscovered.filter((rel) => registry.has(rel) || true),
	opts.grep
);

const { parallelBatch, serialQueue } = schedule(scripts, opts);
const rows = [];
const startedAll = Date.now();

if (parallelBatch.length && opts.parallel) {
	const parallelResults = await runParallel(parallelBatch, opts.jobs, opts.retries);
	for (const rel of parallelBatch) {
		const r = parallelResults.get(rel);
		rows.push({
			script: rel,
			tags: tagsForScript(rel),
			...r,
			mode: "parallel",
		});
	}
} else if (parallelBatch.length) {
	for (const rel of parallelBatch) {
		const r = runScript(path.join(ROOT, rel), { retries: opts.retries });
		rows.push({ script: rel, tags: tagsForScript(rel), ...r, mode: "serial" });
	}
}

for (const rel of serialQueue) {
	const r = runScript(path.join(ROOT, rel), { retries: opts.retries });
	rows.push({ script: rel, tags: tagsForScript(rel), ...r, mode: "serial" });
}

const passed = rows.filter((r) => r.exit_code === 0 && r.all_ok !== false).length;
const summary = {
	total: rows.length,
	passed,
	failed: rows.length - passed,
	duration_ms: Date.now() - startedAll,
	options: opts,
	rows: rows.map(({ stdout_tail, error, ...rest }) => ({
		...rest,
		error: error || null,
	})),
};
console.log(JSON.stringify(summary, null, 2));
process.exit(passed === rows.length ? 0 : 1);
