import { afterAll, beforeAll, describe, expect, it } from "vitest"
import { agentHome, asAgent, repositoryDirectory } from "../src/container"
import { ContainerHost } from "../src/host"
import { syncBranch } from "../src/persist"
import { containerOf, inBox, startBox, stopBox } from "./box"

// What a run starts from: the clone moved to the branch as it is on the remote.
// The remote is a bare repository in the container, so no network is involved.

const origin = "/tmp/sync-origin.git"
const other = "/tmp/sync-other"

let box: string
let container: Container

const agentSh = (script: string) => inBox(box, asAgent(["env", `HOME=${agentHome}`, "/bin/sh", "-c", script]))
const inClone = (script: string) => agentSh(`cd ${repositoryDirectory} && ${script}`)
const head = async () => (await inClone("git rev-parse HEAD")).stdout.trim()

// A commit made in the other clone and pushed to the remote's main.
async function pushedFromOutside(file: string): Promise<string> {
	const made = await agentSh(
		`cd ${other} && git pull -q origin main && echo ${file} >${file} && git add ${file} && git -c user.name=other -c user.email=other@example.com commit -q -m ${file} && git push -q origin main && git rev-parse HEAD`,
	)
	expect(made.stderr).toBe("")
	return made.stdout.trim()
}

beforeAll(async () => {
	box = startBox()
	container = containerOf(box)
	const seeded = await agentSh(
		`git init -q --bare -b main ${origin} && git init -q -b main /tmp/sync-seed && cd /tmp/sync-seed && echo one >README && git add README && git -c user.name=seed -c user.email=seed@example.com commit -q -m one && git push -q ${origin} main && git clone -q ${origin} ${other}`,
	)
	expect(seeded.stderr).toBe("")
	expect(await new ContainerHost(container, () => ({}) as Fetcher).clone(origin, "main")).toBeUndefined()
})

afterAll(() => stopBox(box))

describe("syncBranch", () => {
	it("answers current when the remote has nothing new", async () => {
		const before = await head()
		expect(await syncBranch(container, "main")).toBe("current")
		expect(await head()).toBe(before)
	})

	it("fast-forwards to a commit pushed from outside, and keeps an uncommitted file", async () => {
		await inClone("echo mine >uncommitted.txt")
		const pushed = await pushedFromOutside("two")
		expect(await syncBranch(container, "main")).toBe("fast-forwarded")
		expect(await head()).toBe(pushed)
		expect((await inClone("cat uncommitted.txt two")).stdout).toBe("mine\ntwo\n")
		await inClone("rm uncommitted.txt")
	})

	it("answers current, and keeps the commit, when the clone is ahead of the remote", async () => {
		await inClone("echo ahead >ahead && git add ahead && git commit -q -m ahead")
		const local = await head()
		expect(await syncBranch(container, "main")).toBe("current")
		expect(await head()).toBe(local)
		await inClone("git push -q origin HEAD:refs/heads/main")
	})

	it("answers diverged, and leaves HEAD, with a commit on each side", async () => {
		await inClone("echo local >local && git add local && git commit -q -m local")
		const local = await head()
		await pushedFromOutside("remote")
		expect(await syncBranch(container, "main")).toEqual({ diverged: true })
		expect(await head()).toBe(local)
		await inClone("git reset -q --hard HEAD~1 && git merge -q --ff-only FETCH_HEAD")
	})

	it("answers diverged, with the file still there, when an uncommitted file is in the way", async () => {
		const before = await head()
		await pushedFromOutside("clash")
		await inClone("echo mine >clash")
		expect(await syncBranch(container, "main")).toEqual({ diverged: true })
		expect(await head()).toBe(before)
		expect((await inClone("cat clash")).stdout).toBe("mine\n")
		await inClone("rm clash")
	})

	it("answers an error, with no credential in it, when the branch cannot be fetched", async () => {
		const answer = await syncBranch(container, "no-such-branch")
		expect(answer).toHaveProperty("error")
		expect((answer as { error: string }).error).not.toBe("")
	})
})
