import { Files, SandboxFileError } from "@cloudflare/sandbox"
import { MAX_PAYLOAD_BYTES } from "./events"
import { MAX_OUTPUT_BYTES } from "./runstate"

// Shell snippets and helpers for the Workspace's container, after the guide's
// AgentSandbox. Everything a run leaves behind lives in taskDirectory, outside
// the clone, so `git diff` never sees it.
export const repositoryDirectory = "/workspace/repo"
export const taskDirectory = "/workspace/task"
export const eventsPath = `${taskDirectory}/stdout.log`
export const stderrPath = `${taskDirectory}/stderr.log`
export const exitCodePath = `${taskDirectory}/exit-code`
export const pidPath = `${taskDirectory}/pid`

// The agent is this user, never root (PLZG-311). The runner's own commands run
// as root, the user every exec gets by default; the clone and the agent's home
// are the agent's, and /workspace and the task directory are root's.
export const agentUser = "agent"
export const agentHome = "/home/agent"

// argv as the agent user. no-new-privs keeps a setuid binary from giving the
// privileges back. Git in the clone always runs this way: the clone's config,
// hooks and drivers are the agent's to write, so root must never run them.
export const asAgent = (argv: string[]): string[] => ["setpriv", `--reuid=${agentUser}`, `--regid=${agentUser}`, "--init-groups", "--no-new-privs", "--", ...argv]

// What the image writes at layoutPath: who owns what in it. A snapshot holds a
// whole root filesystem, so one taken from an image with another mark (or none:
// the agent was root then) is not restored. Change both this and the Dockerfile.
export const layoutPath = "/etc/plaza-runner-layout"
export const imageLayout = "2"

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
// stdout.log keeps at most this many bytes: one past the run's output cap, so a
// file this long shows the cap was passed. stderr.log keeps its last MiB.
export const MAX_STDOUT_FILE_BYTES = MAX_OUTPUT_BYTES + 1
export const MAX_STDERR_BYTES = 1024 * 1024

// Copies fifo $0.fifo through the filter "$@" to $0.log, then marks $0.done.
// Each copier runs in its own session, so a signal to the task's group leaves
// it to drain what the group wrote; it ends when every writer is gone.
export const copyScript = `"$@" <"$0.fifo" >"$0.log"; : >"$0.done"`

// Starts argv detached in its own session and process group under task
// directory $1, with copyScript as $2. The leader writes the pid file, then the agent's exit code once
// argv returns. Both streams go through fifos to capped copiers (Copilot C10):
// stdout through head, stderr through tail. A failed setup still writes an exit
// code, so the run ends instead of hanging. The leader and the copiers are
// root's and so is everything they write; argv is the one part that runs as the
// agent (taskCommand), holding only the two fifos the leader opened for it.
export const taskScript = `dir=$1; copy=$2; shift 2
exec setsid -f sh -c 'trap : TERM
echo "$$ $(cat /proc/sys/kernel/random/boot_id)" >"$0/pid.tmp" && mv "$0/pid.tmp" "$0/pid"
copy=$1; shift
mkfifo -m 600 "$0/stdout.fifo" "$0/stderr.fifo" &&
setsid -f sh -c "$copy" "$0/stdout" head -c ${MAX_STDOUT_FILE_BYTES} </dev/null &&
setsid -f sh -c "$copy" "$0/stderr" tail -c ${MAX_STDERR_BYTES} </dev/null &&
"$@" >"$0/stdout.fifo" 2>"$0/stderr.fifo"
echo "$?" >"$0/exit-code.tmp" && mv "$0/exit-code.tmp" "$0/exit-code"' "$dir" "$copy" "$@" </dev/null >/dev/null 2>&1`

// The launcher exec for a task: root starts the leader, and argv runs as the agent.
export const taskCommand = (argv: string[]): string[] => ["/bin/sh", "-c", taskScript, "agent", taskDirectory, copyScript, ...asAgent(argv)]

// Removes directory $1 and makes it again, empty, as user $2 with mode $3.
export const freshDirectoryScript = `rm -rf -- "$1" && install -d -o "$2" -g "$2" -m "$3" -- "$1"`

// The task directory, empty and root's alone: the agent cannot list it, write
// in it or replace it, since /workspace is root's too.
export const resetTaskCommand = ["/bin/sh", "-c", freshDirectoryScript, "reset", taskDirectory, "root", "700"]

// An empty directory of the agent's for git to clone into. /workspace is
// root's, so the agent cannot make it.
export const emptyCloneCommand = ["/bin/sh", "-c", freshDirectoryScript, "clone", repositoryDirectory, agentUser, "755"]

// The exit code of a probe script that refuses a task file: it exists, but is
// not a regular file or can't be read. Only this code means the file is not
// what the runner wrote; any other non-zero exit (a probe killed while the
// container stops, a missing shell) says nothing about the file (G2).
export const TASK_FILE_REFUSED = 64

