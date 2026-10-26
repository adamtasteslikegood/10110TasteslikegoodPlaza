"""Regression tests for source-driven Confluence publication (PLZG-297)."""

import copy
import importlib
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "pm"))


@pytest.fixture
def publisher():
    return importlib.import_module("publish_docs")


@pytest.fixture
def source(tmp_path):
    files = {
        "README.md": "# Plaza\n\n[Design](docs/design.md)\n",
        "docs/README.md": "# docs/\n\nDesign index.\n",
        "specs/README.md": "# specs/\n\nDelivery index.\n",
        "specs/meta/README.md": "# Meta index\n",
        "docs/design.md": "# Design\n\n[Roadmap](../specs/README.md)\n\n```text\n[x](relative.md)\n```\n",
        "specs/old.md": "# Closed sprint\n",
        "specs/meta/spec-frontmatter.schema.json": '{"type":"object"}',
    }
    for path, text in files.items():
        p = tmp_path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    registry = {
        "doc_set_version": "0.2.18",
        "documents": [
            {
                "path": "README.md",
                "doc_id": "PROJECT",
                "tier": 2,
                "authority": "derived",
                "status": "ACTIVE",
            },
            {
                "path": "specs/meta/README.md",
                "doc_id": "META",
                "tier": 0,
                "authority": "summary",
                "status": "ACTIVE",
            },
            {
                "path": "docs/design.md",
                "doc_id": "DESIGN",
                "tier": 2,
                "authority": "implementation",
                "status": "ACTIVE",
            },
            {
                "path": "specs/old.md",
                "doc_id": "OLD",
                "tier": 3,
                "authority": "delivery",
                "status": "HISTORICAL",
            },
        ],
        "exempt": [
            {"path": "docs/README.md"},
            {"path": "specs/README.md"},
            {"path": "report.md"},
        ],
    }
    (tmp_path / "specs/meta/doc-registry.json").write_text(json.dumps(registry))
    modes = {
        "README.md": ("11", "live_doc"),
        "docs/README.md": ("12", "live_doc"),
        "specs/meta/README.md": ("13", "live_doc"),
        "specs/meta/doc-registry.json": ("14", "live_doc"),
        "specs/meta/spec-frontmatter.schema.json": ("15", "live_doc"),
        "specs/README.md": ("16", "live_doc"),
        "specs/old.md": ("17", "live_doc"),
    }
    table = "\n".join(
        f"| `{path}` | `{page_id}` | {mode} |"
        for path, (page_id, mode) in modes.items()
    )
    (tmp_path / "docs/delivery-coordinates.md").write_text(
        "<!-- confluence-doc-mirrors:start -->\nSpace id: `99`\nHome id: `10`\n"
        + table
        + "\n<!-- confluence-doc-mirrors:end -->"
    )
    return tmp_path


def test_registry_retains_history_omits_generated_absence_and_rejects_missing_governed(
    publisher, source
):
    docs = publisher.load_documents(source)
    assert "report.md" not in [d.path for d in docs]
    assert next(d for d in docs if d.path == "specs/old.md").status == "HISTORICAL"
    (source / "docs/design.md").unlink()
    with pytest.raises(ValueError, match="Missing governed"):
        publisher.load_documents(source)


def test_registry_rejects_escaping_paths_and_duplicate_membership(publisher, source):
    p = source / "specs/meta/doc-registry.json"
    r = json.loads(p.read_text())
    r["exempt"].append({"path": "../outside.md"})
    p.write_text(json.dumps(r))
    with pytest.raises(ValueError, match="path"):
        publisher.load_documents(source)
    r["exempt"][-1] = {"path": "README.md"}
    p.write_text(json.dumps(r))
    with pytest.raises(ValueError, match="Duplicate"):
        publisher.load_documents(source)


def test_render_resolves_links_without_rewriting_code_and_indexes_destinations(
    publisher, source
):
    docs = publisher.load_documents(source)
    coords = publisher.load_coordinates(source)
    doc = next(d for d in docs if d.path == "docs/design.md")
    rendered = publisher.render_document(
        doc, docs, coords["pages"], "abc1234", "0.2.18"
    )
    assert (
        'href="https://github.com/adamtasteslikegood/10110TasteslikegoodPlaza/blob/dev/specs/README.md"'
        in rendered
    )
    assert "[x](relative.md)" in rendered
    assert "abc1234" in rendered
    index = next(d for d in docs if d.path == "docs/README.md")
    indexed = publisher.render_document(
        index,
        docs,
        {**coords["pages"], "docs/design.md": {"id": "100", "mode": "live_doc"}},
        "abc1234",
        "0.2.18",
    )
    assert "/pages/100" in indexed
    assert "implementation" in indexed


