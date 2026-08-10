# Bridge Protocol — implementation reference

Not a governed document. Changes freely until M8. See D-014.

## Request

```json
{
  "agent_id": "systems-architect",
  "task": "What does the lobby layout look like?"
}
```

## Response (success)

```json
{
  "agent_id": "systems-architect",
  "task": "What does the lobby layout look like?",
  "output": "The lobby is an open...",
  "status": "ok"
}
```

## Response (error)

```json
{
  "agent_id": "systems-architect",
  "task": "What does the lobby layout look like?",
  "output": "",
  "status": "error",
  "error_type": "timeout",
  "message": "Agent response timed out after 60 seconds"
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
