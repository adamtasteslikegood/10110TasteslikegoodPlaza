#!/usr/bin/env node
// Stage 1 acceptance checks (design §8) against a deployed runner with the
// test-only routes on. Usage:
//
//   RUNNER_CALLER_SECRET=... TEST_REPO=https://github.com/OWNER/REPO TEST_BRANCH=BRANCH \
//     [AI_GATEWAY_TOKEN=... GITHUB_TOKEN=...] [ONLY=H,1,T,3,4] node scripts/acceptance.mjs <url>
//
// Prints one line per check, `PASS n name` or `FAIL n name: why`, plus NOTE
// lines with what was observed, and exits 1 on any FAIL. The two tokens are
// optional and used only to look for them in the container (check 4). No
// secret is printed: every line goes through redact() first. The workspaces
// acc-<random>-a and -b are deleted at the end, whatever happened.
import { execFile } from "node:child_process"
import { randomBytes } from "node:crypto"
import { promisify } from "node:util"

const runFile = promisify(execFile)
const [base] = process.argv.slice(2)
const secret = process.env.RUNNER_CALLER_SECRET ?? ""
const repo = process.env.TEST_REPO ?? ""
const branch = process.env.TEST_BRANCH ?? ""
const only = process.env.ONLY ? new Set(process.env.ONLY.split(",").map((s) => s.trim())) : undefined
const secrets = [secret, process.env.AI_GATEWAY_TOKEN ?? "", process.env.GITHUB_TOKEN ?? ""].filter((s) => s.length >= 8)
const patterns = [/ghp_[A-Za-z0-9]{10,}/, /github_pat_[A-Za-z0-9_]{10,}/, /sk-ant-[A-Za-z0-9_-]{10,}/]

if (!base || !secret || !/^https:\/\/github\.com\/[^/]+\/[^/]+$/.test(repo) || !branch) {
	console.error("Usage: RUNNER_CALLER_SECRET=... TEST_REPO=https://github.com/OWNER/REPO TEST_BRANCH=BRANCH node scripts/acceptance.mjs <url>")
	process.exit(2)
}

// Runs push to TEST_BRANCH: never let them touch a default branch.
if (["main", "master", "dev", "develop"].includes(branch)) {
	console.error(`Refusing TEST_BRANCH=${branch}: use a dedicated branch`)
	process.exit(2)
}

const id = randomBytes(3).toString("hex")
const A = `acc-${id}-a`
const B = `acc-${id}-b`
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
let failed = 0

function redact(text) {
	let out = String(text)
	for (const s of secrets) out = out.split(s).join("[secret]")
	for (const p of patterns) out = out.replace(new RegExp(p.source, "g"), "[token-like]")
	return out
}

const say = (line) => console.log(redact(line))
const note = (text) => say(`NOTE ${text}`)

async function api(method, path, body, timeoutMs = 180_000) {
	const response = await fetch(`${base.replace(/\/$/, "")}${path}`, {
		method,
		headers: { authorization: `Bearer ${secret}`, ...(body === undefined ? {} : { "content-type": "application/json" }) },
		body: body === undefined ? undefined : JSON.stringify(body),
		signal: AbortSignal.timeout(timeoutMs),
	})
	const text = await response.text()
	let json
	try {
		json = JSON.parse(text)
	} catch {
		json = undefined
	}
	return { status: response.status, text, json }
}

function expectStatus(answer, status, what) {
	if (answer.status !== status) throw new Error(`${what} answered ${answer.status} ${answer.text.slice(0, 300)}`)
	return answer
}

// No retry: a new instance is probed until it answers before the clone (Copilot C9).
async function create(name) {
	return expectStatus(await api("PUT", `/workspaces/${name}`, { repo, branch }), 200, `PUT ${name}`).json
}

const status = async (name) => expectStatus(await api("GET", `/workspaces/${name}`), 200, `GET ${name}`).json

async function startRun(name, prompt, maxTurns) {
	return expectStatus(await api("POST", `/workspaces/${name}/runs`, { prompt, maxTurns }), 202, `POST ${name}/runs`).json.run
}

// Polls until the run is no longer running, up to limitMs.
async function waitEnd(name, limitMs = 10 * 60_000) {
	const deadline = Date.now() + limitMs
	for (;;) {
		const s = await status(name)
		if (s.state !== "running") return s
		if (Date.now() > deadline) throw new Error(`${name} still running after ${limitMs / 1000} s`)
		await sleep(5000)
	}
}