class MemoryConfluence:
    """In-memory REST boundary; state changes represent observable server effects."""

    def __init__(self, coords):
        self.pages = {
            "10": {
                "id": "10",
                "spaceId": "99",
                "title": "Home",
                "status": "current",
                "version": {"number": 1},
                "body": {"storage": {"value": ""}},
            }
        }
        for path, dest in coords["pages"].items():
            self.pages[dest["id"]] = {
                "id": dest["id"],
                "spaceId": "99",
                "title": path,
                "status": "archived" if path == "specs/old.md" else "current",
                "subtype": "live",
                "version": {"number": 1},
                "body": {"storage": {"value": ""}},
            }
        self.props = {}
        self.updates = 0
        self.fail_path = None
        self.conflict = False
        self.failed_archive = False

    def request(self, method, path, payload=None):
        parsed = urlsplit(path)
        parts = parsed.path.strip("/").split("/")
        query = parse_qs(parsed.query)
        if parsed.path == "/wiki/rest/api/content/archive":
            for p in payload["pages"]:
                self.pages[str(p["id"])]["status"] = "archived"
            return {"id": "task1"}
        if parsed.path.startswith("/wiki/rest/api/longtask/"):
            return {"finished": True, "successful": not self.failed_archive}
        if len(parts) >= 6 and parts[5] == "properties":
            page_id = parts[4]
            if method == "GET":
                return {
                    "results": [
                        copy.deepcopy(v)
                        for (p, key), v in self.props.items()
                        if p == page_id and key == query.get("key", [None])[0]
                    ]
                }
            key = payload["key"]
            old = self.props.get((page_id, key))
            version = old["version"]["number"] + 1 if old else 1
            self.props[(page_id, key)] = {
                "id": str(len(self.props) + 500) if not old else old["id"],
                "key": key,
                "value": copy.deepcopy(payload["value"]),
                "version": {"number": version},
            }
            return copy.deepcopy(self.props[(page_id, key)])
        if len(parts) == 4 and parts[-1] == "pages":
            if method == "GET":
                return {
                    "results": [
                        copy.deepcopy(p)
                        for p in self.pages.values()
                        if p["title"] == query.get("title", [None])[0]
                        and p["status"] == query.get("status", ["current"])[0]
                    ]
                }
            page_id = str(len(self.pages) + 100)
            self.pages[page_id] = {
                **copy.deepcopy(payload),
                "id": page_id,
                "version": {"number": 1},
                "body": {"storage": {"value": payload["body"]["value"]}},
            }
            return copy.deepcopy(self.pages[page_id])
        if len(parts) == 5 and parts[3] == "pages":
            page_id = parts[4]
            page = self.pages[page_id]
            if method == "GET":
                if page["status"] != query.get("status", ["current"])[0]:
                    raise self.api_error(404)
                return copy.deepcopy(page)
            if self.fail_path == page["title"]:
                raise RuntimeError("write failed")
            if self.conflict:
                self.conflict = False
                page["version"]["number"] += 1
                raise self.api_error(409)
            assert payload["version"]["number"] == page["version"]["number"] + 1
            assert (
                "subtype" not in payload
            ), "Updating subtype risks converting Live Docs"
            page.update(
                {
                    "title": payload["title"],
                    "version": payload["version"],
                    "body": {"storage": {"value": payload["body"]["value"]}},
                }
            )
            self.updates += 1
            return copy.deepcopy(page)
        raise AssertionError((method, path, payload))

    @staticmethod
    def api_error(status):
        import publish_docs

        return publish_docs.ApiError(status, "API error")


