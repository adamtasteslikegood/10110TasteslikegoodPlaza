import { runInDurableObject } from "cloudflare:test"
import { env as workerEnv } from "cloudflare:workers"
import { describe, expect, it } from "vitest"
import { EventLog, MAX_EVENTS, MAX_PAYLOAD_BYTES, MAX_READ_BYTES } from "../src/events"
import type { Env } from "../src/types"

const env = workerEnv as unknown as Env

// Runs `fn` inside a fresh Workspace Durable Object (SQLite storage), so the
// log sits on the real storage engine. Each test gets its own object.
let n = 0
async function withLog<R>(fn: (log: EventLog) => R): Promise<R> {
	const stub = env.WORKSPACE.getByName(`events-test-${++n}`)
	return runInDurableObject(stub, (_instance, state) => fn(new EventLog(state.storage.sql)))
}

describe("EventLog", () => {
	it("numbers appends from 1", async () => {
		const seqs = await withLog((log) => [log.append(1, 1, "a", {}), log.append(1, 1, "b", {}), log.append(1, 1, "c", {})])
		expect(seqs).toEqual([1, 2, 3])
	})

	it("stores run, generation, type, payload and an ISO time", async () => {
		const { events } = await withLog((log) => {
			log.append(4, 2, "assistant", { text: "héllo" })
			return log.readAfter(0)
		})
		expect(events).toHaveLength(1)
		expect(events[0]).toMatchObject({ seq: 1, run: 4, generation: 2, type: "assistant", payload: { text: "héllo" } })
		expect(new Date(events[0].at).toISOString()).toBe(events[0].at)
	})

	it("reads after a seq, in ascending order, with next", async () => {
		const r = await withLog((log) => {
			for (const t of ["a", "b", "c"]) log.append(1, 1, t, t)
			return log.readAfter(1)
		})
		expect(r.events.map((e) => e.seq)).toEqual([2, 3])
		expect(r.next).toBe(3)
	})

	it("returns nothing at or past the end and keeps next equal to after", async () => {
		const r = await withLog((log) => {
			for (const t of ["a", "b", "c"]) log.append(1, 1, t, t)
			return [log.readAfter(3), log.readAfter(99)]
		})
		expect(r[0]).toEqual({ events: [], next: 3 })
		expect(r[1]).toEqual({ events: [], next: 99 })
	})

	it("returns an empty list from an empty log", async () => {
		expect(await withLog((log) => log.readAfter(0))).toEqual({ events: [], next: 0 })
	})

	it("keeps the last MAX_EVENTS and never reuses a seq after trimming", async () => {
		const r = await withLog((log) => {
			for (let i = 0; i < MAX_EVENTS + 5; i++) log.append(1, 1, "x", i)
			const first = log.readAfter(0, 1).events[0].seq
			const next = log.append(1, 1, "x", "after")
			// walk the whole log in pages to count the kept rows
			let kept = 0
			let after = 0
			for (;;) {
				const page = log.readAfter(after, 1000)
				if (page.events.length === 0) break
				kept += page.events.length
				after = page.next
			}
			return { first, next, kept, after }
		})
		expect(r.first).toBe(6)
		expect(r.next).toBe(MAX_EVENTS + 6)
		expect(r.kept).toBe(MAX_EVENTS)
		expect(r.after).toBe(MAX_EVENTS + 6)
	})

	it("starts from the oldest kept event when after is older than the trimmed log", async () => {
		const r = await withLog((log) => {
			for (let i = 0; i < MAX_EVENTS + 5; i++) log.append(1, 1, "x", i)
			return log.readAfter(0, 3)
		})
		expect(r.events.map((e) => e.seq)).toEqual([6, 7, 8])
		expect(r.next).toBe(8)
	})

	it("stores a payload exactly at the cap whole and one byte over truncated", async () => {
		const wrapper = JSON.stringify("").length // the two quotes
		const atCap = "a".repeat(MAX_PAYLOAD_BYTES - wrapper)
		const over = "a".repeat(MAX_PAYLOAD_BYTES - wrapper + 1)
		const { events } = await withLog((log) => {
			log.append(1, 1, "x", atCap)
			log.append(1, 1, "x", over)
			return log.readAfter(0)
		})
		expect(events[0].payload).toBe(atCap)
		expect(events[1].payload).toEqual({ truncated: true, bytes: MAX_PAYLOAD_BYTES + 1 })
	})

	it("measures the cap in UTF-8 bytes, not characters", async () => {
		// "é" is 2 bytes: this has far fewer than the cap in characters but is over it in bytes
		const text = "é".repeat(MAX_PAYLOAD_BYTES / 2)
		const { events } = await withLog((log) => {
			log.append(1, 1, "x", text)
			return log.readAfter(0)
		})
		expect(events[0].payload).toMatchObject({ truncated: true })
		expect((events[0].payload as { bytes: number }).bytes).toBe(MAX_PAYLOAD_BYTES + 2)
	})

	it("truncates a 300,000-byte payload", async () => {
		const { events } = await withLog((log) => {
			log.append(1, 1, "x", "a".repeat(300_000))
			return log.readAfter(0)
		})
		const p = events[0].payload as { truncated: boolean; bytes: number }
		expect(p.truncated).toBe(true)
		expect(p.bytes).toBeGreaterThan(MAX_PAYLOAD_BYTES)
	})

	it("defaults the limit to 500 and clamps it to 1..1000", async () => {
		const r = await withLog((log) => {
			for (let i = 0; i < 1200; i++) log.append(1, 1, "x", i)
			return {
				def: log.readAfter(0).events.length,
				big: log.readAfter(0, 5000).events.length,
				zero: log.readAfter(0, 0).events.length,
				neg: log.readAfter(0, -4).events.length,
				ten: log.readAfter(0, 10),
			}
		})
		expect(r.def).toBe(500)
		expect(r.big).toBe(1000)
		expect(r.zero).toBe(1)
		expect(r.neg).toBe(1)
		expect(r.ten.events).toHaveLength(10)
		expect(r.ten.next).toBe(10)
	})

	it("clear removes everything and restarts seq at 1", async () => {
		const r = await withLog((log) => {
			for (let i = 0; i < 5; i++) log.append(1, 1, "x", i)
			log.clear()
			const empty = log.readAfter(0)
			return { empty, seq: log.append(1, 1, "x", "again") }
		})
		expect(r.empty).toEqual({ events: [], next: 0 })
		expect(r.seq).toBe(1)
	})

	it("a second EventLog over the same storage continues the numbering", async () => {
		const seq = await withLog((log) => {
			log.append(1, 1, "x", 1)
			log.append(1, 1, "x", 2)
			return log.append(1, 1, "x", 3)
		})
		expect(seq).toBe(3)
		const stub = env.WORKSPACE.getByName("events-test-persist")
		const seqs = await runInDurableObject(stub, (_i, state) => {
			const a = new EventLog(state.storage.sql)
			a.append(1, 1, "x", 1)
			const b = new EventLog(state.storage.sql)
			return b.append(1, 1, "x", 2)
		})
		expect(seqs).toBe(2)
	})
})

