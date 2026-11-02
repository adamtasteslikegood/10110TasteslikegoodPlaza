"""Opt-in relay work claims for domain sessions; off unless RELAY_WORK_REPO is set.

Each domain is one claim, ref ``plaza:<domain_id>``, on the work board of the repo
named by RELAY_WORK_REPO (``owner/name``) at the relay pinned by PR_GATE_RELAY_URL.
The credential is pr-lifecycle's: PR_GATE_RELAY_CLIENT_ID and
PR_GATE_RELAY_CLIENT_SECRET (an Access service token) or PR_GATE_RELAY_TOKEN.

Start claims the domain, a background task beats while the generation lives, each
finished Run records a checkpoint (its status, the workspace branch and commit),
and a clean Stop releases the claim as paused. The relay coordinates who works a
domain across runtimes; SQLite stays the bridge's record of the session.

A relay that does not answer never stops local work: the session runs unclaimed.
A claim live under another holder, or a refused credential, refuses Start.
"""

import asyncio
import os
import socket
from collections.abc import Mapping
from pathlib import Path

from bridge.relay_work import RelayDown, RelayRefused, RelayWork, new_secret

REF_PREFIX = "plaza:"
DEFAULT_SECRET_FILE = Path.home() / ".config" / "plaza" / "relay-work-secret"


class ClaimRefused(Exception):
    """Start must not proceed: ``code`` is a domain protocol error code."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def _secret(path: Path) -> str:
    """One secret per machine, made once, so a restarted bridge renews its claims."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as file:
            file.write(new_secret())
    return path.read_text().strip()


def _headers(environ: Mapping[str, str]) -> dict[str, str]:
    cid = environ.get("PR_GATE_RELAY_CLIENT_ID", "")
    csecret = environ.get("PR_GATE_RELAY_CLIENT_SECRET", "")
    token = environ.get("PR_GATE_RELAY_TOKEN", "")
    if cid and csecret:
        return {"CF-Access-Client-Id": cid, "CF-Access-Client-Secret": csecret}
    if token:
        return {"cf-access-token": token}
    raise ValueError(
        "RELAY_WORK_REPO needs PR_GATE_RELAY_CLIENT_ID and "
        "PR_GATE_RELAY_CLIENT_SECRET, or PR_GATE_RELAY_TOKEN"
    )


class RelayClaims:
    """The bridge's relay settings; makes one DomainClaim per domain generation."""

    def __init__(self, work: RelayWork, *, every: float = 30.0):
        self.work, self.every = work, every

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None):
        """None unless RELAY_WORK_REPO is set; a half-made setting is a ValueError."""
        environ = os.environ if environ is None else environ
        repo = environ.get("RELAY_WORK_REPO", "").strip()
        if not repo:
            return None
        if repo.count("/") != 1 or not all(repo.split("/")):
            raise ValueError("RELAY_WORK_REPO must be owner/name")
        url = environ.get("PR_GATE_RELAY_URL", "").strip()
        if not url:
            raise ValueError("RELAY_WORK_REPO needs PR_GATE_RELAY_URL")
        every = float(environ.get("RELAY_WORK_BEAT_SECONDS") or 30)
        if not every >= 5:
            raise ValueError("RELAY_WORK_BEAT_SECONDS is at least 5")
        secret_file = environ.get("RELAY_WORK_SECRET_FILE")
        work = RelayWork(
            url,
            _headers(environ),
            repo,
            environ.get("RELAY_RUNTIME") or "bridge",
            environ.get("RELAY_WORK_HOLDER") or f"bridge@{socket.gethostname()}",
            _secret(Path(secret_file) if secret_file else DEFAULT_SECRET_FILE),
        )
        return cls(work, every=every)

    def for_domain(self, domain_id: str, recorder=None) -> "DomainClaim":
        return DomainClaim(self.work, REF_PREFIX + domain_id, self.every, recorder)


class DomainClaim:
    """One generation's hold on its domain's claim. Never raises after Start."""

    def __init__(self, work: RelayWork, ref: str, every: float, recorder=None):
        self.work, self.ref, self.every, self._recorder = work, ref, every, recorder
        self.held = False
        self.lost = False
        self.resume = None
        self._beats = None

    def _event(self, outcome: str, reason: str):
        if self._recorder is not None:
            try:
                self._recorder.event(
                    "work_claim", outcome=outcome, terminal_reason=reason
                )
            except Exception:
                pass

    async def claim(self, branch: str | None = None) -> dict | None:
        try:
            answer = await asyncio.to_thread(
                self.work.claim, self.ref, branch=branch, reopen=True
            )
        except RelayDown:
            self._event("failure", "relay_down")
            return None
        except RelayRefused as error:
            self._event("failure", f"refused_{error.status}")
            raise ClaimRefused(
                "work_claimed" if error.status == 423 else "relay_refused", str(error)
            ) from None
        except Exception:
            # An answer this client can't read is treated as no answer.
            self._event("failure", "relay_unreadable")
            return None
        self.held = True
        self.resume = answer.get("resume")
        self._event("success", "took_over" if answer.get("tookOver") else "claimed")
        self._beats = asyncio.create_task(self._beat())
        return answer

    async def _beat(self):
        while self.held:
            await asyncio.sleep(self.every)
            try:
                await asyncio.to_thread(self.work.beat, self.ref)
            except (RelayRefused, KeyError):
                # Lapsed, taken over or released meanwhile: stop beating for it.
                self._lose()
                return
            except Exception:
                continue

    def _lose(self):
        if self.held:
            self.held, self.lost = False, True
            self._event("failure", "lost")

    async def checkpoint(self, text: str, *, branch=None, commit=None):
        if not self.held:
            return
        try:
            await asyncio.to_thread(
                self.work.checkpoint, self.ref, text[:500], commit=commit, branch=branch
            )
        except (RelayRefused, KeyError):
            self._lose()
        except RelayDown:
            self._event("failure", "checkpoint_relay_down")
        except Exception:
            self._event("failure", "checkpoint_failed")

    async def close(self, *, release: bool):
        """Stop beating; a clean Stop releases as paused, anything else lets it lapse."""
        if self._beats is not None:
            self._beats.cancel()
            try:
                await self._beats
            except (asyncio.CancelledError, Exception):
                pass
            self._beats = None
        held, self.held = self.held, False
        if held and release:
            try:
                await asyncio.to_thread(
                    self.work.release, self.ref, "paused", "stopped"
                )
            except Exception:
                self._event("failure", "release_failed")
