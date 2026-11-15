// Spike C check (d): a detached task survives a Worker redeploy mid-run.
//
//   RUNNER_CALLER_SECRET=... TEST_REPO=https://github.com/OWNER/REPO TEST_BRANCH=cloud-runner/acceptance \
//     node scripts/redeploy.mjs <url>
//
// Run from cloud-runner/, logged in to wrangler, with Docker running (see README, "Deploy or redeploy"). It
// starts a `sleep 150` run, redeploys with `wrangler deploy -c wrangler.dev.jsonc` 20 s in, waits for the run
// to end, prints the task's exit-code file and deletes the workspace. It needs ALLOW_TEST_ROUTES (exec).
// The redeploy makes a new Worker version; nothing else on the account changes.
// It passes only when `wrangler deploy` succeeded and the version that takes
// all traffic changed (Copilot C7); scripts/redeploy-verdict.ts holds the rule.

import { execFile } from "node:child_process"
import { randomBytes } from "node:crypto"
import { promisify } from "node:util"
import { currentVersion, redeployPassed } from "./redeploy-verdict.ts"

const runFile = promisify(execFile)
const [base] = process.argv.slice(2)
const secret = process.env.RUNNER_CALLER_SECRET ?? ""
const repo = process.env.TEST_REPO ?? ""
const branch = process.env.TEST_BRANCH ?? ""
if (!base || !secret || !repo || !branch) {
	console.error("usage: RUNNER_CALLER_SECRET=... TEST_REPO=... TEST_BRANCH=... node scripts/redeploy.mjs <url>")
	process.exit(2)
}
if (["main", "master", "dev", "develop"].includes(branch)) {
	console.error(`refusing to run against branch ${branch}`)
	process.exit(2)
}

const headers = { authorization: `Bearer ${secret}`, "content-type": "application/json" }
const name = `redeploy-${randomBytes(3).toString("hex")}`
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const t0 = Date.now()
const at = () => `${((Date.now() - t0) / 1000).toFixed(0)}s`

async function call(method, path, body) {
	const answer = await fetch(base + path, { method, headers, body: body && JSON.stringify(body), signal: AbortSignal.timeout(180_000) })
	const text = await answer.text()
	try {
		return { status: answer.status, json: JSON.parse(text) }
	} catch {
		return { status: answer.status, json: undefined }
	}
}

// Any rejection is a failure: an exit code, a signal, a timeout or a spawn error.
const wrangler = (args, timeout) =>
	runFile("npx", ["wrangler", ...args, "-c", "wrangler.dev.jsonc"], { env: { ...process.env, CI: "1" }, maxBuffer: 64 << 20, timeout }).then(
		(done) => ({ ok: true, stdout: String(done.stdout ?? ""), code: 0 }),
		(error) => ({ ok: false, stdout: String(error?.stdout ?? ""), code: error?.code ?? "unknown" }),
	)
const version = async () => {
	const status = await wrangler(["deployments", "status", "--json"], 120_000)
	return status.ok ? currentVersion(status.stdout) : undefined
}

// Fails closed: with no known version before, nothing is started.
const versionBefore = await version()
console.log(at(), "version before", versionBefore)
if (versionBefore === undefined) {
	console.error("FAIL d could not read the current Worker version")
	process.exit(1)
}

let ok = false
try {
	console.log(at(), "PUT", (await call("PUT", `/workspaces/${name}`, { repo, branch })).status)
	const started = await call("POST", `/workspaces/${name}/runs`, {
		prompt: "Run the shell command `sleep 150` with your Bash tool, then reply with the single word done.",
		maxTurns: 3,
	})
	console.log(at(), "run", started.status, JSON.stringify(started.json))
	await sleep(20_000)
	const before = (await call("GET", `/workspaces/${name}`)).json
	console.log(at(), "before redeploy", before?.state, "generation", before?.generation)
	const deployed = await wrangler(["deploy"], 400_000)
	const versionAfter = await version()
	console.log(at(), "redeploy", deployed.ok ? "ok" : `failed (${deployed.code})`, "version after", versionAfter, "image", /skipping push|already exists/i.test(deployed.stdout) ? "unchanged" : "pushed or unknown")
	const mid = (await call("GET", `/workspaces/${name}`)).json
	console.log(at(), "after redeploy", mid?.state, "generation", mid?.generation)
	let ended
	for (let i = 0; i < 80; i++) {
		const s = (await call("GET", `/workspaces/${name}`)).json
		if (s?.state !== "running") {
			ended = s
			break
		}
		await sleep(5000)
	}
	console.log(at(), "ended", ended?.state, "generation", ended?.generation)
	const task = await call("POST", `/workspaces/${name}/exec`, { argv: ["/bin/sh", "-c", "cat /workspace/task/exit-code"] })
	const exitCode = task.json?.stdout?.trim()
	console.log(at(), "task exit-code file:", JSON.stringify(exitCode))
	const events = (await call("GET", `/workspaces/${name}/events?after=0`)).json?.events ?? []
	console.log("runner notices:", events.filter((e) => e.type === "runner").map((e) => e.payload?.notice).join(", "))
	const result = events.filter((e) => e.type === "result").at(-1)?.payload
	console.log("result: duration_ms", result?.duration_ms, "turns", result?.num_turns, "total_cost_usd", result?.total_cost_usd)
	ok = redeployPassed({ deployed: deployed.ok, versionBefore, versionAfter, before, mid, ended, exitCode })
} finally {
	const deleted = await call("DELETE", `/workspaces/${name}`)
	const after = (await call("GET", `/workspaces/${name}`)).json
	console.log(at(), "DELETE", deleted.status, "then state", after?.state)
}
console.log(ok ? "PASS d the run survived the redeploy on the same instance and wrote exit code 0" : "FAIL d")
process.exit(ok ? 0 : 1)