async function eventsAfter(name, after) {
	return expectStatus(await api("GET", `/workspaces/${name}/events?after=${after}`), 200, `events ${name}`).json
}

// Every event from after on, page by page, bounded.
async function allEvents(name, after = 0) {
	const events = []
	for (let page = 0; page < 1000; page++) {
		const read = await eventsAfter(name, after)
		events.push(...read.events)
		if (read.events.length === 0 || read.next === after) return events
		after = read.next
	}
	throw new Error("events did not end after 1000 pages")
}

const lastSeq = async (name) => (await allEvents(name)).at(-1)?.seq ?? 0

// Runs argv in the workspace's container through the test-only route: as the
// agent user, or as root to look at what the agent cannot.
async function inBox(name, argv, root = false) {
	return expectStatus(await api("POST", `/workspaces/${name}/exec`, { argv, root }, 60_000), 200, `exec ${argv[0]}`).json
}

const nodeIn = (name, code) => inBox(name, ["node", "-e", code])

// What a run's result event and events say about its cost and time.
function runFacts(events, runNumber) {
	const mine = events.filter((e) => e.run === runNumber)
	const result = mine.filter((e) => e.type === "result").at(-1)?.payload
	const first = mine[0]?.at
	const last = mine.at(-1)?.at
	const wall = first && last ? (Date.parse(last) - Date.parse(first)) / 1000 : undefined
	return { result, wall }
}

function costNote(label, events, runNumber) {
	const { result, wall } = runFacts(events, runNumber)
	const u = result?.usage ?? {}
	note(
		`cost ${label} run ${runNumber}: events span ${wall ?? "?"} s; result duration_ms=${result?.duration_ms} num_turns=${result?.num_turns} ` +
			`input=${u.input_tokens} output=${u.output_tokens} cache_read=${u.cache_read_input_tokens} cache_write=${u.cache_creation_input_tokens} ` +
			`total_cost_usd=${result?.total_cost_usd} model=${Object.keys(result?.modelUsage ?? {}).join("+") || "?"}`,
	)
}

function scan(text, where) {
	for (const [i, s] of secrets.entries()) if (text.includes(s)) throw new Error(`secret #${i + 1} found in ${where}`)
	for (const p of patterns) if (p.test(text)) throw new Error(`a match for ${p.source.slice(0, 12)}... found in ${where}`)
}

async function check(n, name, body) {
	if (only && !only.has(String(n))) return
	try {
		await body()
		say(`PASS ${n} ${name}`)
	} catch (error) {
		failed += 1
		say(`FAIL ${n} ${name}: ${error instanceof Error ? error.message : error}`)
	}
}

const shared = { check1Events: [] }

