"""Synthetic reply shapes: extract only a terminal, unambiguous envelope."""

import json

import pytest

from bridge.conversation_backend import decode_project_reply


@pytest.mark.parametrize("fence", [False, True])
@pytest.mark.parametrize("commentary", ["", "I checked the café. 雪🚀"])
def test_final_envelope_preserves_commentary_and_unicode(fence, commentary):
    delta = {"summary": "Checked café", "next_action": "Review 雪"}
    envelope = json.dumps({"answer": "Ready. 雪🚀", "memory_delta": delta})
    if fence:
        envelope = "```json\n" + envelope + "\n```"
    raw = (commentary + "\n\n" if commentary else "") + envelope
    expected = (commentary + "\n\n" if commentary else "") + "Ready. 雪🚀"
    assert decode_project_reply(raw) == (expected, delta)


@pytest.mark.parametrize(
    "commentary, expected",
    [
        ("Ready. 雪", "Ready. 雪"),
        ("Checked first.\n\nReady. 雪", "Checked first.\n\nReady. 雪"),
        ("Ready. 雪\n\nMore detail.", "Ready. 雪\n\nMore detail."),
        ("Almost ready. 雪", "Almost ready. 雪\n\nReady. 雪"),
        ("Ready. 雪fall", "Ready. 雪fall\n\nReady. 雪"),
    ],
)
def test_only_verbatim_standalone_answer_is_deduplicated(commentary, expected):
    raw = commentary + '\n\n{"answer":"Ready. 雪","memory_delta":{}}'
    assert decode_project_reply(raw) == (expected, {})


@pytest.mark.parametrize(
    "raw",
    [
        "Plain prose. 雪🚀",
        'Inline {"answer":"example","memory_delta":{}} prose.',
        'Example:\n\n```json\n{"answer":"sample","memory_delta":{}}\n```',
        'For example:\n\n{"answer":"sample","memory_delta":{}}',
        'Here is an example.\n\n```json\n{"answer":"sample","memory_delta":{}}\n```',
        'Sample response\n\n{"answer":"sample","memory_delta":{}}',
        '```python\n{"answer":"sample","memory_delta":{}}\n```',
        '```python\n\n{"answer":"sample","memory_delta":{}}\n```',
        '```text\nCode:\n\n{"answer":"sample","memory_delta":{}}',
        '```json\n{"answer":"sample","memory_delta":{}}\n```\nExplanation.',
        '{"answer":"one"}\n\n{"answer":"two"}',
        '```json\n{"answer":"one"}\n```\n\n```json\n{"answer":"two"}\n```',
        '{"wrapper": {"answer":"sample","memory_delta":{}}}',
        '{"answer":"sample","other":"data"}',
        'Progress.\n\n{"answer":"sample","other":"data"}',
        '{"answer":"first","answer":"second"}',
        'Progress.\n\n{"answer":"yes","memory_delta":{"summary":"a","summary":"b"}}',
        'Progress.\n\n{"answer":"yes","memory_delta":{"summary":NaN}}',
        'Progress.\n\n{"answer":"unterminated}',
        'Progress.\n\n```json\n{"answer":"yes"}\n```\ntrailing text',
        'Progress.\n\n{"answer":5}',
        'Progress.\n\n{"answer":"\\ud800"}',
        "Progress.\n\n"
        + '{"answer":"yes","memory_delta":'
        + "[" * 10000
        + "0"
        + "]" * 10000
        + "}",
    ],
)
def test_ambiguous_malformed_and_example_output_remains_visible(raw):
    assert decode_project_reply(raw) == (raw, None)


def test_extraction_has_a_byte_bound_and_preserves_oversized_text():
    raw = json.dumps({"answer": "雪" * (256 * 1024 // 3)}, ensure_ascii=False)
    assert decode_project_reply(raw) == (raw, None)


def test_extraction_has_a_candidate_bound_and_preserves_ambiguous_text():
    raw = ("Paragraph.\n\n```python\npass\n```\n\n" * 33) + '{"answer":"yes"}'
    assert decode_project_reply(raw) == (raw, None)
