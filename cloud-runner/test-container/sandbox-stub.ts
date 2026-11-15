// Stands in for @cloudflare/sandbox in the container tests: the SDK loads only
// in the Workers runtime, and its file operations speak the sandbox-shim's
// protocol over stdin. Only what the runner's task-file reads use is here, done
// with plain commands as the image's user (root), as the shim runs.

export class SandboxFileError extends Error {
	override name = "SandboxFileError"

	constructor(
		readonly code: string,
		message: string,
	) {
		super(message)
	}

	static is(error: unknown): error is SandboxFileError {
		return error instanceof Error && error.name === "SandboxFileError"
	}
}

export class Files {
	constructor(private readonly container: Container) {}

	// The container's own exec takes an argv list and starts no shell.
	async readFile(path: string): Promise<{ text(): Promise<string> }> {
		const started = await this.container.exec(["cat", "--", path])
		const output = await started.output()
		const decoder = new TextDecoder()

		if (output.exitCode !== 0) {
			const message = decoder.decode(output.stderr)
			const code = message.includes("No such file") ? "ENOENT" : message.includes("Permission denied") ? "EACCES" : message.includes("Is a directory") ? "EISDIR" : "UNKNOWN"
			throw new SandboxFileError(code, message)
		}

		return { text: async () => decoder.decode(output.stdout) }
	}
}