async function main() {
	note(`workspaces ${A} and ${B}, branch ${branch}`)
	await noteMain("before the checks")
	const made = await create(A)
	note(`PUT ${A}: generation ${made.generation}, state ${made.state}`)

	await check("H", "claude --help in the image lists --session-id, --resume, --max-turns", async () => {
		const help = await inBox(A, ["claude", "--help"])
		const version = await inBox(A, ["claude", "--version"])
		note(`claude --version: ${version.stdout.trim()}`)
		// A hidden flag is accepted; an unknown one is refused. With --print and empty stdin neither reaches the model:
		// option parsing fails first, or the CLI stops on the missing prompt. (--version would exit before parsing.)
		const flag = (f) => inBox(A, ["/bin/sh", "-c", `timeout 20 claude -p ${f} < /dev/null`])
		const hidden = await flag("--max-turns 1")
		const unknown = await flag("--no-such-flag-xyz")
		note(`claude -p --max-turns 1 </dev/null: exit ${hidden.exitCode} ${(hidden.stdout + hidden.stderr).trim().split("\n")[0]}`)
		note(`claude -p --no-such-flag-xyz </dev/null: exit ${unknown.exitCode} ${(unknown.stdout + unknown.stderr).trim().split("\n")[0]}`)
		const missing = ["--session-id", "--resume", "--max-turns"].filter((flag) => !help.stdout.includes(flag))
		if (missing.length) throw new Error(`not in --help: ${missing.join(" ")}`)
	})

	await check(1, "a prompt runs to completion, writes and pushes NOTES.md", async () => {
		const runNumber = await startRun(A, `Add a file NOTES.md with one sentence about this repository (mention the id ${id}) and commit it.`, 10)
		const s = await waitEnd(A)
		const events = await allEvents(A)
		shared.check1Events = events.filter((e) => e.run === runNumber)
		costNote("check 1", events, runNumber)
		if (s.state !== "succeeded") throw new Error(`state ${s.state}: ${s.error ?? ""}`)
		if (!shared.check1Events.some((e) => e.type === "result")) throw new Error("no result event")
		const wrote = shared.check1Events.some(
			(e) => e.type === "assistant" && (e.payload?.message?.content ?? []).some((c) => c.type === "tool_use" && JSON.stringify(c.input ?? {}).includes("NOTES.md")),
		)
		if (!wrote) throw new Error("no tool_use event names NOTES.md")
		if (!s.pushed?.commit) throw new Error(`no pushed.commit (pushError: ${s.pushError ?? "none"})`)
		const remote = await runFile("git", ["ls-remote", repo, `refs/heads/${branch}`], { timeout: 60_000 })
		const head = remote.stdout.split(/\s+/)[0]
		note(`pushed.commit ${s.pushed.commit}; ls-remote ${head}`)
		if (head !== s.pushed.commit) throw new Error(`ls-remote shows ${head}, not ${s.pushed.commit}`)
	})

	// After a run, so the task directory exists. No model call.
	await check("U", "the agent is not root, and /workspace and the task directory are out of its reach (PLZG-311)", async () => {
		const who = await inBox(A, ["/bin/sh", "-c", "id -u; id -un; grep NoNewPrivs /proc/self/status"])
		const [uid, user, noNewPrivs] = who.stdout.trim().split("\n")
		note(`an exec as the agent: uid ${uid} (${user}), ${noNewPrivs}`)
		if (!/^[1-9]\d*$/.test(uid ?? "")) throw new Error(`the agent's uid is ${JSON.stringify(uid)}`)
		if (noNewPrivs !== "NoNewPrivs:\t1") throw new Error(`no-new-privs is not set: ${JSON.stringify(noNewPrivs)}`)
		for (const attempt of ["ls /workspace/task", "touch /workspace/task/exit-code", "touch /workspace/planted", "mv /workspace/task /workspace/gone"]) {
			const tried = await inBox(A, ["/bin/sh", "-c", attempt])
			if (tried.exitCode === 0) throw new Error(`the agent could: ${attempt}`)
		}
		const owners = await inBox(A, ["stat", "-c", "%n %U %a", "/workspace", "/workspace/task", "/workspace/task/exit-code", "/workspace/repo"], true)
		note(`owners: ${owners.stdout.trim().split("\n").join("; ")}`)
		const lines = owners.stdout.trim().split("\n")
		const wanted = [/^\/workspace root 755$/, /^\/workspace\/task root 700$/, /^\/workspace\/task\/exit-code root \d+$/, new RegExp(`^/workspace/repo ${user} \\d+$`)]
		if (lines.length !== wanted.length || !wanted.every((w, i) => w.test(lines[i]))) throw new Error(`unexpected owners: ${owners.stdout} ${owners.stderr}`)
	})

	await check("T", "maxTurns 1 stops a run that needs two tool calls (result subtype error_max_turns)", async () => {
		const runNumber = await startRun(
			A,
			"Use your Bash tool to run `date`. Then, in a second and separate Bash call, run `uname -a`. Then reply with both outputs.",
			1,
		)
		const s = await waitEnd(A)
		const events = (await allEvents(A)).filter((e) => e.run === runNumber)
		costNote("check T", events, runNumber)
		const result = events.filter((e) => e.type === "result").at(-1)?.payload
		const tools = events.filter((e) => e.type === "assistant").flatMap((e) => (e.payload?.message?.content ?? []).filter((c) => c.type === "tool_use"))
		note(`check T: state ${s.state}, error ${JSON.stringify(s.error ?? null)}, result subtype ${result?.subtype}, is_error ${result?.is_error}, num_turns ${result?.num_turns}, tool calls ${tools.length}`)
		if (result?.subtype !== "error_max_turns") throw new Error(`result subtype ${result?.subtype}, not error_max_turns`)
		if (s.state !== "failed") throw new Error(`state ${s.state}, not failed`)
	})

	await check(2, "events read twice agree, after=next never repeats, a second start answers 409", async () => {
		const start = await lastSeq(A)
		const runNumber = await startRun(A, "Run the shell command `sleep 45` with your Bash tool, then reply with the single word done.", 4)
		const busy = await api("POST", `/workspaces/${A}/runs`, { prompt: "second", maxTurns: 1 })
		if (busy.status !== 409) throw new Error(`a second start answered ${busy.status}, not 409`)
		await sleep(15_000)
		const first = await eventsAfter(A, start)
		const second = await eventsAfter(A, start)
		const one = first.events.map((e) => e.seq)
		const two = second.events.map((e) => e.seq)
		if (one.length === 0) throw new Error("no events 15 s into the run")
		if (JSON.stringify(two.slice(0, one.length)) !== JSON.stringify(one)) throw new Error(`second read ${two.join(",")} does not start with ${one.join(",")}`)
		const seen = []
		let after = start
		const deadline = Date.now() + 5 * 60_000
		for (;;) {
			const read = await eventsAfter(A, after)
			seen.push(...read.events.map((e) => e.seq))
			after = read.next
			const s = await status(A)
			if (s.state !== "running" && read.events.length === 0) break
			if (Date.now() > deadline) throw new Error("run did not end in 5 min")
			await sleep(3000)
		}
		const events = await allEvents(A, start)
		const full = events.map((e) => e.seq)
		if (new Set(seen).size !== seen.length) throw new Error("a seq was repeated")
		if (JSON.stringify(seen) !== JSON.stringify(full)) throw new Error(`incremental reads ${seen.length} events, full read ${full.length}`)
		costNote("check 2", events, runNumber)
		note(`check 2: ${seen.length} events read incrementally, same as one full read; run ended ${(await status(A)).state}`)
	})

	await check(3, "egress: unlisted host 403, plain HTTP refused, push elsewhere refused, own repository reachable, no raw TCP, no direct UDP (DNS name leakage not tested)", async () => {
		const get = await nodeIn(A, "fetch('https://example.com/').then(r=>console.log(r.status),e=>console.log('error',e.cause?.code??e.message))")
		if (get.stdout.trim() !== "403") throw new Error(`https://example.com answered ${get.stdout.trim()} ${get.stderr.slice(0, 200)}`)
		const plain = await nodeIn(A, "fetch('http://example.com/').then(r=>console.log(r.status),e=>console.log('error',e.cause?.code??e.message))")
		note(`http://example.com: ${plain.stdout.trim()}`)
		if (plain.stdout.trim() === "200") throw new Error("plain HTTP reached example.com")
		// registry.npmjs.org is on the allow list over HTTPS; the policy accepts https:// only.
		const npmHttps = await nodeIn(A, "fetch('https://registry.npmjs.org/left-pad').then(r=>console.log(r.status),e=>console.log('error',e.cause?.code??e.message))")
		const npmHttp = await nodeIn(A, "fetch('http://registry.npmjs.org/left-pad').then(r=>console.log(r.status),e=>console.log('error',e.cause?.code??e.message))")
		note(`https://registry.npmjs.org/left-pad: ${npmHttps.stdout.trim()}; http://registry.npmjs.org/left-pad: ${npmHttp.stdout.trim()}`)
		if (npmHttps.stdout.trim() !== "200") throw new Error(`https://registry.npmjs.org answered ${npmHttps.stdout.trim()}: the allowed host is not reachable, so the HTTP refusal proves nothing`)
		if (npmHttp.stdout.trim() !== "403") throw new Error(`http://registry.npmjs.org answered ${npmHttp.stdout.trim()}, not 403`)
		// The bare root was refused before PLZG-311: it reached the Worker as "https://registry.npmjs.org", with no slash.
		const npmRoot = await nodeIn(A, "fetch('https://registry.npmjs.org').then(r=>console.log(r.status),e=>console.log('error',e.cause?.code??e.message))")
		note(`https://registry.npmjs.org (bare root): ${npmRoot.stdout.trim()}`)
		if (npmRoot.stdout.trim() !== "200") throw new Error(`the bare root https://registry.npmjs.org answered ${npmRoot.stdout.trim()}, not 200`)
		const other = await inBox(A, ["git", "push", "https://github.com/octocat/Hello-World", "HEAD:refs/heads/x"])
		note(`push to octocat/Hello-World: exit ${other.exitCode}, ${other.stderr.trim().split("\n").at(-1)}`)
		if (other.exitCode === 0) throw new Error("a push to another repository succeeded")
		const own = await inBox(A, ["git", "ls-remote", "origin"])
		if (own.exitCode !== 0) throw new Error(`git ls-remote origin exited ${own.exitCode}: ${own.stderr.slice(0, 200)}`)
		for (const port of [53, 22, 25, 8080]) {
			const tcp = await nodeIn(
				A,
				`const s=require('net').connect(${port},'1.1.1.1');s.setTimeout(5000);s.on('connect',()=>{console.log('connected');s.destroy()});s.on('timeout',()=>{console.log('timeout');s.destroy()});s.on('error',e=>console.log('error',e.code))`,
			)
			note(`raw TCP 1.1.1.1:${port}: ${tcp.stdout.trim()}`)
			if (tcp.stdout.includes("connected")) throw new Error(`raw TCP to 1.1.1.1:${port} connected`)
		}
		// The platform answers every UDP/53 query in the container with a local
		// stub (one synthetic address for any name, from any destination). A real
		// resolver would answer differently from an unroutable TEST-NET address
		// and would say NXDOMAIN for a .invalid name.
		const dns = (server, host) =>
			nodeIn(
				A,
				`const r=new (require('dns').promises.Resolver)({timeout:3000,tries:1});r.setServers(['${server}']);r.resolve4('${host}').then(a=>console.log('answered',a.join(',')),e=>console.log('error',e.code))`,
			).then((r) => r.stdout.trim())
		const viaPublic = await dns("1.1.1.1", "example.com")
		const viaTestNet = await dns("192.0.2.1", "example.com")
		const viaGoogle = await dns("8.8.8.8", "example.com")
		note(`UDP DNS example.com via 8.8.8.8: ${viaGoogle}`)
		const resolv = await inBox(A, ["cat", "/etc/resolv.conf"])
		note(`/etc/resolv.conf: ${JSON.stringify(resolv.stdout.trim())}`)
		const invalid = await dns("1.1.1.1", `nx-${id}.example.invalid`)
		note(`UDP DNS example.com via 1.1.1.1: ${viaPublic}; via 192.0.2.1 (TEST-NET): ${viaTestNet}; nx-${id}.example.invalid via 1.1.1.1: ${invalid}`)
		if (invalid.includes("ENOTFOUND")) throw new Error("a .invalid name got NXDOMAIN: a real resolver answered over UDP")
		if (viaPublic !== viaTestNet) throw new Error("1.1.1.1 and an unroutable address answered differently: UDP/53 reached a real resolver")
		const udp = await nodeIn(
			A,
			"const s=require('dgram').createSocket('udp4');const b=Buffer.alloc(48);b[0]=0x1b;s.on('message',m=>{console.log('reply',m.length);s.close()});s.send(b,123,'162.159.200.1');setTimeout(()=>{console.log('no reply');s.close()},3000)",
		)
		note(`UDP NTP to 162.159.200.1:123: ${udp.stdout.trim()}`)
		if (udp.stdout.includes("reply ")) throw new Error("a UDP NTP query to 162.159.200.1 got a reply")
		const odd = await nodeIn(
			A,
			"const s=require('dgram').createSocket('udp4');s.on('message',m=>{console.log('reply',m.length);s.close()});s.send(Buffer.from('ping'),9999,'1.1.1.1');setTimeout(()=>{console.log('no reply');s.close()},3000)",
		)
		note(`UDP to 1.1.1.1:9999: ${odd.stdout.trim()}`)
		if (odd.stdout.includes("reply ")) throw new Error("a UDP datagram to 1.1.1.1:9999 got a reply")
		const lookup = await nodeIn(A, "require('dns').lookup('example.com',(e,a)=>console.log(e?'error '+e.code:'resolved '+a))")
		note(`system resolver for example.com: ${lookup.stdout.trim()}`)
	})

	await check(4, "no credential in env, any process's environ, .git/config, ~/.gitconfig, home, /workspace or the workspace's events", async () => {
		if (secrets.length < 3) note(`only ${secrets.length} of 3 secret values given; the token patterns are checked anyway`)
		const looked = await inBox(A, ["/bin/sh", "-c", "env; cat .git/config; cat ~/.gitconfig 2>/dev/null; ls -la ~ /workspace"])
		scan(looked.stdout + looked.stderr, "the container")
		if (!looked.stdout.includes("[remote \"origin\"]")) throw new Error("the output has no .git/config: the scan saw too little")
		const rootHome = await inBox(A, ["/bin/sh", "-c", "cat /root/.gitconfig 2>/dev/null; ls -la /root"], true)
		scan(rootHome.stdout + rootHome.stderr, "root's home")
		// As root and as the agent: a user without CAP_SYS_PTRACE reads only its own processes' environ.
		const environScript = "for f in /proc/[0-9]*/environ; do [ -r \"$f\" ] || continue; echo \"== $f\"; tr '\\000' '\\n' < \"$f\" 2>/dev/null; done"
		const environs = [await inBox(A, ["/bin/sh", "-c", environScript], true), await inBox(A, ["/bin/sh", "-c", environScript])]
		const environ = { stdout: environs.map((e) => e.stdout).join(""), stderr: environs.map((e) => e.stderr).join("") }
		scan(environ.stdout + environ.stderr, "a process's environ")
		const processes = (environ.stdout.match(/^== /gm) ?? []).length
		if (processes < 2) throw new Error(`only ${processes} /proc/*/environ files read: the scan saw too little`)
		const events = await allEvents(A)
		if (events.length === 0) throw new Error("no events to scan")
		scan(JSON.stringify(events), "the workspace's events")
		note(`scanned ${looked.stdout.length} bytes of container output, the environ of ${processes} processes (${environ.stdout.length} bytes) and ${events.length} events (check 1's: ${shared.check1Events.length})`)
	})

	await check(5, "two workspaces run at once and do not see each other's files", async () => {
		await create(B)
		const prompt = "Reply with the single word ok. Do not use any tools."
		const [ra, rb] = await Promise.all([startRun(A, prompt, 2), startRun(B, prompt, 2)])
		const [sa, sb] = await Promise.all([status(A), status(B)])
		note(`right after both starts: ${A} ${sa.state}, ${B} ${sb.state}`)
		if (sa.state !== "running" || sb.state !== "running") throw new Error("the two runs were not running at the same time")
		const [ea, eb] = await Promise.all([waitEnd(A), waitEnd(B)])
		costNote("check 5 a", await allEvents(A), ra)
		costNote("check 5 b", await allEvents(B), rb)
		if (ea.state !== "succeeded" || eb.state !== "succeeded") throw new Error(`ended ${ea.state} (${ea.error ?? ""}) and ${eb.state} (${eb.error ?? ""})`)
		await inBox(A, ["/bin/sh", "-c", `echo ${id} > /workspace/only-in-a.txt`], true) // /workspace is root's
		const inA = await inBox(A, ["cat", "/workspace/only-in-a.txt"])
		const inB = await inBox(B, ["test", "-e", "/workspace/only-in-a.txt"])
		if (inA.stdout.trim() !== id) throw new Error("the file was not written in a")
		if (inB.exitCode === 0) throw new Error("b sees a's file")
	})

	await check(6, "after replace-instance the snapshot restores an uncommitted file", async () => {
		const r1 = await startRun(A, "Create a file scratch.txt containing 42 and do not commit it. Remember the word heliotrope.", 5)
		const s1 = await waitEnd(A)
		if (s1.state !== "succeeded") throw new Error(`the first run ended ${s1.state}: ${s1.error ?? ""}`)
		const before = await inBox(A, ["cat", "scratch.txt"])
		note(`scratch.txt before replacement: ${JSON.stringify(before.stdout.trim())}; pushError ${s1.pushError ?? "none"}`)
		const notices = (await allEvents(A)).filter((e) => e.run === r1 && e.type === "runner").map((e) => e.payload?.notice)
		note(`run ${r1} runner notices: ${notices.join(", ")}`)
		expectStatus(await api("POST", `/workspaces/${A}/replace-instance`), 200, "replace-instance")
		const r2 = await startRun(A, "What word did I ask you to remember, and what is in scratch.txt?", 4)
		const s2 = await waitEnd(A)
		const events = await allEvents(A)
		costNote("check 6", events, r2)
		const init = events.find((e) => e.run === r2 && e.type === "system")?.payload
		const init1 = events.find((e) => e.run === r1 && e.type === "system")?.payload
		const startedNote = events.filter((e) => e.type === "runner" && e.payload?.notice === "instance started").at(-1)?.payload
		const answer = s2.result ?? ""
		note(
			`check 6: restored=${s2.restored} uncommittedLost=${s2.uncommittedLost} instance note=${JSON.stringify(startedNote)}; ` +
				`session ${init1?.session_id === init?.session_id ? "same" : "different"} (${init?.session_id}); ` +
				`reports 42: ${/\b42\b/.test(answer)}; reports heliotrope: ${/heliotrope/i.test(answer)}; state ${s2.state}`,
		)
		note(`check 6 answer: ${JSON.stringify(answer.slice(0, 300))}`)
		const after = await inBox(A, ["cat", "scratch.txt"])
		if (s2.restored !== "snapshot") throw new Error(`restored is ${s2.restored}, not snapshot`)
		if (after.stdout.trim() !== "42") throw new Error(`scratch.txt after replacement: ${JSON.stringify(after.stdout.trim())} ${after.stderr.trim()}`)
	})

	await check(7, "stop interrupts a run; a replaced instance mid-run reports lost; both accept the next run", async () => {
		const long = "Run the shell command `sleep 120` with your Bash tool, then reply with the single word done."
		await startRun(A, long, 3)
		await sleep(20_000)
		const t = Date.now()
		const stopped = expectStatus(await api("POST", `/workspaces/${A}/stop`), 200, "stop").json
		note(`stop answered ${stopped.state} in ${(Date.now() - t) / 1000} s`)
		if (stopped.state !== "stopped") throw new Error(`stop left state ${stopped.state}`)
		await startRun(A, "Reply with the single word ok. Do not use any tools.", 2)
		expectStatus(await api("POST", `/workspaces/${A}/stop`), 200, "stop of the follow-up run")
		await startRun(A, long, 3)
		await sleep(20_000)
		expectStatus(await api("POST", `/workspaces/${A}/replace-instance`), 200, "replace-instance mid-run")
		const lost = await status(A)
		note(`after replace-instance mid-run: ${lost.state} (${lost.error ?? ""}), pushError ${lost.pushError ?? "none"}`)
		if (lost.state !== "lost") throw new Error(`state ${lost.state}, not lost`)
		const next = await api("POST", `/workspaces/${A}/runs`, { prompt: "Reply with the single word ok. Do not use any tools.", maxTurns: 2 })
		if (next.status !== 202) throw new Error(`the run after lost answered ${next.status}`)
		const s = await status(A)
		note(`run after lost: generation ${s.generation}, restored ${s.restored}, uncommittedLost ${s.uncommittedLost}`)
		expectStatus(await api("POST", `/workspaces/${A}/stop`), 200, "stop of the last run")
	})
}

