import { describe, expect, it } from "vitest"
import { currentVersion, redeployPassed, type Observed } from "../scripts/redeploy-verdict"

// Copilot C7: the redeploy check passes only when the deploy worked and changed the version.
const status = (versions: unknown) => JSON.stringify({ id: "dep", versions })

describe("currentVersion", () => {
	it("reads the one version that takes all traffic", () => {
		expect(currentVersion(status([{ version_id: "v1", percentage: 100 }]))).toBe("v1")
	})

	it("answers undefined for anything else, so the check fails closed", () => {
		expect(currentVersion("")).toBeUndefined()
		expect(currentVersion("not json")).toBeUndefined()
		expect(currentVersion("null")).toBeUndefined()
		expect(currentVersion(JSON.stringify({}))).toBeUndefined()
		expect(currentVersion(status([]))).toBeUndefined()
		expect(currentVersion(status([{ version_id: "v1", percentage: 50 }, { version_id: "v2", percentage: 50 }]))).toBeUndefined()
		expect(currentVersion(status([{ version_id: "v1", percentage: 90 }]))).toBeUndefined()
		expect(currentVersion(status([{ version_id: "", percentage: 100 }]))).toBeUndefined()
		expect(currentVersion(status([{ percentage: 100 }]))).toBeUndefined()
	})
})

describe("redeployPassed", () => {
	const good: Observed = {
		deployed: true,
		versionBefore: "v1",
		versionAfter: "v2",
		before: { state: "running", generation: 4 },
		mid: { state: "running", generation: 4 },
		ended: { state: "succeeded", generation: 4 },
		exitCode: "0",
	}

	it("passes a run that survived a deploy that made a new version", () => {
		expect(redeployPassed(good)).toBe(true)
	})

	it("fails when the deploy failed, even if the run survived", () => {
		expect(redeployPassed({ ...good, deployed: false })).toBe(false)
	})

	it("fails when the version did not change or is unknown", () => {
		expect(redeployPassed({ ...good, versionAfter: "v1" })).toBe(false)
		expect(redeployPassed({ ...good, versionBefore: undefined })).toBe(false)
		expect(redeployPassed({ ...good, versionAfter: undefined })).toBe(false)
		expect(redeployPassed({ ...good, versionBefore: undefined, versionAfter: undefined })).toBe(false)
	})

	it("fails when the run moved to another instance, did not succeed, or wrote another exit code", () => {
		expect(redeployPassed({ ...good, mid: { generation: 5 } })).toBe(false)
		expect(redeployPassed({ ...good, ended: { state: "succeeded", generation: 5 } })).toBe(false)
		expect(redeployPassed({ ...good, ended: { state: "failed", generation: 4 } })).toBe(false)
		expect(redeployPassed({ ...good, before: { state: "idle", generation: 4 } })).toBe(false)
		expect(redeployPassed({ ...good, before: { state: "running" }, mid: {}, ended: { state: "succeeded" } })).toBe(false)
		expect(redeployPassed({ ...good, exitCode: "1" })).toBe(false)
		expect(redeployPassed({ ...good, exitCode: undefined })).toBe(false)
	})
})
