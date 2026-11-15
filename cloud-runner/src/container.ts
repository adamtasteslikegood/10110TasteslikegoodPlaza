import { Files, SandboxFileError } from "@cloudflare/sandbox"
import { MAX_PAYLOAD_BYTES } from "./events"

// Shell snippets and helpers for the Workspace's container, after the guide's
// AgentSandbox. Everything a run leaves behind lives in taskDirectory, outside
// the clone, so `git diff` never sees it.
export const repositoryDirectory = "/workspace/repo"
export const taskDirectory = "/workspace/task"
export const eventsPath = `${taskDirectory}/stdout.log`
export const stderrPath = `${taskDirectory}/stderr.log`
export const exitCodePath = `${taskDirectory}/exit-code`
export const pidPath = `${taskDirectory}/pid`

const caPath = "/etc/cloudflare/certs/cloudflare-containers-ca.crt"
// The CA alone replaces the system trust store. This works because
// Outbound intercepts every HTTPS request from the container.
export const trustEnv = {
	NODE_EXTRA_CA_CERTS: caPath,
	GIT_SSL_CAINFO: caPath,
	CURL_CA_BUNDLE: caPath,
	SSL_CERT_FILE: caPath,
}

// Starts the command detached, in a session of its own, and returns at once.
// The session leader is a shell that outlives the exec and the object: it
// writes its process ID (the group ID) when it starts and the command's exit
// code when it ends, each by temp file and rename. It catches TERM (and does
// nothing), so a stop's TERM reaches the command while the leader stays to
// record the exit code; KILL ends the leader too and leaves no exit code.
export const taskScript = `dir=$1; shift
exec setsid -f sh -c 'trap : TERM
echo "$$ $(cat /proc/sys/kernel/random/boot_id)" >"$0/pid.tmp" && mv "$0/pid.tmp" "$0/pid"
"$@" >"$0/stdout.log" 2>"$0/stderr.log"
echo "$?" >"$0/exit-code.tmp" && mv "$0/exit-code.tmp" "$0/exit-code"' "$dir" "$@" </dev/null >/dev/null 2>&1`

// What the pid file holds: the group ID and the boot it started in.
export type Task = { pid: number; boot: string }

export function parseTask(text: string): Task | undefined {
	const match = /^(\d+) (\S+)\s*$/.exec(text)
	return match === null ? undefined : { pid: Number(match[1]), boot: match[2] }
}

// Succeeds while a process of group $1 that is not a zombie runs, and only in
// boot $2. kill -0 would also succeed on a zombie no one reaps.
export const taskAliveScript = `pgid=$1
[ "$2" = "$(cat /proc/sys/kernel/random/boot_id)" ] || exit 1
for s in /proc/[0-9]*/stat; do
	read -r line <"$s" 2>/dev/null || continue
	set -- \${line##*) }
	[ "$1" != Z ] && [ "$3" = "$pgid" ] && exit 0
done
exit 1`

// Sends signal $3 to process group $1 when it started in boot $2. The image's
// sh is dash, whose kill takes no "--": "-$1" right after the signal names a group.
export const signalScript = `[ "$2" = "$(cat /proc/sys/kernel/random/boot_id)" ] && kill -"$3" "-$1"`

// Up to $3 bytes of file $2 from byte $1 (1-based): a ranged read. A file not
// yet created reads as empty; one that can't be read fails.
export const chunkScript = `[ -e "$2" ] || exit 0
[ -r "$2" ] || { echo "cannot read $2" >&2; exit 1; }
tail -c +"$1" "$2" | head -c "$3"`

// For a line longer than one chunk: its length in bytes from byte $1 of file
// $2, and 1 when it already ends with a newline.
export const longLineScript = `n=$(tail -c +"$1" "$2" | head -n 1 | wc -c)
t=$(tail -c +"$1" "$2" | head -n 1 | tail -c 1 | wc -l)
echo "$n $t"`

export const MAX_DIFF_BYTES = 1024 * 1024

// The diff against HEAD, new files included, read-only for the clone: the
// intent-to-add goes to a copy of the index, so a diff during a run never takes
// the clone's index.lock. Prints at most MAX_DIFF_BYTES + 1 bytes, so a cut
// diff shows as one byte too many; git's SIGPIPE from head (141) is not an error.
export const diffScript = `tmp=$(mktemp) || exit 1
trap 'rm -f "$tmp" "$tmp.rc"' EXIT
index="$(git rev-parse --git-dir)/index" || exit 1
if [ -f "$index" ]; then cp "$index" "$tmp" || exit 1; else rm -f "$tmp"; fi
export GIT_INDEX_FILE="$tmp" GIT_OPTIONAL_LOCKS=0
git add --intent-to-add . || exit 1
{ git diff HEAD; echo "$?" >"$tmp.rc"; } | head -c ${MAX_DIFF_BYTES + 1}
rc=$(cat "$tmp.rc")
[ "$rc" = 0 ] || [ "$rc" = 141 ] || exit "$rc"`

