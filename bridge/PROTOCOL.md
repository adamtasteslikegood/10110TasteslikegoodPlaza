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
