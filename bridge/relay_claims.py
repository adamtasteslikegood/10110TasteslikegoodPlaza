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
import copy
import hashlib
import math
import os
import re
import socket
import time
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from bridge.relay_work import RelayDown, RelayRefused, RelayWork, new_secret

REF_PREFIX = "plaza:"
MAX_BEAT_SECONDS = 60
# The relay cuts a step's text at 300 characters and a holder at 200 (work.ts
# TEXT_MAX, FIELD_MAX). The bridge sends no more than the relay keeps, and its
# holder setting leaves room for the ":<12 hex>" checkout digest.
TEXT_MAX = 300
HOLDER_MAX = 200 - 13
# A relay outage must neither grow the queue without bound nor stall Stop: at
# most this many checkpoints wait to be sent, and Stop waits this long for them.
QUEUE_MAX = 20
FLUSH_SECONDS = 15.0
# After the relay failed to answer, a Run waits this long before asking again,
# so an outage costs one client timeout, not one per Run.
RETRY_SECONDS = 30.0
# GitHub's own name rules, so the repo can't reshape the claim endpoint's path.
REPO = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}")
DEFAULT_SECRET_FILE = Path.home() / ".config" / "plaza" / "relay-work-secret"


class ClaimRefused(Exception):
    """Start must not proceed: ``code`` is a domain protocol error code."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def _secret(path: Path) -> str:
    """One secret per machine, made once, so a restarted bridge renews its claims.

    A new secret is written whole to a private temp file and linked into place,
    so a second bridge starting at the same moment never reads a partial file.
    An existing file must be a regular file; its mode is tightened to 0600.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".relay-work-secret.")
    try:
        with os.fdopen(fd, "w") as file:
            file.write(new_secret())
        try:
            os.link(temp, path)
        except FileExistsError:
            pass
    finally:
        os.unlink(temp)
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{path} must be a regular file")
    if stat.S_IMODE(info.st_mode) & 0o077:
        os.chmod(path, 0o600)
    secret = path.read_text().strip()
    if len(secret) < 32:
        raise ValueError(f"{path} must hold a secret of 32 characters or more")
    return secret


def _check_url(url: str) -> None:
    """An https origin with a host, so a bad pin fails at startup, not as 'relay down'.

    The credential travels in headers: never send it in cleartext. The client
    appends /v1/<repo>/work, and pr-lifecycle pins the same value as an origin,
    so a path, query, fragment or user-info has no place here.
    """
    try:
        parts = urlsplit(url)
        port = parts.port  # raises on a malformed port
    except ValueError:
        raise ValueError("PR_GATE_RELAY_URL is not a valid URL") from None
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ValueError("PR_GATE_RELAY_URL must be an https URL with a host")
    if (
        parts.path not in ("", "/")
        or parts.query
        or parts.fragment
        or "@" in parts.netloc
        or port == 0
    ):
        raise ValueError(
            "PR_GATE_RELAY_URL must be a plain https origin, such as https://relay.example"
        )


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
        name = repo.partition("/")[2]
        if REPO.fullmatch(repo) is None or name in (".", ".."):
            raise ValueError("RELAY_WORK_REPO must be a GitHub owner/name")
        url = environ.get("PR_GATE_RELAY_URL", "").strip()
        if not url:
            raise ValueError("RELAY_WORK_REPO needs PR_GATE_RELAY_URL")
        _check_url(url)
        every = float(environ.get("RELAY_WORK_BEAT_SECONDS") or 30)
        # Beats must land well inside the relay's 120 s lease, or it lapses.
        if not (math.isfinite(every) and 5 <= every <= MAX_BEAT_SECONDS):
            raise ValueError(
                f"RELAY_WORK_BEAT_SECONDS is between 5 and {MAX_BEAT_SECONDS}"
            )
        holder = environ.get("RELAY_WORK_HOLDER") or f"bridge@{socket.gethostname()}"
        # The relay counts UTF-16 units; printable ASCII keeps one unit per
        # character, so the checkout digest always survives its cut.
        if not (holder.isascii() and holder.isprintable()):
            raise ValueError("RELAY_WORK_HOLDER must be printable ASCII")
        if len(holder) > HOLDER_MAX:
            raise ValueError(f"RELAY_WORK_HOLDER is at most {HOLDER_MAX} characters")
        secret_file = environ.get("RELAY_WORK_SECRET_FILE")
        work = RelayWork(
            url,
            _headers(environ),
            repo,
            environ.get("RELAY_RUNTIME") or "bridge",
            holder,
            _secret(Path(secret_file) if secret_file else DEFAULT_SECRET_FILE),
        )
        return cls(work, every=every)

    def for_domain(self, domain_id: str, recorder=None) -> "DomainClaim":
        return DomainClaim(self.work, REF_PREFIX + domain_id, self.every, recorder)


