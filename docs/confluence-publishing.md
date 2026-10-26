# Publishing GitHub documents to Confluence

GitHub `dev` is the source of truth. The **Confluence Source Mirrors** workflow
updates the existing imports after document-related pushes (including merged PRs)
to `dev` or `main`. Both events publish the current committed `dev` tree: a release
merge must not replace it with an older `main` snapshot.

The publisher is operational tooling, not a new source of document authority.
Membership, tiers, authority and status come from
[`specs/meta/doc-registry.json`](../specs/meta/doc-registry.json).
Destination identities come from
[`DELIVERY-COORDINATES`](delivery-coordinates.md#github-documentation-mirrors).

## Activation

1. Configure the repository Actions secret `ATLASSIAN_API_TOKEN_BASE64` with
   Base64-encoded `email:api-token`. Use a dedicated Atlassian account or token
   with access to view, create, edit and archive pages in the destination space.
   This client uses Basic authentication against the site URL; use an API token
   supported for that direct-site authentication, rather than an OAuth token or
   a token requiring the `api.atlassian.com/ex/confluence/...` gateway.
2. Merge the publisher into `dev` through the normal review process. The merge
   triggers publication. Until the secret is configured, the apply step fails
   explicitly and leaves the prior imported snapshots in place.
3. Alternatively, run **Confluence Source Mirrors** manually with `apply=false`
   to produce a credential-free publication plan. Inspect the `confluence-docs-plan`
   artifact, then run with `apply=true` to publish.
4. Verify the Actions run succeeds and check the source revision and parent index
   records in Confluence. Preparing or merging this workflow alone does not prove
   that an authenticated publication succeeded.

Configure the secret in the repository's
[Actions secrets settings](https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/settings/secrets/actions).
Do not put credentials in a document, PR, commit, or chat. This chat's connected
Atlassian authorization is separate from the Actions API credential.

## What gets published

- Every registered governed document, existing committed exempt source, and the
  registry/schema metadata. Missing generated exempt output such as `report.md`
  is omitted; a missing governed source fails before publication.
- All governed documents, repository parent indexes and governance metadata use
  Live Docs. Other references/process documents use pages. The space homepage
  remains a page and mirrors the repository README plus the import record.
- Parent pages mirror their own GitHub index and include a generated record of
  source paths, Confluence links, authority, source status and archive state.
- Historical/superseded documents remain preserved in the archive. A managed
  source removed from the registry is archived. Unrelated pages, retrospectives,
  reports, diagnostic evidence and research whiteboards are not managed or deleted.
- New documents use their source path as a unique page title. Existing import
  titles and IDs are retained. Relative links resolve to GitHub; code examples
  are rendered as code, rather than rewritten as links.

The workflow runs without a schedule. Code-only pushes that do not touch the
configured document/publisher paths do not require a publication.

## Local verification

```bash
python -m pip install -r scripts/pm/requirements.txt pytest
python -m pytest tests/test_publish_docs.py -q
python scripts/validate_specs.py
python scripts/pm/publish_docs.py --dry-run
```

Dry runs do not read credentials or call Confluence. They plan destinations and
render the source set locally; they do not establish remote permissions or prove
that Confluence accepts a publication.

An apply requires a clean checkout matching fetched `origin/dev`, plus the API
secret in the environment. Apply intentionally replaces managed mirror content
with its GitHub source. Submit lasting changes through GitHub rather than editing
those mirrors directly.

## Recovery and operational limits

The homepage's `plaza-doc-mirrors` content property records generated page IDs and
successful source digests. Never delete it to force a refresh: doing so loses
identities for documents added after the bootstrap import. A partially completed
run can be retried. New page creation uses a deterministic title and source marker
to recover a successful create whose identity was not yet recorded. An unrelated
page with that title causes a clear failure instead of being adopted.

An API rate limit is retried with bounded waits; redirects and external pagination
URLs are rejected. A page-version conflict is re-read and retried at most twice.
An archive operation is polled and verified before success is reported. An
unfinished archive task is a failed run until a retry verifies its completion.

For an archived document that becomes ACTIVE, **restore the existing document in
Confluence**, then rerun. For a page whose mode changed, restore the expected mode
in Confluence. The public REST API does not provide a supported mode-conversion
operation, so the publisher fails rather than inventing a replacement document or
using a private conversion API. A deleted destination, wrong space, or disagreement
between the bootstrap and deployed map also requires correction before retrying.
After a source is promoted from exempt to governed, the publisher verifies the
actual UI-converted Live Doc and saves its new mode while retaining its ID. For a
bootstrap import, update the mode in DELIVERY-COORDINATES in the same source change;
the recorded bootstrap identity must still match the deployed document.

The deployed map is a Confluence content property, limited to 32 KiB. The publisher
fails explicitly if the set grows beyond that limit. Publishing is serialized
across both branches. A run publishes one immutable checkout; if `dev` advances
while it runs, the queued run reconciles the newer source afterward.

Live Docs are updated through the
[Confluence REST v2 Page API](https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/)
without changing their `subtype`. Archival uses the
[archive API](https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-content/#api-wiki-rest-api-content-archive-post)
and its long-running task result. Authenticated end-to-end verification remains
an activation step; local tests exercise an isolated API boundary.

*Last updated: October 2026*
