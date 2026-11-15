import { describe, expect, it } from "vitest"
import { checkPush, MAX_COMMAND_BYTES } from "../src/pushguard"

// Copilot C11: only the workspace branch may be updated through receive-pack.
// Fixtures are built from small parts; no input here is unbounded.
const encoder = new TextEncoder()
const bytes = (text: string) => encoder.encode(text)
const pkt = (payload: string) => (payload.length + 4).toString(16).padStart(4, "0") + payload
const FLUSH = "0000"
const A = "a".repeat(40)
const B = "b".repeat(40)
const ZERO = "0".repeat(40)
const CAPS = "\0report-status side-band-64k quiet object-format=sha1 agent=git/2.47.0"
const PACK = "PACK\0\0\0\x02\0\0\0\x01junk"
const body = (...lines: string[]) => bytes(lines.map(pkt).join("") + FLUSH + PACK)

const allowed = (head: Uint8Array) => expect(checkPush(head, "work")).toEqual({ allow: true })
const refused = (head: Uint8Array, reason?: string) => {
	const verdict = checkPush(head, "work")
	expect(verdict).toMatchObject({ allow: false, reason: reason === undefined ? expect.any(String) : expect.stringContaining(reason) })
}

describe("checkPush", () => {
	it("allows an update of the workspace branch, capabilities after the NUL", () => {
		allowed(body(`${A} ${B} refs/heads/work${CAPS}`))
	})

	it("allows creating the workspace branch and a trailing newline on a command", () => {
		allowed(body(`${ZERO} ${B} refs/heads/work${CAPS}\n`))
		allowed(body(`${A} ${B} refs/heads/work\n`))
	})

	it("allows sha256 object ids", () => {
		allowed(body(`${"c".repeat(64)} ${"d".repeat(64)} refs/heads/work\0object-format=sha256`))
	})

	it("allows two commands that both name the workspace branch", () => {
		allowed(body(`${A} ${B} refs/heads/work${CAPS}`, `${B} ${A} refs/heads/work`))
	})

	it("allows shallow lines before the commands", () => {
		allowed(body(`shallow ${A}`, `shallow ${B}\n`, `${A} ${B} refs/heads/work${CAPS}`))
	})

	it("refuses another branch, a tag, and a branch that only starts with the name", () => {
		refused(body(`${A} ${B} refs/heads/main${CAPS}`), "workspace branch")
		refused(body(`${A} ${B} refs/tags/v1${CAPS}`), "workspace branch")
		refused(body(`${A} ${B} refs/heads/work2${CAPS}`), "workspace branch")
		refused(body(`${A} ${B} refs/heads/work/x${CAPS}`), "workspace branch")
		refused(body(`${A} ${B} refs/heads/WORK${CAPS}`), "workspace branch")
		refused(body(`${A} ${B} work${CAPS}`), "workspace branch")
	})

	it("refuses when any one of several commands names another ref", () => {
		refused(body(`${A} ${B} refs/heads/work${CAPS}`, `${A} ${B} refs/heads/main`), "workspace branch")
		refused(body(`${A} ${B} refs/heads/main${CAPS}`, `${A} ${B} refs/heads/work`), "workspace branch")
	})

	it("refuses a deletion, even of the workspace branch", () => {
		refused(body(`${A} ${ZERO} refs/heads/work${CAPS}`), "delet")
		refused(body(`${"c".repeat(64)} ${"0".repeat(64)} refs/heads/work`), "delet")
	})

	it("refuses capabilities on a later command and a NUL inside the ref", () => {
		refused(body(`${A} ${B} refs/heads/work${CAPS}`, `${A} ${B} refs/heads/work${CAPS}`))
		refused(body(`${A} ${B} refs/heads/work\0x\0y`, `${A} ${B} refs/heads/main`))
	})

	it("refuses malformed commands", () => {
		refused(body(`${A} ${B}`))
		refused(body(`${A}  ${B} refs/heads/work`))
		refused(body(`${A.toUpperCase()} ${B} refs/heads/work`))
		refused(body(`${A.slice(1)} ${B} refs/heads/work`))
		refused(body(`${A} ${"d".repeat(64)} refs/heads/work`))
		refused(body(`${A} ${B} refs/heads/work extra`))
	})

	it("refuses a shallow line after a command and a malformed shallow line", () => {
		refused(body(`${A} ${B} refs/heads/work${CAPS}`, `shallow ${A}`))
		refused(body(`shallow ${A.slice(2)}`, `${A} ${B} refs/heads/work`))
	})

	it("refuses lines it does not recognise, such as a push certificate", () => {
		refused(body(`push-cert\0report-status`, "certificate version 0.1\n", "push-cert-end\n", `${A} ${B} refs/heads/work`))
		refused(body("unshallow " + A, `${A} ${B} refs/heads/work`))
	})

	it("refuses an empty command list followed by data", () => {
		refused(bytes(FLUSH + PACK), "no command")
		refused(bytes(pkt(`shallow ${A}`) + FLUSH), "no command")
	})

	it("allows git's auth probe: a body that is a single flush and nothing else", () => {
		expect(checkPush(bytes(FLUSH), "work", true)).toEqual({ allow: true })
		expect(checkPush(bytes(FLUSH), "work", false)).toBe("more")
	})

	it("refuses an empty body", () => {
		refused(new Uint8Array(0))
	})

	it("refuses delim, response-end and too-short lengths, and a length that is not hex", () => {
		for (const length of ["0001", "0002", "0003", "0004"]) {
			refused(bytes(length + pkt(`${A} ${B} refs/heads/work`) + FLUSH))
		}
		refused(bytes("00zz" + FLUSH))
		refused(bytes("-001" + FLUSH))
	})

	it("refuses a truncated pkt-line when the body has ended", () => {
		const whole = pkt(`${A} ${B} refs/heads/work${CAPS}`)
		refused(bytes(whole.slice(0, 50)), "truncated")
		refused(bytes(whole.slice(0, 2)), "truncated")
		refused(bytes(whole), "truncated")
	})

	it("refuses a length prefix that lies", () => {
		const command = `${A} ${B} refs/heads/main`
		// Claims to be shorter: the ref read is cut, and the rest is read as a pkt-line.
		refused(bytes((command.length + 4 - 5).toString(16).padStart(4, "0") + command + FLUSH + PACK))
		// Claims to be longer: the flush and pack data become part of the command.
		refused(bytes((command.length + 4 + 8).toString(16).padStart(4, "0") + command + FLUSH + PACK))
		// A short ref hiding a second command inside the first pkt-line.
		const hidden = `${A} ${B} refs/heads/work\n${A} ${B} refs/heads/main`
		refused(bytes(pkt(hidden) + FLUSH + PACK))
	})

	it("asks for more while a command or the flush is still to come", () => {
		const whole = pkt(`${A} ${B} refs/heads/work${CAPS}`) + FLUSH
		for (const cut of [0, 3, 4, 60, whole.length - 4, whole.length - 1]) {
			expect(checkPush(bytes(whole.slice(0, cut)), "work", false)).toBe("more")
		}
		expect(checkPush(bytes(whole), "work", false)).toEqual({ allow: true })
	})

	it("decides as soon as a refused command is read, without waiting for the rest", () => {
		const partial = pkt(`${A} ${B} refs/heads/main${CAPS}`) + "00"
		expect(checkPush(bytes(partial), "work", false)).toMatchObject({ allow: false })
	})

	it("refuses a command section over the cap, ended or not", () => {
		expect(MAX_COMMAND_BYTES).toBe(64 * 1024)
		const line = pkt(`${A} ${B} refs/heads/work`)
		const count = Math.ceil(MAX_COMMAND_BYTES / line.length)
		const long = bytes(pkt(`${A} ${B} refs/heads/work${CAPS}`) + line.repeat(count) + FLUSH)
		expect(checkPush(long, "work", true)).toMatchObject({ allow: false, reason: expect.stringContaining("64 KiB") })
		expect(checkPush(long.subarray(0, MAX_COMMAND_BYTES + 10), "work", false)).toMatchObject({ allow: false, reason: expect.stringContaining("64 KiB") })
	})

	it("refuses a pkt-line whose length runs past the cap without waiting for its bytes", () => {
		// ffff is the largest length; after the first command it ends past 64 KiB.
		const head = bytes(pkt(`${A} ${B} refs/heads/work${CAPS}`) + "ffff" + "y".repeat(10))
		expect(checkPush(head, "work", false)).toMatchObject({ allow: false, reason: expect.stringContaining("64 KiB") })
	})

	it("refuses every push when the workspace has no branch", () => {
		expect(checkPush(body(`${A} ${B} refs/heads/work${CAPS}`), "")).toMatchObject({ allow: false, reason: expect.stringContaining("branch") })
		expect(checkPush(body(`${A} ${B} refs/heads/${CAPS}`), "")).toMatchObject({ allow: false })
	})

	it("refuses a command whose ref is not valid UTF-8", () => {
		const payload = new Uint8Array([...bytes(`${A} ${B} refs/heads/wor`), 0xff])
		const head = new Uint8Array([...bytes((payload.length + 4).toString(16).padStart(4, "0")), ...payload, ...bytes(FLUSH)])
		expect(checkPush(head, "work")).toMatchObject({ allow: false })
	})
})
