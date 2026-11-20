"""The cloud runner client: requests, failure kinds and settings. No test opens a network connection."""

import inspect
import http.client
import io
import json
import os
import urllib.error
import urllib.request
import urllib.response
from dataclasses import replace
from email.message import Message

import pytest

from bridge import cloud_log
from bridge.cloud_runner import CloudRunner, RunnerDown, RunnerRefused, _NoRedirect
from bridge.config import default_config
from bridge.tests.cloud_fakes import FakeRunner

SECRET = "s3cr3t-" + "x" * 40
URL = "https://runner.example"


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body if isinstance(body, bytes) else body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Stands in for the client's opener: records requests, answers from ``answer``."""

    def __init__(self, answer):
        self.answer = answer
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        result = self.answer
        if isinstance(result, Exception):
            raise result
        status, body = result
        if status >= 400:
            raise urllib.error.HTTPError(
                request.full_url, status, "x", Message(), io.BytesIO(body.encode())
            )
        return FakeResponse(status, body)


def client(answer, url=URL):
    runner = CloudRunner(url, SECRET)
    runner.opener = FakeOpener(answer)
    return runner


def settings(**values):
    return replace(default_config(), **values)


def secret_file(tmp_path, text=SECRET, mode=0o600):
    path = tmp_path / "secret"
    path.write_text(text)
    path.chmod(mode)
    return path


def test_every_request_carries_the_bearer_and_its_own_user_agent():
    runner = client((200, "{}"))
    runner.create("w", "o/r", "b")
    runner.status("w")
    runner.stop("w")
    assert len(runner.opener.requests) == 3
    for request in runner.opener.requests:
        assert request.get_header("Authorization") == f"Bearer {SECRET}"
        assert request.get_header("User-agent") == "plaza-bridge-cloud/1"
    assert set(runner.opener.timeouts) == {30.0}
    put, get, post = runner.opener.requests
    assert (put.get_method(), put.full_url) == ("PUT", f"{URL}/workspaces/w")
    assert json.loads(put.data) == {"repo": "o/r", "branch": "b"}
    assert (get.get_method(), get.data) == ("GET", None)
    assert (post.get_method(), post.full_url) == ("POST", f"{URL}/workspaces/w/stop")


def test_a_workspace_name_cannot_reshape_the_path():
    runner = client((200, "{}"))
    runner.status("a/../b?x=1")
    assert runner.opener.requests[0].full_url == f"{URL}/workspaces/a%2F..%2Fb%3Fx%3D1"


def test_a_redirect_is_refused_not_followed():
    assert (
        _NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil")
        is None
    )

    class Redirecting(urllib.request.HTTPHandler):
        opened = []

        def http_open(self, request):
            Redirecting.opened.append(request.full_url)
            headers = Message()
            headers["Location"] = "http://127.0.0.1:1/elsewhere"
            response = urllib.response.addinfourl(
                io.BytesIO(b""), headers, request.full_url, 302
            )
            response.msg = "Found"
            return response

    runner = CloudRunner("http://localhost:8787", SECRET)
    runner.opener = urllib.request.build_opener(Redirecting, _NoRedirect())
    with pytest.raises(RunnerRefused) as caught:
        runner.status("w")
    assert caught.value.status == 302
    assert Redirecting.opened == ["http://localhost:8787/workspaces/w"]


def test_no_answer_and_a_500_are_down():
    for answer in (
        urllib.error.URLError("refused"),
        TimeoutError("slow"),
        (500, "boom"),
        (503, "later"),
    ):
        with pytest.raises(RunnerDown):
            client(answer).status("w")


def test_a_502_is_refused_with_its_status():
    with pytest.raises(RunnerRefused) as caught:
        client((502, "The branch could not be fetched")).start_run(
            "w", "p", conversation="c", max_turns=3
        )
    assert caught.value.status == 502
    assert not isinstance(caught.value, RunnerDown)


def test_a_409_keeps_its_text():
    with pytest.raises(RunnerRefused) as caught:
        client((409, "A run is already active")).start_run(
            "w", "p", conversation="c", max_turns=3
        )
    assert (caught.value.status, caught.value.text) == (409, "A run is already active")


def test_other_non_2xx_answers_are_refused_and_the_text_is_cut():
    for status in (401, 404, 412, 413, 422):
        with pytest.raises(RunnerRefused) as caught:
            client((status, "y" * 1000)).status("w")
        assert caught.value.status == status
        assert len(caught.value.text) == 300


def test_a_2xx_that_is_not_json_is_refused():
    with pytest.raises(RunnerRefused) as caught:
        client((200, "<html>login</html>")).status("w")
    assert caught.value.status == 200


def test_start_run_returns_the_run_number():
    runner = client((202, '{"run": 4}'))
    assert runner.start_run("w", "do it", conversation="abc-1", max_turns=7) == 4
    body = json.loads(runner.opener.requests[0].data)
    assert body == {"prompt": "do it", "conversation": "abc-1", "maxTurns": 7}
    assert runner.opener.requests[0].full_url == f"{URL}/workspaces/w/runs"
    with pytest.raises(RunnerRefused):
        client((202, '{"run": "4"}')).start_run("w", "p", conversation="c", max_turns=1)