def test_apply_reuses_imports_persists_new_ids_and_is_repeatable(publisher, source):
    api = MemoryConfluence(publisher.load_coordinates(source))
    api.conflict = True
    result = publisher.publish(source, api, "abc1234")
    assert result["created"] == 1
    assert api.pages["11"]["subtype"] == "live"
    assert "docs/design.md" in api.props[("10", "plaza-doc-mirrors")]["value"]["pages"]
    assert len(api.pages) == 9
    updates = api.updates
    publisher.publish(source, api, "nextsha")
    assert api.updates == updates
    assert len(api.pages) == 9


def test_parent_record_updates_when_only_registry_membership_changes(publisher, source):
    api = MemoryConfluence(publisher.load_coordinates(source))
    publisher.publish(source, api, "abc1234")
    p = source / "specs/meta/doc-registry.json"
    r = json.loads(p.read_text())
    r["documents"] = [d for d in r["documents"] if d["path"] != "docs/design.md"]
    p.write_text(json.dumps(r))
    (source / "docs/design.md").unlink()
    publisher.publish(source, api, "def5678")
    design_id = api.props[("10", "plaza-doc-mirrors")]["value"]["pages"][
        "docs/design.md"
    ]["id"]
    assert api.pages[design_id]["status"] == "archived"
    assert "docs/design.md" not in api.pages["12"]["body"]["storage"]["value"]


def test_manual_mirror_edit_is_replaced_by_committed_source(publisher, source):
    api = MemoryConfluence(publisher.load_coordinates(source))
    publisher.publish(source, api, "abc1234")
    api.pages["11"]["body"]["storage"]["value"] = "manual drift"
    api.pages["11"]["version"]["number"] += 1
    publisher.publish(source, api, "def5678")
    assert "manual drift" not in api.pages["11"]["body"]["storage"]["value"]
    assert "Plaza" in api.pages["11"]["body"]["storage"]["value"]


def test_recover_unrecorded_creation_without_duplicate(publisher, source):
    api = MemoryConfluence(publisher.load_coordinates(source))
    documents = publisher.load_documents(source)
    doc = next(d for d in documents if d.path == "docs/design.md")
    api.pages["999"] = {
        "id": "999",
        "spaceId": "99",
        "title": doc.path,
        "parentId": "12",
        "subtype": "live",
        "status": "current",
        "version": {"number": 1},
        "body": {
            "storage": {
                "value": publisher.render_document(
                    doc, documents, {}, "abc1234", "0.2.18"
                )
            }
        },
    }
    result = publisher.publish(source, api, "abc1234")
    assert result["created"] == 0
    assert len(api.pages) == 9
    assert (
        api.props[("10", "plaza-doc-mirrors")]["value"]["pages"][doc.path]["id"]
        == "999"
    )


def test_archive_failure_is_reported_not_treated_as_completed(publisher, source):
    api = MemoryConfluence(publisher.load_coordinates(source))
    api.pages["17"]["status"] = "current"
    api.failed_archive = True
    with pytest.raises(ValueError, match="archive task failed"):
        publisher.publish(source, api, "abc1234")


def test_mismatched_governed_mode_fails_before_creating_anything(publisher, source):
    api = MemoryConfluence(publisher.load_coordinates(source))
    # A manual page conversion must not be silently accepted or converted back.
    api.pages["11"].pop("subtype")
    with pytest.raises(ValueError, match="mode"):
        publisher.publish(source, api, "abc1234")
    assert api.updates == 0
    assert len(api.pages) == 8


def test_source_mode_change_fails_before_new_document_creation(publisher, source):
    p = source / "docs/delivery-coordinates.md"
    p.write_text(
        p.read_text().replace(
            "| `specs/old.md` | `17` | live_doc |", "| `specs/old.md` | `17` | page |"
        )
    )
    api = MemoryConfluence(publisher.load_coordinates(source))
    api.pages["17"].pop("subtype")
    with pytest.raises(ValueError, match="Convert"):
        publisher.publish(source, api, "abc1234")
    assert len(api.pages) == 8


