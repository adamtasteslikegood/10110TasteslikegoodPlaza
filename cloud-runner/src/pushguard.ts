// Which refs a git-receive-pack request may update (Copilot C11). Pure: it
// reads the leading pkt-lines of the request body and nothing else.
//
// The body of a push starts with its command list, before the packfile:
//
//   [shallow <oid>]...  <old-oid> SP <new-oid> SP <ref>[NUL <capabilities>]  ...  0000  <pack>
//
// each line framed as a pkt-line (4 hex digits of length, counting themselves).
// A push may update only refs/heads/<workspace branch>, and may not delete it.
// Anything this does not recognise is refused: the check trusts git's wire
// format, so it reads strictly rather than guessing.

export const MAX_COMMAND_BYTES = 64 * 1024
// The largest Content-Length a push may state (F3); a larger one is refused.
export const MAX_PUSH_BYTES = 2 * 1024 ** 3

export type PushVerdict = { allow: true } | { allow: false; reason: string }

const refuse = (reason: string): PushVerdict => ({ allow: false, reason })
const OID = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/
const LENGTH = /^[0-9a-fA-F]{4}$/
const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true })

// `head` is the start of the body; `ended` says whether it is all of it. The
// answer is "more" when the decision needs bytes that have not arrived yet,
// and never "more" when ended is true or once head passes MAX_COMMAND_BYTES.
export function checkPush(head: Uint8Array, branch: string, ended = true): PushVerdict | "more" {
	if (branch === "") {
		return refuse("the workspace has no branch, so nothing may be pushed")
	}

	const want = `refs/heads/${branch}`
	let offset = 0
	let commands = 0
	let shallows = 0

	for (;;) {
		if (offset + 4 > MAX_COMMAND_BYTES) {
			return refuse("the push command list is over 64 KiB")
		}

		if (offset + 4 > head.length) {
			return ended ? refuse("the push command list is truncated") : "more"
		}

		const prefix = String.fromCharCode(...head.subarray(offset, offset + 4))

		if (!LENGTH.test(prefix)) {
			return refuse("the push command list is not in pkt-line form")
		}

		const length = parseInt(prefix, 16)

		if (length === 0) {
			if (commands > 0) {
				return { allow: true }
			}

			// git sends a lone flush as a probe before a large push, to check
			// the credential. It updates nothing.
			if (offset === 0 && shallows === 0) {
				if (head.length > 4) return refuse("the push has no command")
				return ended ? { allow: true } : "more"
			}

			return refuse("the push has no command")
		}

		if (length < 5) {
			// 0001 to 0003 are protocol v2 markers and 0004 an empty line: none
			// belongs in a push command list.
			return refuse("the push command list has an unexpected pkt-line")
		}

		if (offset + length > MAX_COMMAND_BYTES) {
			return refuse("the push command list is over 64 KiB")
		}

		if (offset + length > head.length) {
			return ended ? refuse("the push command list is truncated") : "more"
		}

		let payload = head.subarray(offset + 4, offset + length)
		if (payload.at(-1) === 0x0a) payload = payload.subarray(0, -1)
		offset += length

		const nul = payload.indexOf(0)
		const command = nul === -1 ? payload : payload.subarray(0, nul)
		let text: string

		try {
			text = decoder.decode(command)
		} catch {
			return refuse("the push command list is not valid UTF-8")
		}

		if (text.startsWith("shallow ")) {
			if (commands > 0 || nul !== -1 || !OID.test(text.slice(8))) {
				return refuse("the push command list has an unexpected shallow line")
			}

			shallows += 1
			continue
		}

		// Only the first command carries capabilities.
		if (nul !== -1 && commands > 0) {
			return refuse("the push command list has capabilities on a later command")
		}

		const parts = text.split(" ")

		if (parts.length !== 3 || !OID.test(parts[0]) || !OID.test(parts[1]) || parts[0].length !== parts[1].length) {
			return refuse("the push command list has a line that is not a ref update")
		}

		if (parts[2] !== want) {
			return refuse("only the workspace branch may be pushed")
		}

		if (/^0+$/.test(parts[1])) {
			return refuse("deleting the workspace branch is not allowed")
		}

		commands += 1
	}
}
