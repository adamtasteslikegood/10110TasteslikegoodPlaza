"""cloud_runner: the bridge's HTTP client for the Plaza cloud runner (stdlib only).

The runner is a Cloudflare Worker (cloud-runner/README.md, "Routes"). Every call
sends ``Authorization: Bearer <caller secret>``. Methods block: callers use
``asyncio.to_thread``. Modelled on ``bridge/relay_work.py``: redirects are never
followed (the bearer must not leave the configured origin) and the client names
itself in User-Agent, because Cloudflare answers urllib's default with a 403.

Two failures, told apart on purpose:

* ``RunnerDown``: no connection, a timeout, or a 5xx other than 502. Try again later.
* ``RunnerRefused``: any other answer that is not 2xx, a redirect included. A 502
  is the runner answering that GitHub or the clone failed, so it is a refusal.
"""

from __future__ import annotations

import http.client
import json
import os
import ssl
import stat
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from bridge.agent_bindings import DOMAIN_IDS

USER_AGENT = "plaza-bridge-cloud/1"
TIMEOUT_SECONDS = 30.0
TEXT_MAX = 300
SECRET_MIN = 32
DEFAULT_SECRET_FILE = Path.home() / ".config" / "plaza" / "cloud-runner-secret"
SECRET_FILE_VARIABLE = "CLOUD_RUNNER_SECRET_FILE"


_TRANSPORT = (
    urllib.error.URLError,
    http.client.HTTPException,
    TimeoutError,
    OSError,
)


class RunnerDown(Exception):
    """No connection, a timeout, or a 5xx other than 502."""


class RunnerRefused(Exception):
    """Any other answer that is not 2xx; ``text`` is the body, at most 300 characters."""

    def __init__(self, status: int, text: str):
        super().__init__(f"{status}: {text}")
        self.status = status
        self.text = text


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect means refusal. Never forward the bearer to another origin.
        return None


def _read_secret(path: Path) -> str:
    """Read the caller secret. Unlike relay_claims._secret, this never creates the file."""
    try:
        info = os.lstat(path)
    except OSError:
        raise ValueError(f"the cloud runner secret file {path} is missing") from None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{path} must be a regular file")
    if stat.S_IMODE(info.st_mode) & 0o077:
        os.chmod(path, 0o600)
    try:
        secret = path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        raise ValueError(f"{path} could not be read") from None
    if not secret.isascii():
        raise ValueError(f"{path} must hold an ASCII secret")
    if len(secret) < SECRET_MIN:
        raise ValueError(
            f"{path} must hold a secret of {SECRET_MIN} characters or more"
        )
    return secret


def _check_url(url: str) -> str:
    """An origin only: it is written into every run's log manifest, so it carries no secret."""
    try:
        parts = urlsplit(url)
        port = parts.port  # raises on a malformed port
    except ValueError:
        raise ValueError("CLOUD_RUNNER_URL is not a valid URL") from None
    scheme, host = parts.scheme.lower(), parts.hostname
    if not host or scheme not in ("https", "http"):
        raise ValueError("CLOUD_RUNNER_URL must be an https URL with a host")
    if scheme == "http" and host not in ("localhost", "127.0.0.1"):
        raise ValueError("CLOUD_RUNNER_URL must be https (http only for localhost)")
    if (
        parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or "@" in parts.netloc
        or port == 0
    ):
        raise ValueError(
            "CLOUD_RUNNER_URL must be a plain origin, such as https://runner.example"
        )
    return url.rstrip("/")


class CloudRunner:
    def __init__(
        self,
        url: str,
        secret: str,
        timeout: float = TIMEOUT_SECONDS,
        environ=None,
    ):
        environ = os.environ if environ is None else environ
        self.url = _check_url(url)
        if len(secret) < SECRET_MIN:
            raise ValueError(f"the secret must be at least {SECRET_MIN} characters")
        self._secret = secret
        self.timeout = timeout
        cafile = environ.get("SSL_CERT_FILE")
        context = (
            ssl.create_default_context(cafile=cafile)
            if cafile
            else ssl.create_default_context()
        )
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context), _NoRedirect()
        )

    def __repr__(self) -> str:
        return f"CloudRunner(url={self.url!r})"

    @classmethod
    def from_env(cls, config, environ=None) -> "CloudRunner | None":
        # Every run's log manifest carries the URL, so a set one is checked
        # even with no cloud department.
        url = config.cloud_runner_url.strip()
        if url:
            url = _check_url(url)
        if not config.cloud_domains:
            return None
        unknown = sorted(config.cloud_domains - DOMAIN_IDS)
        if unknown:
            raise ValueError(f"CLOUD_DOMAINS names unknown departments: {unknown}")
        environ = os.environ if environ is None else environ
        url = _check_url(url)
        named = environ.get(SECRET_FILE_VARIABLE)
        secret = _read_secret(Path(named) if named else DEFAULT_SECRET_FILE)
        return cls(url, secret, environ=environ)

    def _send(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        headers = {"authorization": f"Bearer {self._secret}", "user-agent": USER_AGENT}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["content-type"] = "application/json"
        request = urllib.request.Request(
            self.url + path, data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as res:
                status, text = res.status, res.read().decode(errors="replace")
        except urllib.error.HTTPError as error:
            status = error.code
            try:
                text = error.read().decode(errors="replace")
            except _TRANSPORT:
                # The status arrived; only its body was lost.
                text = ""
        except _TRANSPORT as error:
            raise RunnerDown(self._clean(str(error))) from None
        text = self._clean(text)
        if status >= 500 and status != 502:
            raise RunnerDown(f"{status}: {text[:TEXT_MAX]}")
        if not 200 <= status < 300:
            raise RunnerRefused(status, text[:TEXT_MAX])
        try:
            answer = json.loads(text)
        except ValueError:
            raise RunnerRefused(status, text[:TEXT_MAX]) from None
        if not isinstance(answer, dict):
            raise RunnerRefused(status, "the runner's answer was not an object")
        return answer

    def _clean(self, text: str) -> str:
        return text.replace(self._secret, "***")

    def redactions(self) -> tuple[str]:
        """The caller secret, for the recorder's redaction list only."""
        return (self._secret,)

    def clean(self, text: str) -> str:
        """``text`` with the caller secret replaced, for the bridge's own log lines."""
        return self._clean(text)

    @staticmethod
    def _path(name: str, tail: str = "") -> str:
        return f"/workspaces/{quote(name, safe='')}{tail}"

    def create(self, name: str, repo: str, branch: str) -> dict:
        return self._send("PUT", self._path(name), {"repo": repo, "branch": branch})

    def status(self, name: str) -> dict:
        return self._send("GET", self._path(name))

    def start_run(
        self, name: str, prompt: str, *, conversation: str, max_turns: int
    ) -> int:
        answer = self._send(
            "POST",
            self._path(name, "/runs"),
            {"prompt": prompt, "conversation": conversation, "maxTurns": max_turns},
        )
        run = answer.get("run")
        if not isinstance(run, int) or isinstance(run, bool):
            raise RunnerRefused(202, "the runner did not name the run")
        return run

    def events(self, name: str, after: int) -> tuple[list[dict], int]:
        answer = self._send("GET", self._path(name, f"/events?after={int(after)}"))
        events, following = answer.get("events"), answer.get("next")
        if (
            not isinstance(events, list)
            or not isinstance(following, int)
            or isinstance(following, bool)
        ):
            raise RunnerRefused(200, "the runner's events answer was malformed")
        return events, following

    def stop(self, name: str) -> dict:
        return self._send("POST", self._path(name, "/stop"))
