"""Tests for bridge.protocol — message types, parsing, validation."""

import pytest

from bridge.protocol import (
    RequestType,
    BridgeRequest,
    classify_request,
    parse_request,
    validate_request,
    make_error,
    make_success,
    make_domain_state,
)


class TestClassifyRequest:
    def test_no_type_defaults_to_conversation(self):
        assert (
            classify_request({"agent_id": "a", "task": "t"}) == RequestType.CONVERSATION
        )

    def test_domain_query(self):
        assert classify_request({"type": "domain_query"}) == RequestType.DOMAIN_QUERY

    def test_conversation_explicit(self):
        assert classify_request({"type": "conversation"}) == RequestType.CONVERSATION

    def test_resume(self):
        assert classify_request({"type": "resume"}) == RequestType.RESUME

    def test_unknown_type_defaults_to_conversation(self):
        assert classify_request({"type": "bogus"}) == RequestType.CONVERSATION


class TestParseRequest:
    def test_parses_domain_query(self):
        raw = {
            "type": "domain_query",
            "domain_id": "engineering",
            "agent_id": "systems-architect",
            "task": "Review auth middleware",
            "request_id": "abc-123",
        }
        req = parse_request(raw)
        assert req.type == RequestType.DOMAIN_QUERY
        assert req.domain_id == "engineering"
        assert req.agent_id == "systems-architect"
        assert req.task == "Review auth middleware"
        assert req.request_id == "abc-123"

    def test_parses_legacy_request_no_type(self):
        raw = {"agent_id": "security-auditor", "task": "What do you think?"}
        req = parse_request(raw)
        assert req.type == RequestType.CONVERSATION
        assert req.agent_id == "security-auditor"

    def test_generates_request_id_when_missing(self):
        req = parse_request({"agent_id": "a", "task": "t"})
        assert req.request_id != ""

    def test_parses_resume(self):
        raw = {"type": "resume", "domain_id": "engineering", "cursor": "5"}
        req = parse_request(raw)
        assert req.type == RequestType.RESUME
        assert req.cursor == "5"

    def test_missing_fields_default_to_empty(self):
        req = parse_request({})
        assert req.agent_id == ""
        assert req.task == ""
        assert req.domain_id == ""


class TestValidateRequest:
    def test_valid_conversation(self):
        req = BridgeRequest(type=RequestType.CONVERSATION, agent_id="a", task="t")
        assert validate_request(req) is None

    def test_conversation_missing_agent_id(self):
        req = BridgeRequest(type=RequestType.CONVERSATION, agent_id="", task="t")
        assert validate_request(req) is not None

    def test_conversation_missing_task(self):
        req = BridgeRequest(type=RequestType.CONVERSATION, agent_id="a", task="")
        assert validate_request(req) is not None

    def test_domain_query_missing_domain_id(self):
        req = BridgeRequest(
            type=RequestType.DOMAIN_QUERY, agent_id="a", task="t", domain_id=""
        )
        assert validate_request(req) is not None

    def test_domain_query_valid(self):
        req = BridgeRequest(
            type=RequestType.DOMAIN_QUERY,
            agent_id="a",
            task="t",
            domain_id="engineering",
        )
        assert validate_request(req) is None

    def test_resume_missing_domain_id(self):
        req = BridgeRequest(type=RequestType.RESUME, domain_id="")
        assert validate_request(req) is not None

    def test_resume_valid(self):
        req = BridgeRequest(type=RequestType.RESUME, domain_id="engineering")
        assert validate_request(req) is None


class TestResponseBuilders:
    def test_make_error(self):
        resp = make_error("agent-1", "do stuff", "not_found", "No agent")
        assert resp["status"] == "error"
        assert resp["error_type"] == "not_found"
        assert resp["agent_id"] == "agent-1"
        assert resp["output"] == ""

    def test_make_success(self):
        resp = make_success("agent-1", "do stuff", "result text")
        assert resp["status"] == "ok"
        assert resp["output"] == "result text"

    def test_make_success_with_domain_fields(self):
        resp = make_success(
            "agent-1",
            "do stuff",
            "result",
            domain_id="engineering",
            request_id="r1",
            output_id="3",
        )
        assert resp["domain_id"] == "engineering"
        assert resp["request_id"] == "r1"
        assert resp["output_id"] == "3"

    def test_make_domain_state(self):
        resp = make_domain_state("engineering", "backgrounded", 3)
        assert resp["type"] == "domain_state"
        assert resp["domain_id"] == "engineering"
        assert resp["state"] == "backgrounded"
        assert resp["unread_count"] == 3