// The size of file $1 in bytes; 0 while it does not exist. Anything but a
// readable regular file (a directory, a FIFO that would block the read) is
// refused with TASK_FILE_REFUSED.
export const outputBytesScript = `[ -e "$1" ] || { echo 0; exit 0; }
[ -f "$1" ] || { echo "$1 is not a regular file" >&2; exit ${TASK_FILE_REFUSED}; }
[ -r "$1" ] || { echo "cannot read $1" >&2; exit ${TASK_FILE_REFUSED}; }
wc -c <"$1"`

// Succeeds once both copiers of task directory $1 have ended.
export const outputDoneScript = `[ -e "$1/stdout.done" ] && [ -e "$1/stderr.done" ]`

// What the pid file holds: the group ID and the boot it started in.
export type Task = { pid: number; boot: string }

// A group ID of 0 or 1 is refused: `kill -SIG -0` signals the caller's own
// group and `kill -SIG -1` every process it may signal.
export function parseTask(text: string): Task | undefined {
	const match = /^(\d+) (\S+)\s*$/.exec(text)
	if (match === null) return undefined
	const pid = Number(match[1])
	return pid > 1 ? { pid, boot: match[2] } : undefined
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

// The sweep's own answers, apart from 0: a process of the user is still there,
// or the image has no such user (an instance from before the agent user) or
// the user is root. Any other exit says nothing about the user's processes.
export const AGENT_LEFT = 65
export const NO_AGENT_USER = 66

// Ends every process of user $1; succeeds once none is left. A process of
// that user sends KILL to -1, every process it may signal: its own user's and
// no other, since it has no privilege, and all in one call, so a process that
// forks cannot outrun it. This reaches a process that left the task's group
// (setsid), which signalScript does not. Root then looks for what is left, by
// the Uid line of /proc/PID/status (a process can make its /proc directory
// root's, but not that line), and tries again for up to 2 s. A zombie waiting
// to be reaped is no process. Never for root: -1 would then be every process.
export const endUserScript = `uid=$(id -u "$1" 2>/dev/null) || exit ${NO_AGENT_USER}
[ "$uid" -gt 0 ] || exit ${NO_AGENT_USER}
n=0
while :; do
	setpriv --reuid="$1" --regid="$1" --init-groups --no-new-privs -- /bin/sh -c 'kill -KILL -1' 2>/dev/null
	left=0
	for d in /proc/[0-9]*; do
		state= owner=
		while read -r key value rest; do
			case $key in State:) state=$value ;; Uid:) owner=$value; break ;; esac
		done 2>/dev/null <"$d/status"
		if [ "$owner" = "$uid" ] && [ "$state" != Z ]; then left=1; break; fi
	done
	[ "$left" = 0 ] && exit 0
	n=$((n + 1))
	[ "$n" -ge 20 ] && exit ${AGENT_LEFT}
	sleep 0.1
done`

// Up to $3 bytes of file $2 from byte $1 (1-based): a ranged read. A file not
// yet created reads as empty; one that is not a regular file or can't be read is
// refused with TASK_FILE_REFUSED.
export const chunkScript = `[ -e "$2" ] || exit 0
[ -f "$2" ] || { echo "$2 is not a regular file" >&2; exit ${TASK_FILE_REFUSED}; }
[ -r "$2" ] || { echo "cannot read $2" >&2; exit ${TASK_FILE_REFUSED}; }
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

// The test-only exec route answers at most this many bytes of each stream.
export const MAX_EXEC_OUTPUT_BYTES = 64 * 1024

export function capOutput(bytes: ArrayBuffer | Uint8Array): string {
	const all = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
	return new TextDecoder().decode(all.subarray(0, MAX_EXEC_OUTPUT_BYTES))
}

// How long each kind of exec may take before it is aborted.
export const execTimeout = { short: 30 * 1000, clone: 10 * 60 * 1000, push: 5 * 60 * 1000, restore: 5 * 60 * 1000 }

type Output = { exitCode: number; stdout: ArrayBuffer | Uint8Array; stderr: ArrayBuffer | Uint8Array }

// Runs a command to its end, or rejects once timeoutMs has passed. The signal
// stops the process; the race makes sure the promise ends even if it does not.
export async function execOutput(container: Container, command: string[], options: ContainerExecOptions, timeoutMs: number): Promise<Output> {
	const signal = AbortSignal.timeout(timeoutMs)
	// Named without the asAgent prefix, which says nothing about the command.
	const plain = command[0] === "setpriv" ? command.slice(command.indexOf("--") + 1) : command
	const name = plain[0] === "/bin/sh" && plain[1] === "-c" ? `sh ${plain[3] ?? ""}`.trim() : plain.slice(0, 2).join(" ")
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
