// The pass rule for scripts/redeploy.mjs, kept free of imports so tests can
// load it (test/redeploy-verdict.test.ts) and Node can run it by stripping
// types. Copilot C7: the redeploy itself must have worked, and it must have
// put a new Worker version in place.

// What `wrangler deployments status --json` printed: the version that takes
// all traffic, or undefined when the output is not one version at 100 %.
export function currentVersion(stdout: string): string | undefined {
	let parsed: unknown

	try {
		parsed = JSON.parse(stdout)
	} catch {
		return undefined
	}

	const versions = (parsed as { versions?: unknown } | null)?.versions

	if (!Array.isArray(versions) || versions.length !== 1) {
		return undefined
	}

	const [only] = versions as { version_id?: unknown; percentage?: unknown }[]
	return typeof only?.version_id === "string" && only.version_id !== "" && only.percentage === 100 ? only.version_id : undefined
}

type Seen = { state?: string; generation?: number } | undefined

export type Observed = {
	// Whether `wrangler deploy` resolved. Any rejection (exit code, signal,
	// timeout, spawn error) is a failed deploy.
	deployed: boolean
	versionBefore: string | undefined
	versionAfter: string | undefined
	before: Seen
	mid: Seen
	ended: Seen
	exitCode: string | undefined
}

export function redeployPassed(o: Observed): boolean {
	const generation = o.before?.generation

	return (
		o.deployed &&
		o.versionBefore !== undefined &&
		o.versionAfter !== undefined &&
		o.versionAfter !== o.versionBefore &&
		o.before?.state === "running" &&
		generation !== undefined &&
		o.mid?.generation === generation &&
		o.ended?.generation === generation &&
		o.ended?.state === "succeeded" &&
		o.exitCode === "0"
	)
}
