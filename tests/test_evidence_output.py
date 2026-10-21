"""Fresh evidence publication must fail before spending and never replace history."""

import json
from pathlib import Path

import pytest

from scripts.evidence_output import FreshEvidenceOutput


def test_reserved_output_publishes_complete_json_once(tmp_path):
    output = tmp_path / "report.json"
    with FreshEvidenceOutput(output) as destination:
        assert not output.exists()
        with pytest.raises(FileExistsError):
            with FreshEvidenceOutput(output):
                pass
        destination.publish_json({"accepted": False, "errors": ["observed failure"]})
        assert json.loads(output.read_bytes()) == {
            "accepted": False,
            "errors": ["observed failure"],
        }
        with pytest.raises(ValueError):
            destination.publish_json({"accepted": True})
    assert list(tmp_path.iterdir()) == [output]


def test_atomic_publication_preserves_concurrent_evidence_and_unpublished_report(
    tmp_path,
):
    output = tmp_path / "report.json"
    staging = None
    with pytest.raises(FileExistsError):
        with FreshEvidenceOutput(output) as destination:
            staging = Path(destination._temporary.name)
            output.write_bytes(b"independent evidence")
            destination.publish_json({"accepted": False, "errors": ["interrupted"]})
    assert output.read_bytes() == b"independent evidence"
    assert staging.is_file(), "failed publication must retain the attempted report"
    assert json.loads(staging.read_bytes())["errors"] == ["interrupted"]


@pytest.mark.parametrize("kind", ["regular", "directory", "dangling-symlink"])
def test_preflight_preserves_every_existing_destination(tmp_path, kind):
    output = tmp_path / "report.json"
    if kind == "regular":
        output.write_bytes(b"prior report")
    elif kind == "directory":
        output.mkdir()
    else:
        output.symlink_to(tmp_path / "missing")
    before = output.lstat()
    with pytest.raises(FileExistsError):
        with FreshEvidenceOutput(output):
            pytest.fail("existing output cannot be reserved")
    assert output.lstat() == before