describe("EventLog read budget", () => {
	it("stops a read at MAX_READ_BYTES of payload, and a reader still reaches every event", async () => {
		const big = "x".repeat(200_000) // 24 of these are past the budget
		const r = await withLog((log) => {
			for (let i = 0; i < 24; i++) log.append(1, 1, "big", big)
			const first = log.readAfter(0)
			const seen = [...first.events]
			for (let next = first.next, page = 0; page < 30; page++) {
				const more = log.readAfter(next)
				if (more.events.length === 0) break
				seen.push(...more.events)
				next = more.next
			}
			return { first, seen }
		})
		const bytes = r.first.events.reduce((sum, e) => sum + JSON.stringify(e.payload).length, 0)
		expect(r.first.events.length).toBeGreaterThan(0)
		expect(r.first.events.length).toBeLessThan(24)
		expect(bytes).toBeLessThanOrEqual(MAX_READ_BYTES)
		expect(r.seen.map((e) => e.seq)).toEqual(Array.from({ length: 24 }, (_, i) => i + 1))
	})

	it("returns one event even when it alone is larger than the rest of the budget", async () => {
		const r = await withLog((log) => {
			log.append(1, 1, "big", "y".repeat(MAX_PAYLOAD_BYTES - 10))
			return log.readAfter(0)
		})
		expect(r.events).toHaveLength(1)
	})
})
