import { execFile, execFileSync } from "node:child_process"

export const image = "plaza-cloud-runner:container-test"

// A container from the agent image, with no network, as the platform starts
// one: the image's own entrypoint and user, nothing added.
export function startBox(): string {
	return execFileSync("docker", ["run", "--detach", "--rm", "--network", "none", image], { encoding: "utf8" }).trim()
}

export function stopBox(id: string): void {
	execFileSync("docker", ["rm", "--force", id], { stdio: "ignore" })
}

type Output = { exitCode: number; stdout: Uint8Array; stderr: Uint8Array }

function dockerExec(id: string, command: string[], options: { cwd?: string; env?: Record<string, string>; signal?: AbortSignal }): Promise<Output> {
	const env = Object.entries(options.env ?? {}).flatMap(([key, value]) => ["--env", `${key}=${value}`])
	const argv = ["exec", ...env, "--workdir", options.cwd ?? "/", id, ...command]

	return new Promise((resolve, reject) => {
		execFile("docker", argv, { encoding: "buffer", maxBuffer: 128 * 1024 * 1024, signal: options.signal }, (error, stdout, stderr) => {
			// A command that ran and failed has a numeric exit code; anything else is docker's own trouble.
			if (error !== null && typeof error.code !== "number") return reject(error)
			resolve({ exitCode: error === null ? 0 : (error.code as number), stdout: new Uint8Array(stdout), stderr: new Uint8Array(stderr) })
		})
	})
}

// The part of a Durable Object's Container the runner uses for commands,
// backed by `docker exec`. Like the platform's exec, it runs as the image's user.
export function containerOf(id: string): Container {
	return {
		running: true,
		exec: async (command: string[], options: ContainerExecOptions = {}) => ({ output: () => dockerExec(id, command, options) }),
	} as unknown as Container
}

// Runs a command in the box as the image's user (root) and decodes its output.
export async function inBox(id: string, command: string[], cwd = "/"): Promise<{ exitCode: number; stdout: string; stderr: string }> {
	const output = await dockerExec(id, command, { cwd })
	const decoder = new TextDecoder()
	return { exitCode: output.exitCode, stdout: decoder.decode(output.stdout), stderr: decoder.decode(output.stderr) }
}

// Polls until done() holds, for up to ms.
export async function until(done: () => Promise<boolean>, ms = 20_000): Promise<void> {
	const end = Date.now() + ms

	while (!(await done())) {
		if (Date.now() > end) throw new Error(`Not done after ${ms} ms`)
		await new Promise((resolve) => setTimeout(resolve, 100))
	}
}
