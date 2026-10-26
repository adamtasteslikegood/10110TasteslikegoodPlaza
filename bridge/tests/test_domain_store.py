"""Reusable terminal-store contract; future stores supply another factory."""

import pytest

from bridge.domain_protocol import DomainCommandError
from bridge.domain_store import MemoryStore


@pytest.fixture(params=[MemoryStore], ids=["memory"])
def store_factory(request):
    return request.param


@pytest.fixture
def store(store_factory):
    return store_factory()


def terminal(request_id="request", output="done", **fields):
    return dict(
        type="domain_result",
        request_id=request_id,
        agent_id="backend-architect",
        task="work",
        output=output,
        memory={"saved": True},
        **fields,
    )


def test_new_and_fresh_stores_have_no_restart_history(store, store_factory):
    empty = store.replay(0)
    assert empty.entries == []
    assert empty.high_water_mark == 0
    assert empty.earliest_output_id is None
    assert empty.history_gap is False
    store.append(terminal())
    fresh = store_factory().replay(0)
    assert fresh.entries == [] and fresh.high_water_mark == 0
    assert fresh.earliest_output_id is None and fresh.history_gap is False


def test_append_assigns_dense_ids_in_order(store):
    first = store.append(terminal("one", output_id="999"))
    second = store.append(terminal("two"))
    assert [first["output_id"], second["output_id"]] == ["1", "2"]
    window = store.replay(0)
    assert [p["request_id"] for p in window.entries] == ["one", "two"]
    assert window.high_water_mark == 2 and window.earliest_output_id == 1
    assert window.history_gap is False


@pytest.mark.parametrize(
    "cursor, ids", [(0, ["1", "2"]), (1, ["2"]), (2, []), (99, [])]
)
def test_replay_cursor_edges(store, cursor, ids):
    store.append(terminal("one"))
    store.append(terminal("two"))
    window = store.replay(cursor)
    assert [p["output_id"] for p in window.entries] == ids
    assert window.high_water_mark == 2 and window.earliest_output_id == 1
    assert window.history_gap is False


@pytest.mark.parametrize("cursor", [True, False, -1, 1.0, "1", None])
def test_invalid_cursor_is_existing_protocol_error(store, cursor):
    with pytest.raises(DomainCommandError) as error:
        store.replay(cursor)
    assert error.value.code == "invalid_request"


def test_count_trim_preserves_highwater_and_bounds_request_lookup(store):
    for i in range(258):
        store.append(terminal(str(i)))
    window = store.replay(0)
    assert len(window.entries) == 256
    assert window.entries[0]["output_id"] == "3"
    assert window.entries[-1]["output_id"] == "258"
    assert window.high_water_mark == 258 and window.earliest_output_id == 3
    assert window.history_gap is True
    assert store.replay(1).history_gap is True
    assert store.replay(2).history_gap is False
    assert store.replay(258).entries == []
    assert store.find_request("0") is None
    assert store.find_request("1") is None
    assert store.find_request("2")["output_id"] == "3"
    assert store.append(terminal("0"))["output_id"] == "259"


def test_utf8_bytes_keep_exact_cap_then_trim_oldest(store):
    # Each output is 1 MiB in UTF-8, but only half that many characters.
    for i in range(4):
        store.append(terminal(str(i), output="é" * (512 * 1024)))
    at_cap = store.replay(0)
    assert len(at_cap.entries) == 4 and at_cap.history_gap is False
    store.append(terminal("overflow", output="x"))
    over_cap = store.replay(0)
    assert [p["output_id"] for p in over_cap.entries] == ["2", "3", "4", "5"]
    assert over_cap.earliest_output_id == 2 and over_cap.high_water_mark == 5
    assert over_cap.history_gap is True
    assert store.find_request("0") is None


def test_packet_metadata_does_not_count_as_output_bytes(store):
    for i in range(17):
        packet = terminal(str(i), output="")
        packet["task"] = "t" * (256 * 1024)
        store.append(packet)
    window = store.replay(0)
    assert len(window.entries) == 17
    assert window.earliest_output_id == 1 and window.history_gap is False


def test_empty_after_byte_trim_preserves_highwater_and_gap(store):
    result = store.append(terminal(output="x" * (4 * 1024 * 1024 + 1)))
    assert result["output_id"] == "1"  # Still deliver the terminal to its caller.
    window = store.replay(0)
    assert window.entries == [] and window.high_water_mark == 1
    assert window.earliest_output_id is None and window.history_gap is True
    assert store.replay(1).history_gap is False
    assert store.find_request("request") is None
    assert store.append(terminal("next"))["output_id"] == "2"
    assert store.replay(0).earliest_output_id == 2


def test_append_lookup_and_replay_are_independent_nested_copies(store):
    original = terminal()
    returned = store.append(original)
    original["memory"]["saved"] = False
    returned["output"] = "mutated"
    returned["memory"]["saved"] = False
    found = store.find_request("request")
    assert found["memory"] == {"saved": True} and found["output"] == "done"
    found["memory"]["saved"] = False
    window = store.replay(0)
    assert window.entries[0]["memory"] == {"saved": True}
    window.entries[0]["memory"]["saved"] = False
    window.entries.clear()
    assert store.replay(0).entries[0]["memory"] == {"saved": True}
    assert "output_id" not in original


def test_lookup_returns_oldest_retained_matching_request(store):
    store.append(terminal("same", output="first"))
    store.append(terminal("same", output="second"))
    assert store.find_request("same")["output"] == "first"
    assert store.find_request("missing") is None


def test_store_instances_do_not_share_history_or_sequence(store_factory):
    one, two = store_factory(), store_factory()
    one.append(terminal("one"))
    assert two.find_request("one") is None and two.replay(0).entries == []
    assert two.append(terminal("two"))["output_id"] == "1"
    assert one.find_request("two") is None
