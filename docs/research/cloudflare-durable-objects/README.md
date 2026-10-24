# Cloudflare Durable Objects + Workers research

Raw pages fetched from developers.cloudflare.com with `Accept: text/markdown`. Files in `raw/` are unmodified responses.

Reading order:
1. 01-durable-objects-overview.md, 02-what-are-durable-objects.md (concepts)
2. 03-storage-best-practices.md, 04-sqlite-storage-api.md (storage)
3. 05-limits.md, 06-pricing.md (constraints and cost)
4. 07-workers-python.md, 08-workers-overview.md (Workers runtime)
5. 09-agents-sdk.md, 10-sandbox-sdk.md, 11-containers.md (agent hosting options)

00-durable-objects-llms.txt is the docs page index.

## Reconciliation provenance and review gate

The twelve raw files here are byte-identical to the snapshots retained under
`Docs/files/cloudflare-durable-objects/raw/` at this reconciliation. Both paths
are preserved so original references and provenance survive; use this directory
as the research reading entry point. Vendor snapshots were not edited or refetched.

The analysis and store/backend plan are research/proposals, not new canon.
See [M13 decisions and questions](../../../M13_DECISIONS_AND_QUESTIONS.md)
for recorded owner answers, governance conflicts and the next-session review gate.

## Additional source review

- [Brayden/chat: SQLite DOs, WebSockets and React Router](brayden-chat-review.md):
  pinned source inspection, applicability to Plaza, and recovery/auth gaps.