def test_events_returns_the_list_and_next():
    event = {
        "seq": 12,
        "run": 1,
        "generation": 1,
        "at": "t",
        "type": "x",
        "payload": {},
    }
    runner = client((200, json.dumps({"events": [event], "next": 12})))
    assert runner.events("w", 9) == ([event], 12)
    assert runner.opener.requests[0].full_url == f"{URL}/workspaces/w/events?after=9"
    with pytest.raises(RunnerRefused):
        client((200, '{"events": 1}')).events("w", 0)


def test_from_env_is_off_without_cloud_domains(tmp_path):
    assert CloudRunner.from_env(default_config(), environ={}) is None


def good(tmp_path, **extra):
    config = settings(cloud_domains=frozenset({"design"}), cloud_runner_url=URL)
    environ = {"CLOUD_RUNNER_SECRET_FILE": str(secret_file(tmp_path)), **extra}
    return config, environ


def test_from_env_builds_a_client_and_tightens_the_file_mode(tmp_path):
    config, environ = good(tmp_path)
    path = secret_file(tmp_path, mode=0o644)
    environ["CLOUD_RUNNER_SECRET_FILE"] = str(path)
    runner = CloudRunner.from_env(config, environ)
    assert isinstance(runner, CloudRunner) and runner.url == URL
    assert os.stat(path).st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://runner.example",
        "ftp://runner.example",
        "https://user:pass@runner.example",
        "https://runner.example/v1",
        "https://runner.example/?a=1",
        "https://runner.example/#frag",
        "https://runner.example:0",
        "https://",
    ],
)
def test_from_env_refuses_a_url_that_is_not_an_origin(tmp_path, bad_url):
    config, environ = good(tmp_path)
    with pytest.raises(ValueError):
        CloudRunner.from_env(replace(config, cloud_runner_url=bad_url), environ)


def test_from_env_allows_plain_http_only_for_loopback_names(tmp_path):
    config, environ = good(tmp_path)
    for url in (
        "http://localhost:8787",
        "http://127.0.0.1:8787/",
        "https://runner.example/",
    ):
        assert CloudRunner.from_env(replace(config, cloud_runner_url=url), environ)
    with pytest.raises(ValueError):
        CloudRunner.from_env(
            replace(config, cloud_runner_url="http://[::1]:8787"), environ
        )


def test_from_env_refuses_a_half_made_setting(tmp_path):
    config, environ = good(tmp_path)
    with pytest.raises(ValueError):  # an unknown department id
        CloudRunner.from_env(
            replace(config, cloud_domains=frozenset({"nope"})), environ
        )
    short = secret_file(tmp_path, "x" * 31)
    with pytest.raises(ValueError):  # a short secret
        CloudRunner.from_env(config, {"CLOUD_RUNNER_SECRET_FILE": str(short)})
    link = tmp_path / "link"
    link.symlink_to(secret_file(tmp_path))
    with pytest.raises(ValueError):  # a symlink
        CloudRunner.from_env(config, {"CLOUD_RUNNER_SECRET_FILE": str(link)})
    with pytest.raises(ValueError):  # a directory
        CloudRunner.from_env(config, {"CLOUD_RUNNER_SECRET_FILE": str(tmp_path)})
    missing = tmp_path / "absent"
    with pytest.raises(ValueError):  # missing: never created
        CloudRunner.from_env(config, {"CLOUD_RUNNER_SECRET_FILE": str(missing)})
    assert not missing.exists()


def test_from_env_reads_the_default_file_when_no_variable_is_set(tmp_path, monkeypatch):
    monkeypatch.setattr("bridge.cloud_runner.DEFAULT_SECRET_FILE", tmp_path / "nope")
    config, _ = good(tmp_path)
    with pytest.raises(ValueError):
        CloudRunner.from_env(config, {})


def test_the_secret_is_in_no_repr_and_no_error_text(tmp_path):
    config, environ = good(tmp_path)
    runner = CloudRunner.from_env(config, environ)
    assert SECRET not in repr(runner) and SECRET not in str(runner)
    echoing = f"you sent Bearer {SECRET}"
    for answer in (
        urllib.error.URLError(echoing),
        (500, echoing),
        (409, echoing),
        (200, echoing),
    ):
        runner.opener = FakeOpener(answer)
        with pytest.raises((RunnerDown, RunnerRefused)) as caught:
            runner.status("w")
        assert SECRET not in str(caught.value)
        assert SECRET not in getattr(caught.value, "text", "")
        # What the owner logs goes through the client's own scrub as well.
        assert SECRET not in cloud_log.remote(caught.value, runner.clean)
    assert runner.clean(echoing) == "you sent Bearer ***"
    short = secret_file(tmp_path, "x" * 5)
    with pytest.raises(ValueError):
        CloudRunner.from_env(config, {"CLOUD_RUNNER_SECRET_FILE": str(short)})


