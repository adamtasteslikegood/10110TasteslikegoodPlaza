import { afterAll, beforeAll, describe, expect, it } from "vitest"
import { agentHome, agentUser, asAgent, imageLayout, layoutPath, repositoryDirectory, taskDirectory } from "../src/container"
import { ContainerHost } from "../src/host"
import { gitEnv, restoredProblem } from "../src/persist"
import { containerOf, inBox, startBox, stopBox, until } from "./box"

// PLZG-311: the agent runs as a user of its own, and what the runner trusts
// about a run (its pid, exit code and logs) is root's alone. Every command here
// is the one the Worker sends, through the real ContainerHost, in a container
// from the real image.

const origin = "/tmp/origin.git"
const decoder = new TextDecoder()

let box: string
let host: ContainerHost
let agentUid: string

// A shell script as the agent user, with the agent's home.
const agentSh = (script: string) => asAgent(["env", `HOME=${agentHome}`, "/bin/sh", "-c", script])
const rootSh = (script: string) => inBox(box, ["/bin/sh", "-c", script])

// Runs argv as a task to its end; answers the exit code the leader wrote.
async function runTask(argv: string[], env: Record<string, string> = {}): Promise<number> {
	await host.resetTask()
	await host.startTask(argv, env)
	let code: number | undefined
	await until(async () => (code = await host.exitCode()) !== undefined)
	await until(() => host.outputDone())
	return code as number
}

const taskSh = (script: string, env?: Record<string, string>) => runTask(["/bin/sh", "-c", script], env)
const stdout = async () => decoder.decode(await host.readOutput(0, 1024 * 1024))

beforeAll(async () => {
	box = startBox()
	host = new ContainerHost(containerOf(box), () => ({}) as Fetcher)
	agentUid = (await inBox(box, ["id", "-u", agentUser])).stdout.trim()

	// A remote to clone from and push to, with one commit on main.
	const seeded = await inBox(
		box,
		agentSh(
			`git init -q --bare -b main ${origin} && git init -q -b main /tmp/seed && cd /tmp/seed && echo one >README && git add README && git -c user.name=seed -c user.email=seed@example.com commit -q -m one && git push -q ${origin} main`,
		),
	)
	expect(seeded.stderr).toBe("")
	expect(await host.clone(origin, "main")).toBeUndefined()
})

afterAll(() => stopBox(box))

describe("the image", () => {
	it("has an agent user that is not root, with a home of its own", async () => {
		expect(Number(agentUid)).toBeGreaterThan(0)
		expect((await rootSh(`stat -c %U ${agentHome}`)).stdout.trim()).toBe(agentUser)
	})

	it("carries the layout mark the runner expects", async () => {
		expect((await rootSh(`cat ${layoutPath}`)).stdout.trim()).toBe(imageLayout)
	})

	it("keeps /workspace root's, so the agent cannot swap the directories in it", async () => {
		expect((await rootSh("stat -c '%U %a' /workspace")).stdout.trim()).toBe("root 755")
	})
})

