import type { Event } from "./types"

export const MAX_EVENTS = 10_000
export const MAX_PAYLOAD_BYTES = 262_144
// Payload bytes one read returns at most, past its first event.
export const MAX_READ_BYTES = 4 * 1024 * 1024

const DEFAULT_LIMIT = 500
const MAX_LIMIT = 1000

const encoder = new TextEncoder()

type Row = { seq: number; run: number; generation: number; at: string; type: string; payload: string }

// A numbered log of the last MAX_EVENTS events of one workspace, in the
// Durable Object's own SQLite. AUTOINCREMENT keeps `seq` rising even after the
// newest rows are trimmed or removed; only clear() starts the count again.
export class EventLog {
	constructor(private sql: SqlStorage) {
		this.createTable()
	}

	private createTable(): void {
		this.sql.exec(
			`CREATE TABLE IF NOT EXISTS events (
				seq INTEGER PRIMARY KEY AUTOINCREMENT,
				run INTEGER NOT NULL,
				generation INTEGER NOT NULL,
				at TEXT NOT NULL,
				type TEXT NOT NULL,
				payload TEXT NOT NULL
			)`,
		)
	}

	append(run: number, generation: number, type: string, payload: unknown): number {
		let json = JSON.stringify(payload) ?? "null"
		const bytes = encoder.encode(json).length
		if (bytes > MAX_PAYLOAD_BYTES) json = JSON.stringify({ truncated: true, bytes })
		const at = new Date().toISOString()
		const seq = this.sql
			.exec<{ seq: number }>(
				"INSERT INTO events (run, generation, at, type, payload) VALUES (?, ?, ?, ?, ?) RETURNING seq",
				run,
				generation,
				at,
				type,
				json,
			)
			.one().seq
		// Range delete on the primary key: cheap, and a no-op until the log is full.
		this.sql.exec("DELETE FROM events WHERE seq <= ?", seq - MAX_EVENTS)
		return seq
	}

	readAfter(after: number, limit = DEFAULT_LIMIT): { events: Event[]; next: number } {
		const n = Number.isFinite(limit) ? Math.min(MAX_LIMIT, Math.max(1, Math.floor(limit))) : DEFAULT_LIMIT
		const rows = this.sql.exec<Row>("SELECT seq, run, generation, at, type, payload FROM events WHERE seq > ? ORDER BY seq ASC LIMIT ?", after, n)
		const events: Event[] = []
		let bytes = 0

		// Stops before the event that would pass MAX_READ_BYTES, but always returns
		// one, so a reader can always move past `after`.
		for (const r of rows) {
			bytes += encoder.encode(r.payload).length
			if (events.length > 0 && bytes > MAX_READ_BYTES) break
			events.push({ seq: r.seq, run: r.run, generation: r.generation, at: r.at, type: r.type, payload: JSON.parse(r.payload) })
		}

		return { events, next: events.length > 0 ? events[events.length - 1].seq : after }
	}

	// Forget every event and restart `seq` at 1 (a deleted workspace starts over).
	clear(): void {
		this.sql.exec("DROP TABLE IF EXISTS events")
		this.createTable()
	}
}