export const diffCutLine = "[The diff is longer than 1 MiB and was cut here.]\n"

// The diff as text, at most MAX_DIFF_BYTES of it. A longer one is cut after
// its last whole line within the limit and ends with diffCutLine.
export function capDiff(stdout: Uint8Array): string {
	const decoder = new TextDecoder()

	if (stdout.byteLength <= MAX_DIFF_BYTES) {
		return decoder.decode(stdout)
	}

	const head = stdout.subarray(0, MAX_DIFF_BYTES)
	const end = head.lastIndexOf(0x0a)
	const kept = decoder.decode(end < 0 ? head : head.subarray(0, end + 1))
	return `${kept}${kept.endsWith("\n") ? "" : "\n"}${diffCutLine}`
}

export type CommandResult = { exitCode: number; stdout: string; stderr: string }

// How long each kind of exec may take before it is aborted.
export const execTimeout = { short: 30 * 1000, clone: 10 * 60 * 1000, push: 5 * 60 * 1000, restore: 5 * 60 * 1000 }

type Output = { exitCode: number; stdout: ArrayBuffer | Uint8Array; stderr: ArrayBuffer | Uint8Array }

// Runs a command to its end, or rejects once timeoutMs has passed. The signal
// stops the process; the race makes sure the promise ends even if it does not.
export async function execOutput(container: Container, command: string[], options: ContainerExecOptions, timeoutMs: number): Promise<Output> {
	const signal = AbortSignal.timeout(timeoutMs)
	const name = command[0] === "/bin/sh" && command[1] === "-c" ? `sh ${command[3] ?? ""}`.trim() : command.slice(0, 2).join(" ")
	const aborted = new Promise<never>((_resolve, reject) => {
		signal.addEventListener("abort", () => reject(new Error(`${name} timed out after ${timeoutMs / 1000} s`)), { once: true })
	})
	aborted.catch(() => undefined) // a timer that fires after the command ended is no error

	return Promise.race([(async () => (await container.exec(command, { ...options, signal })).output())(), aborted])
}

export async function run(container: Container, command: string[], cwd: string, env: Record<string, string>, timeoutMs = execTimeout.short): Promise<CommandResult> {
	const output = await execOutput(container, command, { cwd, env }, timeoutMs)
	const decoder = new TextDecoder()
	return { exitCode: output.exitCode, stdout: decoder.decode(output.stdout), stderr: decoder.decode(output.stderr) }
}

export async function runBytes(container: Container, command: string[], cwd = "/", env: Record<string, string> = {}, timeoutMs = execTimeout.short): Promise<Uint8Array> {
	const output = await execOutput(container, command, { cwd, env }, timeoutMs)

	if (output.exitCode !== 0) {
		throw new Error(`${command[0]} exited with ${output.exitCode}: ${tail(new TextDecoder().decode(output.stderr))}`)
	}

	return new Uint8Array(output.stdout)
}

export async function readOptionalText(files: Files, path: string): Promise<string | undefined> {
	try {
		return await (await files.readFile(path)).text()
	} catch (error) {
		if (SandboxFileError.is(error) && error.code === "ENOENT") {
			return undefined
		}

		throw error
	}
}

export async function* readLines(body: ReadableStream<Uint8Array> | null): AsyncGenerator<string> {
	if (body === null) {
		return
	}

	const decoder = new TextDecoder()
	let buffered = ""

	for await (const chunk of body) {
		buffered += decoder.decode(chunk, { stream: true })
		const lines = buffered.split("\n")
		buffered = lines.pop() ?? ""
		yield* lines
	}

	buffered += decoder.decode()

	if (buffered !== "") {
		yield buffered
	}
}

// The complete lines in a chunk (each without its "\n") and the bytes they
// take, newlines included. Bytes after the last newline are left for later.
export function completeLines(chunk: Uint8Array): { lines: Uint8Array[]; consumed: number } {
	const end = chunk.lastIndexOf(0x0a)
	const lines: Uint8Array[] = []
	let start = 0

	for (let i = 0; i <= end; i++) {
		if (chunk[i] === 0x0a) {
			lines.push(chunk.subarray(start, i))
			start = i + 1
		}
	}

	return { lines, consumed: end + 1 }
}

// The `type` of a line too large to keep, read from its first bytes.
export function leadingType(head: string): string {
	return /^\s*\{\s*"type"\s*:\s*"([^"\\]{1,100})"/.exec(head)?.[1] ?? "unknown"
}

// What one line of Claude Code's output adds to the event log, if anything.
export function lineEvent(line: Uint8Array, parse: (text: string) => { type: string; payload: unknown } | undefined): { type: string; payload: unknown } | undefined {
	const decoder = new TextDecoder()

	if (line.byteLength > MAX_PAYLOAD_BYTES) {
		return { type: leadingType(decoder.decode(line.subarray(0, 256))), payload: { truncated: true, bytes: line.byteLength } }
	}

	return parse(decoder.decode(line))
}

export function tail(text: string, chars = 2000): string {
	return text.slice(-chars)
}