def test_the_fake_has_the_same_methods_and_signatures():
    for name in ("create", "status", "start_run", "events", "stop", "clean"):
        assert inspect.signature(getattr(FakeRunner, name)) == inspect.signature(
            getattr(CloudRunner, name)
        )


def test_the_fake_records_calls_and_plays_a_script():
    fake = FakeRunner()
    fake.script("start_run", RunnerRefused(409, "A run is already active"), 9)
    fake.script("events", ([{"seq": 1}], 1))
    with pytest.raises(RunnerRefused):
        fake.start_run("w", "p", conversation="c", max_turns=2)
    assert fake.start_run("w", "p", conversation="c", max_turns=2) == 9
    assert fake.events("w", 0) == ([{"seq": 1}], 1)
    assert fake.create("w", "o/r", "b")["state"] == "idle"
    assert fake.calls[0] == ("start_run", "w", "p", "c", 2)
    assert fake.calls[-1] == ("create", "w", "o/r", "b")


class BrokenBody:
    def __init__(self, status, error):
        self.status, self._error = status, error

    def read(self):
        raise self._error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class BrokenOpener:
    def __init__(self, response=None, http_error=None):
        self.response, self.http_error = response, http_error

    def open(self, request, timeout=None):
        if self.http_error is not None:
            raise self.http_error
        return self.response


def broken_error(status, error):
    http_error = urllib.error.HTTPError(URL, status, "x", Message(), io.BytesIO(b""))
    http_error.read = lambda *a: (_ for _ in ()).throw(error)
    return BrokenOpener(http_error=http_error)


def test_a_body_that_drops_mid_read_is_down():
    runner = CloudRunner(URL, SECRET)
    runner.opener = BrokenOpener(BrokenBody(200, http.client.IncompleteRead(b"x")))
    with pytest.raises(RunnerDown):
        runner.status("w")


def test_an_error_body_that_cannot_be_read_keeps_its_status():
    runner = CloudRunner(URL, SECRET)
    runner.opener = broken_error(409, TimeoutError("slow"))
    with pytest.raises(RunnerRefused) as caught:
        runner.status("w")
    assert (caught.value.status, caught.value.text) == (409, "")
    runner.opener = broken_error(502, OSError("reset"))
    with pytest.raises(RunnerRefused) as caught:
        runner.status("w")
    assert caught.value.status == 502
    runner.opener = broken_error(503, OSError("reset"))
    with pytest.raises(RunnerDown):
        runner.status("w")


@pytest.mark.parametrize("body", ["[]", "null"])
def test_a_2xx_that_is_not_an_object_is_refused(body):
    calls = (
        lambda r: r.status("w"),
        lambda r: r.create("w", "o/r", "b"),
        lambda r: r.stop("w"),
        lambda r: r.events("w", 0),
        lambda r: r.start_run("w", "p", conversation="c", max_turns=1),
    )
    for call in calls:
        with pytest.raises(RunnerRefused):
            call(client((200, body)))


def test_a_next_of_true_is_refused():
    with pytest.raises(RunnerRefused):
        client((200, '{"events": [], "next": true}')).events("w", 0)


def test_ssl_cert_file_comes_from_the_given_environ(tmp_path):
    bad = tmp_path / "missing.pem"
    with pytest.raises((OSError, ValueError)):
        CloudRunner(URL, SECRET, environ={"SSL_CERT_FILE": str(bad)})


@pytest.mark.parametrize("bad_url", ["ftp://runner.example", "https://a@b.example"])
def test_a_bad_url_is_refused_even_with_no_cloud_department(tmp_path, bad_url):
    config = settings(cloud_domains=frozenset(), cloud_runner_url=bad_url)
    with pytest.raises(ValueError, match="CLOUD_RUNNER_URL"):
        CloudRunner.from_env(config, {})


@pytest.mark.parametrize("url", ["", "   "])
def test_no_url_and_no_cloud_department_is_no_client(url):
    config = settings(cloud_domains=frozenset(), cloud_runner_url=url)
    assert CloudRunner.from_env(config, {}) is None


def test_the_url_is_stripped(tmp_path):
    config, environ = good(tmp_path)
    config = replace(config, cloud_runner_url=f"  {URL}/ \n")
    assert CloudRunner.from_env(config, environ).url == URL


def test_a_secret_that_is_not_ascii_is_refused_without_its_content(tmp_path):
    config, environ = good(tmp_path)
    text = "s3cr3t-" + "é" * 40
    environ["CLOUD_RUNNER_SECRET_FILE"] = str(secret_file(tmp_path, text=text))
    with pytest.raises(ValueError, match="ASCII") as raised:
        CloudRunner.from_env(config, environ)
    assert "s3cr3t" not in str(raised.value) and "é" not in str(raised.value)


def test_the_client_names_its_secret_for_redaction_only(tmp_path):
    config, environ = good(tmp_path)
    runner = CloudRunner.from_env(config, environ)
    assert runner.redactions() == (SECRET,)
    assert SECRET not in repr(runner)
