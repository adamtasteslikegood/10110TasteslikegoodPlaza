# Brayden/chat — source review for Plaza M13–M15

Reviewed October 24, 2026 against [Brayden/chat commit 360897a99983200858dcf20222ce77280a698e96](https://github.com/Brayden/chat/tree/360897a99983200858dcf20222ce77280a698e96).
**Research only.** Static source inspection, not a build, deployment, penetration test or provider selection. No example code was copied into Plaza.

## What the example actually implements

- [Backend entry point](https://github.com/Brayden/chat/blob/360897a99983200858dcf20222ce77280a698e96/Backend/src/index.ts): a Hono Worker validates a session's channel membership, routes channel requests to `ConversationDurableObject.idFromName("channel-" + channelId)`, and sends other requests to one `AuthorizationDurableObject.idFromName("default")`.
- [Conversation DO](https://github.com/Brayden/chat/blob/360897a99983200858dcf20222ce77280a698e96/Backend/src/durable-objects/conversation.ts): per-channel SQLite message table, HTTP message listing/posting, R2 uploads. A message is inserted and read back before the authorization DO is called to notify connected members.
- [Authorization DO](https://github.com/Brayden/chat/blob/360897a99983200858dcf20222ce77280a698e96/Backend/src/durable-objects/authorization.ts): SQLite users/channels/membership/sessions, plus the application's live WebSocket connections and presence/notification fanout. It is a shared coordinator, not one socket hub per channel.
- [Backend config](https://github.com/Brayden/chat/blob/360897a99983200858dcf20222ce77280a698e96/Backend/wrangler.jsonc): both DO classes use `new_sqlite_classes` migrations, named bindings, and an R2 bucket.
- [Frontend Worker](https://github.com/Brayden/chat/blob/360897a99983200858dcf20222ce77280a698e96/Frontend/workers/app.ts), [package](https://github.com/Brayden/chat/blob/360897a99983200858dcf20222ce77280a698e96/Frontend/package.json), and [WebSocket provider](https://github.com/Brayden/chat/blob/360897a99983200858dcf20222ce77280a698e96/Frontend/app/providers/WebSocketProvider.tsx): a React Router 7 / React 19 web frontend, served through a Worker adapter, using HTTP for message/history operations and WebSockets for notifications.

The inspected commit dates to May 2, 2025; dependency/config examples must not be treated as current platform requirements. This is not an Agents SDK application and it does not run Claude Code, manage Git worktrees or provide execution containers.

## Mapping to Plaza without ratifying a design

| Example responsibility | Potential Plaza analogue | Boundary that still needs design |
|---|---|---|
| Conversation DO with SQLite | Durable domain/session event storage or relay replica | Stable project/domain/session/host key; local-vs-remote writer authority; bounded records |
| Worker routing + membership checks | Authenticated relay ingress and project/session authorization | Bridge/host identity, credential scope, revocation and authorization on reconnect |
| Stored message before notification | Persist accepted output before notifying clients | Crash between append and notify; replay cursor; idempotency; duplicate handling |
| React Router frontend | Another client of the UI-independent bridge/relay | It does not require replacing Godot or teaching the bridge about a particular UI |
| Global authorization/notification DO | Possible small prototype directory/presence service | A shared hotspot and single coordination scope must be evaluated; not assumed as the scalable session architecture |
| R2 uploads | Optional artifact storage | Source/code/prompt/secret classification and per-project access controls; not implicitly approved |

For the proposed A/B/C direction, this example primarily informs the **hosted state/relay and client layers**. It does not answer the execution-host, sandbox, host-affinity, cleanup or OAuth/API-key feasibility questions. Existing local execution and guards would still be required.

## Specific source findings to carry into review

1. **SQLite is durable; socket bookkeeping is process-local.** `authorization.ts` declares `connections = new Map<string, WebSocket>()`, calls `server.accept()`, and installs event listeners. The reviewed connection path does not use `ctx.acceptWebSocket` and socket attachments to reconstruct hibernated connection identity. Its later `webSocketClose` method does not by itself establish hibernation support. Do not cite this example as proof of hibernating, restart-resumable agent sessions.
2. **Reconnect is not cursor recovery.** The frontend WebSocket provider reconnects manually/on focus and logs closes. The channel screen's focus-triggered history-reload block is commented out. Stored HTTP history exists, but there is no Plaza-style durable `output_id` / high-water / gap handshake in the reviewed chat path. A restored socket does not establish loss-free replay of notifications missed while disconnected.
3. **Timestamp pagination can skip ties.** `conversation.ts` uses second-resolution `unixepoch()` timestamps, `ORDER BY created_at DESC`, and `created_at < (SELECT created_at ... WHERE id = ?)` for the next page. Multiple messages in the same second can straddle a page boundary and be excluded from the next page. A stable total-order cursor is a concrete M13 requirement; this listing query is not an equivalent contract.
4. **Persist-before-notify is useful but incomplete.** There is an external await between storing a message and notification delivery. No outbox/acknowledged replay protocol was found in the reviewed message path. A failed response/retry also needs idempotency semantics rather than blindly creating a new random message ID.
5. **Startup is not explicitly gated.** Both DO constructors call asynchronous `setup()` without awaiting or registering it with `blockConcurrencyWhile`; routes are installed after awaited schema setup. This source structure does not explicitly block fetch until initialization completes. A future Plaza implementation should test cold-start admission rather than assume this sample proves it safe.
6. **Auth is illustrative, not a credential template.** Password hashing is a direct unsalted SHA-256 digest; browser sessions are kept in localStorage and included in the WebSocket URL query. These observed choices are not appropriate defaults to copy for a service that can authorize real code execution. This is a source-level observation, not a claim of an exploited deployment.
7. **Notification topology differs from storage topology.** Conversation DOs are per channel, but all connections route through the default authorization DO. Do not describe this as one independently hibernating WebSocket DO per room/domain or as proof of parallel execution capacity.

These findings are bounded to the inspected source. No requests were sent to the author's deployed service, no accounts were created and no vulnerability report was sent externally.

## Next-session use

Read with [the existing analysis](ANALYSIS.md), [the proposed store/backend plan](../../superpowers/plans/2026-10-23-domain-session-store-execution-backend.md), and [Adam's review queue](../../../M13_DECISIONS_AND_QUESTIONS.md), especially Q02–Q09 and Q11. This reference sharpens the questions; it answers no open owner decision and grants no implementation permission.

Before adopting a similar pattern, require evidence for stable cursor replay across restart, append/notification crash recovery, duplicate submissions, host affinity and unavailable-host behavior, hibernation/reconnect identity, bounded retention and authorization. Keep execution worktree/lease/memory checks separate from transport connectivity.