// The runs push only to TEST_BRANCH; main must not move.
async function noteMain(when) {
	try {
		const remote = await runFile("git", ["ls-remote", repo, "refs/heads/main"], { timeout: 60_000 })
		note(`ls-remote main ${when}: ${remote.stdout.split(/\s+/)[0] || "(no main)"}`)
	} catch (error) {
		note(`ls-remote main ${when}: ${error instanceof Error ? error.message : error}`)
	}
}

async function cleanup() {
	for (const name of [A, B]) {
		try {
			const deleted = await api("DELETE", `/workspaces/${name}`)
			const after = await api("GET", `/workspaces/${name}`)
			note(`DELETE ${name}: ${deleted.status}; then GET ${after.status} ${after.text.trim().slice(0, 120)}`)
			if (![200, 204, 404].includes(deleted.status)) throw new Error(`DELETE answered ${deleted.status}`)
			if (after.json?.state !== "none") throw new Error(`after DELETE the state is ${after.json?.state}, not none`)
		} catch (error) {
			failed += 1
			say(`FAIL cleanup ${name}: ${error instanceof Error ? error.message : error}`)
		}
	}
}

try {
	await main()
	await noteMain("after the checks")
} catch (error) {
	failed += 1
	say(`FAIL setup: ${error instanceof Error ? error.message : error}`)
} finally {
	await cleanup()
}

process.exit(failed === 0 ? 0 : 1)
