#!/usr/bin/env python3
"""Publish the committed registry to managed Confluence mirrors (PLZG-297).

Run --dry-run without credentials. API writes require --apply and an Actions
secret. Destination identities originate in DELIVERY-COORDINATES; newly created
identities are saved on the home page so interrupted runs can resume.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlencode, urljoin, urlsplit

import requests

from _atlassian_guard import validate_atlassian_site
from _confluence_format import markdown_to_storage

REPOSITORY = "adamtasteslikegood/10110TasteslikegoodPlaza"
SITE = "https://tasteslikegood.atlassian.net"
REGISTRY = "specs/meta/doc-registry.json"
SCHEMA = "specs/meta/spec-frontmatter.schema.json"
INDEXES = ("docs/README.md", "specs/README.md", "specs/meta/README.md", REGISTRY)
HISTORY = {"HISTORICAL", "SUPERSEDED"}
MAP_KEY = "plaza-doc-mirrors"
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


@dataclass
class Document:
    path: str
    raw: str
    status: str
    authority: str
    mode: str
    governed: bool


def safe_source(root, path):
    if not isinstance(path, str) or not path or "\\" in path:
        raise ValueError("Invalid source path")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or str(parsed) != path:
        raise ValueError(f"Unsafe source path: {path}")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Escaping source path: {path}")
    return resolved


def load_documents(root):
    registry = json.loads((root / REGISTRY).read_text())
    docs, seen = [], set()
    for governed, rows in ((True, registry["documents"]), (False, registry["exempt"])):
        for row in rows:
            path = row["path"]
            source = safe_source(root, path)
            if path in seen:
                raise ValueError(f"Duplicate registry path: {path}")
            seen.add(path)
            if not source.is_file():
                if governed:
                    raise ValueError(f"Missing governed source: {path}")
                continue
            raw = source.read_text()
            fm = FRONTMATTER.match(raw)
            declared = (
                re.search(
                    r"^status:\s*(ACTIVE|DRAFT|HISTORICAL|SUPERSEDED)\s*$", fm[1], re.M
                )
                if fm
                else None
            )
            status = row.get("status", declared[1] if declared else "REFERENCE")
            authority = (
                f"tier {row['tier']} / {row['authority']}"
                if governed
                else "exempt / reference"
            )
            mode = "live_doc" if governed or path in INDEXES else "page"
            docs.append(Document(path, raw, status, authority, mode, governed))
    for path in (REGISTRY, SCHEMA):
        if path in seen:
            raise ValueError(f"Governance metadata unexpectedly registered: {path}")
        docs.append(
            Document(
                path,
                safe_source(root, path).read_text(),
                "METADATA",
                "governance metadata",
                "live_doc",
                False,
            )
        )
    missing = set(INDEXES) | {"README.md"}
    missing -= {d.path for d in docs}
    if missing:
        raise ValueError(f"Missing required indexes: {sorted(missing)}")
    return docs


def validate_destinations(pages, home_id):
    ids = {home_id}
    for path, dest in pages.items():
        safe_source(Path("/source"), path)
        page_id = str(dest.get("id", ""))
        if (
            not page_id.isdigit()
            or page_id in ids
            or dest.get("mode") not in {"page", "live_doc"}
        ):
            raise ValueError(f"Invalid or duplicate destination for {path}")
        ids.add(page_id)


def load_coordinates(root):
    text = (root / "docs/delivery-coordinates.md").read_text()
    match = re.search(
        r"<!-- confluence-doc-mirrors:start -->(.*?)<!-- confluence-doc-mirrors:end -->",
        text,
        re.S,
    )
    if not match:
        raise ValueError("Missing documentation mirror coordinates")
    space, home = re.search(r"Space id: `(\d+)`", match[1]), re.search(
        r"Home id: `(\d+)`", match[1]
    )
    if not space or not home:
        raise ValueError("Missing space/home coordinates")
    rows = re.findall(
        r"^\| `([^`]+)` \| `(\d+)` \| (page|live_doc) \|$", match[1], re.M
    )
    pages = {path: {"id": page_id, "mode": mode} for path, page_id, mode in rows}
    if not pages or len(pages) != len(rows):
        raise ValueError("Empty or duplicate bootstrap destinations")
    validate_destinations(pages, home[1])
    return {"spaceId": space[1], "homeId": home[1], "pages": pages}


def page_url(page_id):
    return f"{SITE}/wiki/pages/{page_id}"


def render_document(doc, documents, destinations, commit, version, *, home=False):
    escaped_path = quote(doc.path, safe="/")
    source = f"https://github.com/{REPOSITORY}/blob/dev/{escaped_path}"
    revision = (
        f"https://github.com/{REPOSITORY}/blob/{quote(commit, safe='')}/{escaped_path}"
    )
    header = (
        f'<p><strong>GitHub source mirror</strong> · <a href="{source}">{html.escape(doc.path)}</a> · '
        f'<a href="{revision}">Source revision {html.escape(commit)}</a> · '
        f"Document set {html.escape(version)}</p><p>{html.escape(doc.authority)} · "
        f"Source status: {html.escape(doc.status)}. GitHub dev is the source of truth; "
        "merged-source updates are published by GitHub Actions. Edit the GitHub source rather than this mirror.</p>"
        f"<p><code>plaza-source:{html.escape(doc.path)}</code></p><hr />"
    )
    fm = FRONTMATTER.match(doc.raw)
    markdown = doc.raw[fm.end() :] if fm else doc.raw
    if doc.path.endswith(".json"):
        markdown = "```json\n" + doc.raw + "\n```\n"
    rendered = markdown_to_storage(markdown)

    def absolute_link(match):
        attr, value = match.groups()
        value = html.unescape(value)
        if value.startswith("#") or urlsplit(value).scheme or value.startswith("//"):
            return match[0]
        target = urljoin(source, value)
        return f'{attr}="{html.escape(target, quote=True)}"'

    rendered = re.sub(r'(href|src)="([^"]*)"', absolute_link, rendered)
    if doc.path in INDEXES or home:
        if home or doc.path == REGISTRY:
            listed = documents
        else:
            prefix = doc.path.rsplit("/", 1)[0] + "/"
            listed = [d for d in documents if d.path.startswith(prefix)]
        rows = []
        for child in listed:
            dest = destinations.get(child.path)
            name = html.escape(child.path)
            if dest:
                name = f'<a href="{page_url(dest["id"])}">{name}</a>'
            state = "archived" if child.status in HISTORY else "current"
            rows.append(
                f"<tr><td>{name}</td><td>{html.escape(child.status)}</td><td>{html.escape(child.authority)}</td><td>{state}</td></tr>"
            )
        rendered += (
            "<hr /><h2>Imported document record</h2><p>Derived from the committed registry. This record does not grant document authority.</p><table><tbody><tr><th>GitHub source / Confluence mirror</th><th>Source status</th><th>Authority</th><th>Mirror state</th></tr>"
            + "".join(rows)
            + "</tbody></table>"
        )
    return header + rendered


class ApiError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class ConfluenceClient:
    def __init__(self, site, token, *, session=None, pause=time.sleep):
        host = validate_atlassian_site(site)
        self.site = f"https://{host}"
        self.token = token
        self.session = session or requests.Session()
        self.pause = pause

    def request(self, method, path, payload=None):
        parsed = urlsplit(path)
        if (
            parsed.scheme
            or parsed.netloc
            or not parsed.path.startswith(("/wiki/api/v2/", "/wiki/rest/api/"))
            or ".." in parsed.path.split("/")
        ):
            raise ValueError(
                "Refusing API request outside the configured Confluence site"
            )
        for attempt in range(5):
            self.pause(0.4)
            try:
                response = self.session.request(
                    method,
                    self.site + path,
                    json=payload,
                    headers={
                        "Authorization": f"Basic {self.token}",
                        "Accept": "application/json",
                    },
                    timeout=(10, 60),
                    allow_redirects=False,
                )
            except requests.RequestException:
                if method != "GET" or attempt == 4:
                    raise ApiError(
                        0,
                        "Confluence transport failed; rerun to reconcile partial progress",
                    ) from None
                self.pause(2**attempt)
                continue
            retry = response.status_code == 429 or (
                method == "GET" and response.status_code in {502, 503, 504}
            )
            if retry and attempt < 4:
                try:
                    delay = float(response.headers.get("Retry-After", 2**attempt))
                except ValueError:
                    delay = 2**attempt
                if not 0 <= delay <= 300:
                    raise ApiError(
                        response.status_code,
                        "Confluence retry window exceeds this run's limit",
                    )
                self.pause(delay)
                continue
            if not 200 <= response.status_code < 300:
                raise ApiError(
                    response.status_code,
                    f"Confluence {method} {parsed.path} returned HTTP {response.status_code}; response body suppressed",
                )
            return response.json() if response.content else {}
        raise ApiError(0, "Confluence retry limit exhausted")


def get_property(client, page_id, key):
    path = f"/wiki/api/v2/pages/{page_id}/properties?" + urlencode(
        {"key": key, "limit": 250}
    )
    while path:
        data = client.request("GET", path)
        for prop in data.get("results", []):
            if prop["key"] == key:
                return prop
        path = data.get("_links", {}).get("next")
    return None


def save_property(client, page_id, key, value):
    if len(json.dumps(value).encode()) > 32768:
        raise ValueError(
            "Confluence mirror state exceeds the 32 KiB content-property limit"
        )
    old = get_property(client, page_id, key)
    if old and old["value"] == value:
        return old
    path = f"/wiki/api/v2/pages/{page_id}/properties"
    payload = {"key": key, "value": value}
    if old:
        payload["version"] = {"number": old["version"]["number"] + 1}
        path += "/" + str(old["id"])
    return client.request("PUT" if old else "POST", path, payload)


def get_page(client, page_id):
    for status in ("current", "archived"):
        try:
            return client.request(
                "GET",
                f"/wiki/api/v2/pages/{page_id}?body-format=storage&status={status}",
            )
        except ApiError as error:
            if error.status != 404 or status == "archived":
                raise
    raise ValueError(f"Missing Confluence page: {page_id}")


def check_page(page, coordinates, mode):
    if str(page.get("spaceId")) != coordinates["spaceId"]:
        raise ValueError(f"Page {page.get('id')} belongs to another space")
    actual_mode = "live_doc" if page.get("subtype") == "live" else "page"
    if actual_mode != mode:
        raise ValueError(
            f"Page {page.get('id')} mode changed; restore {mode} in Confluence before publishing"
        )


def update_page(client, page, value, commit):
    for attempt in range(3):
        payload = {
            "id": page["id"],
            "status": "current",
            "title": page["title"],
            "body": {"representation": "storage", "value": value},
            "version": {
                "number": page["version"]["number"] + 1,
                "message": f"GitHub dev source {commit}",
            },
        }
        try:
            return client.request("PUT", f'/wiki/api/v2/pages/{page["id"]}', payload)
        except ApiError as error:
            if error.status != 409 or attempt == 2:
                raise
            fresh = get_page(client, page["id"])
            if (
                fresh.get("status") != "current"
                or fresh.get("spaceId") != page.get("spaceId")
                or fresh.get("subtype") != page.get("subtype")
            ):
                raise ValueError(
                    "Page destination changed during publication"
                ) from error
            page = fresh
    raise ValueError("Page update conflict limit exhausted")


def archive_page(client, page):
    if page.get("status") == "archived":
        return
    task = client.request(
        "POST", "/wiki/rest/api/content/archive", {"pages": [{"id": int(page["id"])}]}
    )
    task_id = str(task.get("id", ""))
    if not re.fullmatch(r"[A-Za-z0-9-]+", task_id):
        raise ValueError("Archive did not return a valid long-task id")
    for _ in range(30):
        progress = client.request("GET", f"/wiki/rest/api/longtask/{task_id}")
        if progress.get("finished"):
            if (
                not progress.get("successful")
                or get_page(client, page["id"]).get("status") != "archived"
            ):
                raise ValueError("Confluence archive task failed")
            return
        time.sleep(2)
    raise ValueError("Archive task is pending; rerun to verify completion")


def publish(root, client, commit):
    documents, coordinates = load_documents(root), load_coordinates(root)
    version = json.loads((root / REGISTRY).read_text())["doc_set_version"]
    home = get_page(client, coordinates["homeId"])
    check_page(home, coordinates, "page")
    if home.get("status") != "current":
        raise ValueError("The configured Confluence home is archived")
    prop = get_property(client, home["id"], MAP_KEY)
    state = (
        prop["value"]
        if prop
        else {"repository": REPOSITORY, "pages": coordinates["pages"]}
    )
    if state.get("repository") != REPOSITORY:
        raise ValueError("Confluence mirror state belongs to another repository")
    pages = state["pages"]
    for path, bootstrap in coordinates["pages"].items():
        if path in pages and pages[path]["id"] != bootstrap["id"]:
            raise ValueError(f"Bootstrap and stored destination disagree: {path}")
        pages.setdefault(path, bootstrap)
    validate_destinations(pages, home["id"])
    desired_modes = {doc.path: doc.mode for doc in documents}
    for doc in documents:
        bootstrap = coordinates["pages"].get(doc.path)
        if bootstrap and bootstrap["mode"] != doc.mode:
            raise ValueError(
                f"Convert {doc.path} to {doc.mode} and update its bootstrap mode in DELIVERY-COORDINATES before publishing"
            )
    remote = {}
    active = {d.path for d in documents if d.status not in HISTORY}
    for path, dest in pages.items():
        page = get_page(client, dest["id"])
        desired_mode = desired_modes.get(path, dest["mode"])
        check_page(page, coordinates, desired_mode)
        dest["mode"] = desired_mode
        if path in active and page.get("status") == "archived":
            raise ValueError(
                f"Please restore reactivated source {path} in Confluence before publishing"
            )
        remote[path] = page
    result = {
        "created": 0,
        "updated": 0,
        "archived": 0,
        "unchanged": 0,
        "commit": commit,
    }
    # Preflight recovery across current AND archived content before any writes.
    # A completed creation may have been archived before its id was recorded.
    recovered, parents = {}, {}
    for doc in documents:
        if doc.path in pages:
            continue
        parent_path = (
            "specs/meta/README.md"
            if doc.path.startswith("specs/meta/")
            else (
                "specs/README.md"
                if doc.path.startswith("specs/")
                else "docs/README.md" if doc.path.startswith("docs/") else None
            )
        )
        parent_id = pages[parent_path]["id"] if parent_path else home["id"]
        parents[doc.path] = parent_id
        matches_by_id = {}
        for status in ("current", "archived"):
            query = urlencode(
                {
                    "space-id": coordinates["spaceId"],
                    "title": doc.path,
                    "status": status,
                    "body-format": "storage",
                    "limit": 250,
                }
            )
            path = "/wiki/api/v2/pages?" + query
            visited = set()
            while path:
                if path in visited:
                    raise ValueError("Recovery pagination loop")
                visited.add(path)
                data = client.request("GET", path)
                for candidate in data.get("results", []):
                    matches_by_id[candidate["id"]] = candidate
                path = data.get("_links", {}).get("next")
        matches = list(matches_by_id.values())
        if len(matches) > 1:
            raise ValueError(f"Multiple recovery candidates for {doc.path}")
        if matches:
            page = matches[0]
            if (
                f"plaza-source:{html.escape(doc.path)}"
                not in page.get("body", {}).get("storage", {}).get("value", "")
                or str(page.get("parentId")) != parent_id
            ):
                raise ValueError(f"Refusing to adopt unrelated page titled {doc.path}")
            check_page(page, coordinates, doc.mode)
            if doc.status not in HISTORY and page.get("status") == "archived":
                raise ValueError(
                    f"Please restore recovered archived source {doc.path} in Confluence before publishing"
                )
            recovered[doc.path] = page
    # Create identities before rendering indexes, recording each immediately.
    for doc in documents:
        if doc.path in pages:
            continue
        page = recovered.get(doc.path)
        if page is None:
            payload = {
                "spaceId": coordinates["spaceId"],
                "parentId": parents[doc.path],
                "title": doc.path,
                "status": "current",
                "body": {
                    "representation": "storage",
                    "value": render_document(doc, documents, pages, commit, version),
                },
            }
            if doc.mode == "live_doc":
                payload["subtype"] = "live"
            page = client.request("POST", "/wiki/api/v2/pages", payload)
            result["created"] += 1
        check_page(page, coordinates, doc.mode)
        pages[doc.path] = {"id": page["id"], "mode": doc.mode}
        remote[doc.path] = page
        validate_destinations(pages, home["id"])
        save_property(client, home["id"], MAP_KEY, state)
    # Render everything before modifying existing content: malformed sources or
    # converter errors cannot leave a partly refreshed set of existing pages.
    bodies = {
        d.path: render_document(d, documents, pages, commit, version) for d in documents
    }
    digests = {
        d.path: hashlib.sha256(
            render_document(d, documents, pages, "SOURCE", version).encode()
        ).hexdigest()
        for d in documents
    }
    for doc in documents:
        page, dest = remote[doc.path], pages[doc.path]
        if page.get("status") == "archived":
            result["unchanged"] += 1
            continue
        if (
            dest.get("digest") != digests[doc.path]
            or dest.get("publishedVersion") != page["version"]["number"]
        ):
            page = update_page(client, page, bodies[doc.path], commit)
            dest.update(
                digest=digests[doc.path],
                commit=commit,
                publishedVersion=page["version"]["number"],
            )
            save_property(client, home["id"], MAP_KEY, state)
            result["updated"] += 1
        else:
            result["unchanged"] += 1
        if doc.status in HISTORY:
            archive_page(client, page)
            result["archived"] += 1
    for path in set(pages) - {d.path for d in documents}:
        if remote[path].get("status") != "archived":
            archive_page(client, remote[path])
            result["archived"] += 1
    overview = next(d for d in documents if d.path == "README.md")
    home_body = render_document(overview, documents, pages, commit, version, home=True)
    home_digest = hashlib.sha256(
        render_document(
            overview, documents, pages, "SOURCE", version, home=True
        ).encode()
    ).hexdigest()
    if (
        state.get("homeDigest") != home_digest
        or state.get("homePublishedVersion") != home["version"]["number"]
    ):
        home = update_page(client, home, home_body, commit)
        state["homeDigest"] = home_digest
        state["homePublishedVersion"] = home["version"]["number"]
        save_property(client, home["id"], MAP_KEY, state)
    # Also persist verified mode transitions even if their content did not change.
    save_property(client, home["id"], MAP_KEY, state)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--dry-run", action="store_true")
    choice.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    documents = load_documents(args.root)
    coordinates = load_coordinates(args.root)
    if args.dry_run:
        version = json.loads((args.root / REGISTRY).read_text())["doc_set_version"]
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "source_branch": "dev",
                    "spaceId": coordinates["spaceId"],
                    "homeId": coordinates["homeId"],
                    "documents": [
                        {
                            "path": d.path,
                            "status": d.status,
                            "mode": d.mode,
                            "destination": coordinates["pages"].get(d.path),
                            "storage_bytes": len(
                                render_document(
                                    d,
                                    documents,
                                    coordinates["pages"],
                                    "DRY-RUN",
                                    version,
                                ).encode()
                            ),
                        }
                        for d in documents
                    ],
                },
                indent=2,
            )
        )
        return 0
    token = os.environ.get("ATLASSIAN_API_TOKEN_BASE64", "")
    if not token:
        raise ValueError(
            "Set the ATLASSIAN_API_TOKEN_BASE64 Actions secret before applying"
        )
    # Apply only a clean, fetched dev tree. A local invocation cannot accidentally
    # publish an unmerged branch or a dirty checkout with production credentials.
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=args.root, text=True
    ).strip()
    dev = subprocess.check_output(
        ["git", "rev-parse", "origin/dev"], cwd=args.root, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=args.root, text=True
    ).strip()
    if commit != dev or dirty:
        raise ValueError("Apply requires a clean checkout of fetched origin/dev")
    print(
        json.dumps(publish(args.root, ConfluenceClient(SITE, token), commit), indent=2)
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, ApiError) as error:
        raise SystemExit(str(error)) from None
