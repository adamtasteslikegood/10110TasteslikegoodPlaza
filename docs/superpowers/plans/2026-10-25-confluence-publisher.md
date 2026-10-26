# Confluence source mirror publisher implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Update the existing imported Confluence documents and parent indexes after GitHub merges, retaining GitHub as the source of truth.

**Architecture:** A serialized GitHub Actions job checks out current `dev` on pushes to `main`/`dev`. A Python publisher reads the source registry and the bootstrap destination table in DELIVERY-COORDINATES, renders through the existing Confluence storage converter, and reconciles only managed documents. The Confluence home page stores subsequent generated destination identities in a content property.

**Tech Stack:** Python 3.12, requests, existing md2cf renderer, Confluence REST v2 pages/properties and v1 archive long tasks, GitHub Actions.

**Spec:** Owner request and explicit selection of GitHub Actions publishing in this chat; destination coordinates and document authority derive from `docs/delivery-coordinates.md` and `specs/meta/doc-registry.json`.

## Global constraints

- `dev` is the source of truth for both trigger branches; never publish an older release tree over it.
- Preserve existing 48 import IDs and Live Docs modes. All governed documents and parent indexes use Live Docs; the space home remains a page.
- Derive the imported set from registry documents, committed exempt files, and registry/schema metadata. Missing governed sources fail; missing generated exempt output is omitted.
- Only archive managed, source-declared HISTORICAL/SUPERSEDED or removed documents. Never delete source or unrelated Confluence content.
- Use an Actions secret for API authentication; never write credentials or response bodies to logs.
- A credential-free dry run makes no API calls. An apply run records content hashes and generated destination IDs for repeatable publication.

## Review focus

- Retried publication must not create duplicate pages after partial progress.
- Untrusted pagination links and HTTP redirects must not receive credentials.
- An error while updating a page must not mark its source revision as successfully applied.
- A historical document becoming ACTIVE must fail with a restore instruction before any writes; do not guess an unsupported REST restore operation.
- Registry changes must update the parent records even if the parent Markdown did not change.

### Task 1: Registry-driven rendering and destination planning

**Files:** Create `scripts/pm/publish_docs.py`, `tests/test_publish_docs.py`; modify DELIVERY-COORDINATES and the registry; create `docs/confluence-publishing.md`.

**Interfaces:** `load_documents(root) -> list[Document]`, `load_coordinates(root) -> dict`, `render_document(document, documents, destinations, commit, version) -> str`.

- [x] Write tests for missing/escaping sources, registry status, bootstrap IDs, resolved relative links, preserved code fences, and generated index records.
- [x] Run the tests and observe failures before implementing.
- [x] Implement registry loading and storage rendering using the existing converter.
- [x] Verify tests, `validate_specs.py`, and credential-free `--dry-run` against the real checkout.

### Task 2: Confluence reconciliation and merge workflow

**Files:** Extend publisher/tests; create `.github/workflows/confluence-docs.yml`.

**Interfaces:** `ConfluenceClient.request(method, path, payload=None) -> dict`, `publish(root, client, commit) -> dict`; remote map property `plaza-doc-mirrors` stores per-source digest, published version and destination identity.

- [x] Write failing tests with a local HTTP server for authentication routing, bounded rate-limit retries, version conflicts, existing/new documents, partial-run recovery, archive polling, restore, and idempotence.
- [x] Implement scoped API access, preflight validation, source hash/version publication, persisted destination recovery, and explicit failure reporting. Reactivated archived documents require manual restore; page-mode changes require manual conversion because a public conversion API is unavailable.
- [x] Add push/manual triggers, serialized publication, checkout of current `dev`, validation, dry-run artifact, and secret-backed apply.
- [x] Run the publisher tests and project Python suite; inspect workflow and diff; commit and open a PR with activation limitations stated.

## Activation

Configure the API token in GitHub Actions secrets and run a manual dry run, followed by an apply. Confluence content continues to describe the import as a snapshot until an apply run succeeds; preparing the workflow alone does not establish live synchronization.

## Implementation record

The registry-driven renderer, reconciliation tests and workflow are implemented.
The initial baseline passed 607 tests and 118 subtests. The publisher's 17 tests
cover repeatable apply, partial-create recovery, current/archived identity lookup,
mode promotion, source removals, manual mirror drift, conflict retries and archive
failure. Both independent review findings were reproduced RED and fixed GREEN.
The current clean source plan contains 50 documents and two new destinations.

Ruling: keep public REST mode-conversion and restore limitations explicit; require
the owner to convert/restore existing documents in Confluence rather than creating
new identities or using private APIs. This preserves links but requires that UI
step when a source is reactivated or changes mode.

At initial PR preparation, the unchanged flow snapshot failed the delivery-coordinate freshness gate because
its `as_of` is older than 14 days. This was confirmed with the baseline validator;
the publisher does not refresh unrelated board evidence. The initial Godot
integration timeout was resolved by importing the current project cache; the
isolated integration test then passed without an application-code change.

Final verification: 2,009 Python tests and 118 subtests passed. Black checked all
108 Python files. The governed validator and credential-free render passed.
PR #375 contains the prepared publisher. The owner subsequently authorized
refreshing the live PLZG flow snapshot and fixing a stale-reservation race exposed
by the Godot CI integration gate. Both changes are covered by their validators or
deterministic regression tests. Authenticated publication remains pending token
setup. Store the secret in the branch-restricted `confluence-publish` environment;
the integration cannot configure that environment (HTTP 403).
