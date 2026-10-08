# Bridge Protocol

WebSocket on `ws://localhost:8765` (D-015). JSON messages, one per WebSocket frame.

## Request Types

### Conversation (backward-compatible with M8)

```json
{
  "type": "conversation",
  "agent_id": "security-auditor",
  "task": "What's your take on the new hire?",
  "request_id": "optional-uuid"
}
```

A request **without** a `type` field is treated as `"conversation"` — existing
clients work without changes.

#### Conversation history

The bridge remembers a conversation for as long as the WebSocket connection it
arrived on stays open. Within a connection it keeps one history per `agent_id`:
each successful exchange is appended, and the next request for that agent is
sent to the model with those earlier turns in front of it.

- **The client sends nothing extra.** There is no conversation id and no
  history field. A client holds a conversation by keeping its connection open
  and loses it by reconnecting. Any client gets this the same way (`D-005`).
- **A new connection starts with nothing**, and two connections never see each
  other's turns, even for the same agent.
- **Only successful exchanges are kept.** A request that fails, or a reply with
  no text, leaves the history as it was, so retrying does not repeat the
  question.
- **It is bounded.** The newest 40 messages (20 exchanges) per agent are kept;
  older ones are dropped whole, oldest first.
- **It is not persisted.** Nothing is written to disk, and a bridge restart
  forgets everything. Long-lived, resumable state is what domain sessions are
  for.

### Domain Query

```json
{
  "type": "domain_query",
  "domain_id": "engineering",
  "agent_id": "systems-architect",
  "task": "Review the auth middleware",
  "request_id": "uuid"
}
```

Domain queries run asynchronously. The response arrives as a push message
when the Agent SDK completes. If the domain is backgrounded, output
accumulates in the buffer for later resume.

### Resume

```json
{
  "type": "resume",
  "domain_id": "engineering",
  "cursor": "last-seen-output-id"
}
```

Returns all output entries since the cursor. Also refocuses the domain
(transitions from BACKGROUNDED to ACTIVE).

### Lifecycle Commands

```json
{"type": "activate_domain", "domain_id": "engineering"}
{"type": "background_domain", "domain_id": "engineering"}
{"type": "refocus_domain", "domain_id": "engineering"}
{"type": "deactivate_domain", "domain_id": "engineering"}
```

## Response Format

Both engines use the same response shape:

```json
{
  "agent_id": "systems-architect",
  "task": "Review the auth middleware",
  "output": "Looking at the middleware...",
  "status": "ok",
  "domain_id": "engineering",
  "request_id": "uuid",
  "output_id": "0"
}
```

Error responses add `error_type` and `message`:

```json
{
  "agent_id": "systems-architect",
  "task": "Review the auth middleware",
  "output": "",
  "status": "error",
  "error_type": "not_found",
  "message": "No agent 'systems-architect'"
}
```

### Error types

| error_type | Meaning |
|---|---|
| `timeout` | Claude API call exceeded the timeout (D-006) |
| `auth` | No valid credentials found |
| `not_found` | agent_id not in the agent store |
| `api_error` | Claude API returned an error |
| `invalid_request` | Malformed JSON or missing required fields |

## Domain State Notifications (push)

Sent by the bridge when domain state changes:

```json
{
  "type": "domain_state",
  "domain_id": "engineering",
  "state": "backgrounded",
  "unread_count": 3
}
```

## Domain Session States

```
INACTIVE → ACTIVATING → ACTIVE → BACKGROUNDED → ACTIVE (refocus)
                          ↓           ↓
                     DEACTIVATED  DEACTIVATED
```