def test_dry_run_renders_documents_without_api_credentials(
    publisher, source, capsys, monkeypatch
):
    monkeypatch.delenv("ATLASSIAN_API_TOKEN_BASE64", raising=False)
    assert publisher.main(["--root", str(source), "--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["dry_run"] is True
    assert all(d["storage_bytes"] > 0 for d in plan["documents"])


def test_source_symlink_cannot_escape_repository(publisher, source):
    sibling = source.parent / (source.name + "-outside.md")
    sibling.write_text("outside")
    (source / "docs/design.md").unlink()
    (source / "docs/design.md").symlink_to(sibling)
    with pytest.raises(ValueError, match="path"):
        publisher.load_documents(source)


def test_promoted_dynamic_document_recovers_after_ui_mode_conversion(publisher, source):
    p = source / "specs/meta/doc-registry.json"
    registry = json.loads(p.read_text())
    design = registry["documents"].pop(2)
    registry["exempt"].append({"path": "docs/design.md"})
    p.write_text(json.dumps(registry))
    api = MemoryConfluence(publisher.load_coordinates(source))
    publisher.publish(source, api, "first")
    page_id = api.props[("10", "plaza-doc-mirrors")]["value"]["pages"][
        "docs/design.md"
    ]["id"]
    registry["exempt"].pop()
    registry["documents"].append(design)
    p.write_text(json.dumps(registry))
    api.pages[page_id]["subtype"] = "live"  # owner completes requested UI conversion
    publisher.publish(source, api, "promoted")
    assert (
        api.props[("10", "plaza-doc-mirrors")]["value"]["pages"]["docs/design.md"][
            "mode"
        ]
        == "live_doc"
    )
    assert len(api.pages) == 9


def test_archived_unrecorded_creation_requires_restore_without_any_writes(
    publisher, source
):
    api = MemoryConfluence(publisher.load_coordinates(source))
    docs = publisher.load_documents(source)
    doc = next(d for d in docs if d.path == "docs/design.md")
    api.pages["999"] = {
        "id": "999",
        "spaceId": "99",
        "title": doc.path,
        "parentId": "12",
        "subtype": "live",
        "status": "archived",
        "version": {"number": 1},
        "body": {
            "storage": {
                "value": publisher.render_document(doc, docs, {}, "first", "0.2.18")
            }
        },
    }
    with pytest.raises(ValueError, match="restore"):
        publisher.publish(source, api, "retry")
    assert len(api.pages) == 9
    assert api.updates == 0
    assert api.props == {}


def test_does_not_acknowledge_failed_page_or_touch_foreign_space(publisher, source):
    api = MemoryConfluence(publisher.load_coordinates(source))
    api.fail_path = "README.md"
    with pytest.raises(RuntimeError, match="write failed"):
        publisher.publish(source, api, "abc1234")
    stored = (
        api.props.get(("10", "plaza-doc-mirrors"), {}).get("value", {}).get("pages", {})
    )
    assert not stored.get("README.md", {}).get("digest")
    api.fail_path = None
    api.pages["11"]["spaceId"] = "12345"
    writes = api.updates
    with pytest.raises(ValueError, match="space"):
        publisher.publish(source, api, "abc1234")
    assert api.updates == writes


def test_reactivated_archive_requires_restore_without_recreating_it(publisher, source):
    api = MemoryConfluence(publisher.load_coordinates(source))
    p = source / "specs/meta/doc-registry.json"
    r = json.loads(p.read_text())
    r["documents"][-1]["status"] = "ACTIVE"
    p.write_text(json.dumps(r))
    with pytest.raises(ValueError, match="restore"):
        publisher.publish(source, api, "abc1234")
    assert len(api.pages) == 8


def test_request_retries_rate_limit_but_refuses_external_urls_and_redirects(publisher):
    import requests

    class Transport:
        def __init__(self):
            self.responses = [429, 200]
            self.count = 0

        def request(self, method, url, **kw):
            self.count += 1
            assert kw["allow_redirects"] is False
            r = requests.Response()
            r.status_code = self.responses.pop(0)
            r.headers["Retry-After"] = "0"
            r._content = b'{"ok":true}'
            return r

    transport = Transport()
    api = publisher.ConfluenceClient(
        "https://tasteslikegood.atlassian.net",
        "dXNlcjp0b2tlbg==",
        session=transport,
        pause=lambda _: None,
    )
    assert api.request("GET", "/wiki/api/v2/pages/10") == {"ok": True}
    assert transport.count == 2
    with pytest.raises(ValueError):
        api.request("GET", "https://attacker.invalid/wiki/api/v2/pages/10")
    transport.responses = [302]
    with pytest.raises(publisher.ApiError):
        api.request("GET", "/wiki/api/v2/pages/10")
