# Vendored from adamtasteslikegood/codex-pr-review-gate-cc, pr-lifecycle-relay/client/relay_work.py at main f10c59a (PR #59).
# Keep it in step with that file rather than editing it here. One local change: the
# error contract below now says what _send does (a non-JSON body is RelayRefused).
# A second, to be sent upstream too: the client names itself in User-Agent (PLZG-303).
"""relay_work: the relay's work claims from Python, for the game bridge (stdlib only, Python 3.10 or later).

The same API as client/relay-work.ts, and the same variables as pr-lifecycle: PR_GATE_RELAY_URL, then PR_GATE_RELAY_CLIENT_ID and
PR_GATE_RELAY_CLIENT_SECRET (an Access service token) or PR_GATE_RELAY_TOKEN (a person's token). A local dev relay with TLS=1 is trusted
through SSL_CERT_FILE, which its env files set.

    work = RelayWork.from_env("adamtasteslikegood/10110tasteslikegoodplaza", runtime="bridge", holder="bridge@host:domain-1")
    answer = work.claim("gh#12", branch="work/gh-12")          # answer["resume"] holds branch, commit, notes, steps
    with work.keepalive("gh#12"):                               # beats every 30 s in a thread while the block runs
        ...
        work.checkpoint("gh#12", "parser done", commit=sha, branch="work/gh-12", notes="notes/gh-12.md")
    work.release("gh#12", "done", "PR opened")

Every call returns the relay's JSON answer, or raises RelayRefused (held, lost, not allowed, not found, bad request, or a
non-JSON answer such as Access's login page for a missing or expired credential) or RelayDown (no answer, a 5xx or a timeout). The secret is the caller's: keep one per checkout or session, 32 characters or more,
and pass the same one again after a restart so a renewal works.
"""

from __future__ import annotations

import json
import os
import secrets
import ssl
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import Any, Iterator


class RelayRefused(Exception):
    def __init__(self, status: int, answer: dict[str, Any]):
        super().__init__(f"{status}: {answer.get('error', answer)}")
        self.status = status
        self.answer = answer


class RelayDown(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Access redirects mean refusal. Never forward credentials off the pinned origin.
        return None


# Cloudflare's Browser Integrity Check answers urllib's default User-Agent
# ("Python-urllib/3.x") with 403 "error code: 1010", before Access or the Worker.
USER_AGENT = "relay-work-py/1"


def new_secret() -> str:
    return secrets.token_hex(32)


class RelayWork:
    def __init__(
        self,
        url: str,
        headers: dict[str, str],
        repo: str,
        runtime: str,
        holder: str,
        secret: str,
        timeout: float = 10.0,
    ):
        if len(secret) < 32:
            raise ValueError("the secret must be at least 32 characters")
        self.endpoint = f"{url.rstrip('/')}/v1/{repo.lower()}/work"
        # A caller's own User-Agent wins, whatever its casing; else the default.
        named = any(key.lower() == "user-agent" for key in headers)
        self.headers = {
            **({} if named else {"user-agent": USER_AGENT}),
            **headers,
            "content-type": "application/json",
        }
        self.runtime = runtime
        self.holder = holder
        self.secret = secret
        self.timeout = timeout
        self.tokens: dict[str, int] = {}
        cafile = os.environ.get("SSL_CERT_FILE")
        self.context = (
            ssl.create_default_context(cafile=cafile)
            if cafile
            else ssl.create_default_context()
        )
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.context), _NoRedirect()
        )

    @classmethod
    def from_env(
        cls, repo: str, runtime: str, holder: str, secret: str | None = None
    ) -> "RelayWork":
        url = os.environ.get("PR_GATE_RELAY_URL", "")
        if not url:
            raise ValueError("PR_GATE_RELAY_URL is not set")
        cid, csecret, token = (
            os.environ.get(name, "")
            for name in (
                "PR_GATE_RELAY_CLIENT_ID",
                "PR_GATE_RELAY_CLIENT_SECRET",
                "PR_GATE_RELAY_TOKEN",
            )
        )
        if cid and csecret:
            headers = {"CF-Access-Client-Id": cid, "CF-Access-Client-Secret": csecret}
        elif token:
            headers = {"cf-access-token": token}
        else:
            raise ValueError(
                "set PR_GATE_RELAY_CLIENT_ID and PR_GATE_RELAY_CLIENT_SECRET, or PR_GATE_RELAY_TOKEN"
            )
        return cls(url, headers, repo, runtime, holder, secret or new_secret())

    def _send(self, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps({k: v for k, v in body.items() if v is not None}).encode()
        request = urllib.request.Request(
            self.endpoint, data=data, headers=self.headers, method="POST"
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as res:
                status, text = res.status, res.read().decode()
        except urllib.error.HTTPError as error:
            status, text = error.code, error.read().decode(errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise RelayDown(str(error)) from error
        if status >= 500:
            raise RelayDown(f"{status}: {text[:300]}")
        try:
            answer = json.loads(text)
        except ValueError:
            # Access answers a missing or expired credential with its login page, never JSON.
            raise RelayRefused(status, {"error": text[:300]}) from None
        if status != 200:
            raise RelayRefused(status, answer)
        return answer

    def claim(
        self,
        ref: str,
        title: str | None = None,
        branch: str | None = None,
        reopen: bool = False,
    ) -> dict[str, Any]:
        answer = self._send(
            {
                "op": "claim",
                "ref": ref,
                "holder": self.holder,
                "runtime": self.runtime,
                "secret": self.secret,
                "title": title,
                "branch": branch,
                "reopen": reopen or None,
            }
        )
        self.tokens[ref] = answer["token"]
        return answer

    def beat(self, ref: str) -> dict[str, Any]:
        return self._send(
            {"op": "beat", "ref": ref, "secret": self.secret, "token": self.tokens[ref]}
        )

    def checkpoint(
        self,
        ref: str,
        text: str,
        commit: str | None = None,
        branch: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self._send(
            {
                "op": "checkpoint",
                "ref": ref,
                "secret": self.secret,
                "token": self.tokens[ref],
                "text": text,
                "commit": commit,
                "branch": branch,
                "notes": notes,
            }
        )

    def release(
        self, ref: str, outcome: str, text: str | None = None
    ) -> dict[str, Any]:
        answer = self._send(
            {
                "op": "release",
                "ref": ref,
                "secret": self.secret,
                "token": self.tokens[ref],
                "outcome": outcome,
                "text": text,
            }
        )
        self.tokens.pop(ref, None)
        return answer

    def get(self, ref: str) -> dict[str, Any]:
        return self._send({"op": "get", "ref": ref})

    def list(self, state: str | None = None) -> dict[str, Any]:
        return self._send({"op": "list", "state": state})

    @contextmanager
    def keepalive(self, ref: str, every: float = 30.0) -> Iterator[threading.Event]:
        """Beats in a thread while the block runs. The yielded event is set if the claim is lost, so a loop can stop its work."""
        if every < 5:
            raise ValueError("every is at least 5 seconds")
        token = self.tokens[ref]
        stop, lost = threading.Event(), threading.Event()

        def run() -> None:
            while not stop.wait(every):
                try:
                    self._send(
                        {
                            "op": "beat",
                            "ref": ref,
                            "secret": self.secret,
                            "token": token,
                        }
                    )
                except RelayRefused:
                    lost.set()
                    return
                except RelayDown:
                    continue

        thread = threading.Thread(
            target=run, daemon=True, name=f"relay-keepalive-{ref}"
        )
        thread.start()
        try:
            yield lost
        finally:
            stop.set()
            thread.join(timeout=every)