describe("a task", () => {
	it("runs the agent's command as the agent user, with no way back to root", async () => {
		expect(await taskSh("id -un; id -u; grep NoNewPrivs /proc/self/status")).toBe(0)
		expect((await stdout()).split("\n").slice(0, 3)).toEqual([agentUser, agentUid, "NoNewPrivs:\t1"])
	})

	it("gives the agent its own home, which it can write", async () => {
		expect(await taskSh('[ -w "$HOME" ] && echo "$HOME"', gitEnv)).toBe(0)
		expect(await stdout()).toBe(`${agentHome}\n`)
	})

	it("keeps the pid file, the exit code and the logs out of the agent's reach", async () => {
		const code = await taskSh(
			`echo 0 >${taskDirectory}/exit-code; echo "2 x" >${taskDirectory}/pid; touch ${taskDirectory}/stdout.log; ls ${taskDirectory}; rm -rf ${taskDirectory}; mv ${taskDirectory} /workspace/gone; touch /workspace/planted; echo tried; exit 7`,
		)

		expect(code).toBe(7)
		expect(await stdout()).toBe("tried\n")
		expect((await host.stderrTail()).match(/Permission denied/g)?.length).toBeGreaterThanOrEqual(6)
		expect((await rootSh(`stat -c '%U %a' ${taskDirectory}`)).stdout.trim()).toBe("root 700")
		expect((await rootSh("ls /workspace")).stdout.split("\n").filter(Boolean).sort()).toEqual(["repo", "task"])

		const task = await host.readTask()
		const boot = (await rootSh("cat /proc/sys/kernel/random/boot_id")).stdout.trim()
		expect(task).toMatchObject({ boot })
		expect((task as { pid: number }).pid).toBeGreaterThan(2)
	})

	it("records the agent's exit code and both of its streams", async () => {
		expect(await taskSh("echo out; echo err >&2; exit 3")).toBe(3)
		expect(await stdout()).toBe("out\n")
		expect(await host.stderrTail()).toBe("err\n")
	})

	it("lets no signal from the agent reach the leader that writes the exit code", async () => {
		expect(await taskSh('kill -KILL "$PPID" 2>/dev/null; echo "kill $?"; exit 5')).toBe(5)
		expect(await stdout()).toBe("kill 1\n")
	})

	it("ends the agent on the runner's TERM, and the leader records it", async () => {
		await host.resetTask()
		await host.startTask(["sleep", "60"], {})
		let task: Awaited<ReturnType<ContainerHost["readTask"]>>
		await until(async () => (task = await host.readTask()) !== undefined)
		if (task === undefined || task === "invalid") throw new Error("no task")
		expect(await host.taskAlive(task)).toBe(true)

		await host.signalTask(task, "TERM")
		let code: number | undefined
		await until(async () => (code = await host.exitCode()) !== undefined)
		expect(code).toBe(143)
	})
})

describe("the clone", () => {
	it("is the agent's", async () => {
		expect((await rootSh(`stat -c %U ${repositoryDirectory} ${repositoryDirectory}/.git/config`)).stdout.trim().split("\n")).toEqual([agentUser, agentUser])
	})

	it("shows the agent's uncommitted work in the diff, and runs a diff driver the agent set as the agent", async () => {
		const planted = `printf '#!/bin/sh\\nid -u >/tmp/driver-uid\\n' >/tmp/driver && chmod +x /tmp/driver && git config diff.external /tmp/driver`
		expect(await taskSh(`echo new >NEW.txt && ${planted}`)).toBe(0)

		expect((await host.diff()).ok).toBe(true)
		expect((await rootSh("cat /tmp/driver-uid")).stdout.trim()).toBe(agentUid)

		expect(await taskSh("git config --unset diff.external")).toBe(0)
		const diff = await host.diff()
		expect(diff.ok).toBe(true)
		expect(diff.text).toContain("+++ b/NEW.txt")
	})

	it("pushes the agent's commit, and runs a hook the agent planted as the agent", async () => {
		const hook = `printf '#!/bin/sh\\nid -u >/tmp/hook-uid\\n' >.git/hooks/pre-push && chmod +x .git/hooks/pre-push`
		expect(await taskSh(`git add NEW.txt && git commit -q -m two && ${hook}`, gitEnv)).toBe(0)

		const pushed = await host.push("main")
		const remote = await inBox(box, agentSh(`git --git-dir ${origin} rev-parse main`))
		expect(pushed).toEqual({ commit: remote.stdout.trim() })
		expect(remote.stdout.trim()).toMatch(/^[0-9a-f]{40}$/)
		expect((await rootSh("cat /tmp/hook-uid")).stdout.trim()).toBe(agentUid)
	})

	it("runs a test command as the agent, and as root only when asked", async () => {
		expect((await host.exec(["id", "-un"])).stdout).toBe(`${agentUser}\n`)
		expect((await host.exec(["git", "status", "--short"])).exitCode).toBe(0)
		expect((await host.exec(["id", "-un"], true)).stdout).toBe("root\n")
	})
})

// Last: these change the box.
describe("a restored instance", () => {
	it("is accepted when it has the clone and this image's layout", async () => {
		expect(await restoredProblem(containerOf(box))).toBeUndefined()
	})

	it("is refused when its layout mark is another's, as a snapshot from before the agent user is", async () => {
		await rootSh(`echo 1 >${layoutPath}`)
		expect(await restoredProblem(containerOf(box))).toMatch(/layout/)
		await rootSh(`rm ${layoutPath}`)
		expect(await restoredProblem(containerOf(box))).toMatch(/layout/)
	})
})