class DomainClaim:
    """One generation's hold on its domain's claim.

    Only ``claim`` and ``ensure`` raise, and only ClaimRefused: at Start, and
    before a later Run when the claim is live under another holder or the relay
    refuses it. Callers of both must handle it. Beats, checkpoints, ``flush``
    and ``close`` never raise.
    """

    def __init__(self, work: RelayWork, ref: str, every: float, recorder=None):
        self.work, self.ref, self.every, self._recorder = work, ref, every, recorder
        self._settings = work  # the shared RelayWork; never changed here
        self.held = False
        self.lost = False
        self.resume = None
        self._beats = None
        self._branch = self._place = None
        self._asked = None  # when the relay last failed to answer a claim
        # Checkpoints go to the relay one at a time, in the order Runs finished.
        self._sending = None
        self._queued = 0

    def _event(self, outcome: str, reason: str):
        if self._recorder is not None:
            try:
                self._recorder.event(
                    "work_claim", outcome=outcome, terminal_reason=reason
                )
            except Exception:
                pass

    async def claim(
        self, branch: str | None = None, place: str | None = None
    ) -> dict | None:
        """Claim the domain; ``place`` (the project checkout) joins the holder.

        Same machine and same checkout is the same holder, so a restarted bridge
        renews at once; the workspace lease already keeps one bridge per checkout.
        Another checkout of the repo on this machine is another holder and waits.
        """
        self._branch, self._place = branch, place
        if place is not None:
            mark = hashlib.sha256(place.encode("utf-8", "surrogatepass")).hexdigest()
            # Always from the shared settings, so a repeated claim never stacks.
            work = copy.copy(self._settings)
            work.holder = f"{self._settings.holder}:{mark[:12]}"
            work.tokens = (
                dict(self.work.tokens) if self.work is not self._settings else {}
            )
            self.work = work
        try:
            answer = await asyncio.to_thread(
                self.work.claim, self.ref, branch=branch, reopen=True
            )
        except RelayDown:
            self._asked = time.monotonic()
            self._event("failure", "relay_down")
            return None
        except RelayRefused as error:
            self._asked = None
            self._event("failure", f"refused_{error.status}")
            raise ClaimRefused(
                "work_claimed" if error.status == 423 else "relay_refused", str(error)
            ) from None
        except Exception:
            # Only no answer (RelayDown) runs unclaimed. An answer this client
            # can't use may still have recorded a claim nothing would beat, so
            # Start is refused rather than risk two runtimes on one domain.
            self._event("failure", "relay_unreadable")
            raise ClaimRefused("relay_refused", "unreadable relay answer") from None
        if not isinstance(answer, dict) or type(answer.get("token")) is not int:
            self._event("failure", "relay_unreadable")
            raise ClaimRefused("relay_refused", "relay answer without a claim token")
        self._asked = None
        self.held, self.lost = True, False
        self.resume = answer.get("resume")
        self._event("success", "took_over" if answer.get("tookOver") else "claimed")
        if self._beats is not None:
            self._beats.cancel()  # a beat task left from before a lost claim
        self._beats = asyncio.create_task(self._beat())
        return answer

    @property
    def status(self) -> str:
        """``held``, ``lost`` (the relay said so) or ``unclaimed`` (never answered)."""
        return "held" if self.held else "lost" if self.lost else "unclaimed"

    async def ensure(self) -> None:
        """Before a Run: a claim that is not held is claimed again.

        A lapsed claim nobody took, or a relay that was down at Start, is simply
        claimed. A claim now live under another holder raises ClaimRefused, as at
        Start. A relay that still does not answer leaves the Run unclaimed, and
        is asked again at most every RETRY_SECONDS.
        """
        if self.held:
            return
        if self._asked is not None and time.monotonic() - self._asked < RETRY_SECONDS:
            return
        await self.claim(branch=self._branch, place=self._place)

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

    def reserve_checkpoint(self):
        """Hold a place in the send order now; fill it later with ``fill(...)``.

        A Run reserves while it still holds the session and fills after its
        terminal's delivery attempt, so checkpoints stay in Run order and never
        reach the relay before the client was sent the result. ``fill()`` with no
        text gives the place up. Returns at once; never raises.
        """
        if not self.held:
            return lambda *args, **kwargs: None
        if self._queued >= QUEUE_MAX:
            # The relay is not keeping up; this Run's step is dropped, not queued.
            self._event("failure", "checkpoint_dropped")
            return lambda *args, **kwargs: None
        self._queued += 1
        slot = asyncio.get_running_loop().create_future()
        previous = self._sending

        async def send():
            try:
                if previous is not None:
                    await asyncio.gather(previous, return_exceptions=True)
                text, branch, commit = await slot
                if text is not None:
                    await self.checkpoint(text, branch=branch, commit=commit)
            finally:
                self._queued -= 1

        def fill(text=None, *, branch=None, commit=None):
            if not slot.done():
                slot.set_result((text, branch, commit))

        self._sending = asyncio.create_task(send())
        return fill

    def queue_checkpoint(self, text: str, *, branch=None, commit=None):
        """Queue a checkpoint behind any still being sent; returns at once."""
        self.reserve_checkpoint()(text, branch=branch, commit=commit)

    async def flush(self, timeout: float | None = None) -> bool:
        """Wait until every queued checkpoint is sent or given up, or ``timeout``.

        True when the queue drained; False when a relay call may still be in flight.
        """
        if self._sending is None:
            return True
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.gather(self._sending, return_exceptions=True)),
                timeout,
            )
        except (asyncio.TimeoutError, TimeoutError):  # distinct before 3.11
            self._event("failure", "flush_timeout")
            return False
        return True

    async def checkpoint(self, text: str, *, branch=None, commit=None):
        if not self.held:
            return
        try:
            await asyncio.to_thread(
                self.work.checkpoint,
                self.ref,
                text[:TEXT_MAX],
                commit=commit,
                branch=branch,
            )
        except (RelayRefused, KeyError):
            self._lose()
        except RelayDown:
            self._event("failure", "checkpoint_relay_down")
        except Exception:
            self._event("failure", "checkpoint_failed")

    async def close(self, *, release: bool):
        """Stop beating; a clean Stop releases as paused, anything else lets it lapse."""
        # Queued checkpoints land before the release, so the relay's last step
        # is the last Run, then the pause. A relay outage can't hold Stop longer
        # than FLUSH_SECONDS; checkpoints still waiting then are dropped.
        drained = await self.flush(FLUSH_SECONDS)
        if self._beats is not None:
            self._beats.cancel()
            try:
                await self._beats
            except (asyncio.CancelledError, Exception):
                pass
            self._beats = None
        held, self.held = self.held, False
        if not (held and release):
            return
        if not drained:
            # A checkpoint may still be in flight; a release now could race it.
            # The claim lapses on its own after the relay's lease instead.
            self._event("failure", "release_skipped")
        else:
            try:
                await asyncio.to_thread(
                    self.work.release, self.ref, "paused", "stopped"
                )
            except Exception:
                self._event("failure", "release_failed")
