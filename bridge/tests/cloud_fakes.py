"""An in-process stand-in for bridge.cloud_runner.CloudRunner, for later tasks' tests."""

from __future__ import annotations


class FakeRunner:
    """The five CloudRunner methods, recording calls; ``script`` sets the answers.

    ``script(method, *answers)``: each call to ``method`` consumes the next answer
    (the last one repeats). An answer that is an Exception is raised; any other is
    returned. With no script a method answers with a plain default.
    """

    def __init__(self):
        self.calls: list[tuple] = []
        self._scripts: dict[str, list] = {}
        self._runs = 0
        self.secret: str | None = None  # what ``clean`` replaces, as the client does

    def clean(self, text: str) -> str:
        return text.replace(self.secret, "***") if self.secret else text

    def script(self, method: str, *answers) -> None:
        self._scripts[method] = list(answers)

    def _answer(self, method: str, default):
        queue = self._scripts.get(method)
        if not queue:
            return default
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def create(self, name: str, repo: str, branch: str) -> dict:
        self.calls.append(("create", name, repo, branch))
        return self._answer("create", {"state": "idle", "branch": branch})

    def status(self, name: str) -> dict:
        self.calls.append(("status", name))
        return self._answer("status", {"state": "idle"})

    def start_run(
        self, name: str, prompt: str, *, conversation: str, max_turns: int
    ) -> int:
        self.calls.append(("start_run", name, prompt, conversation, max_turns))
        self._runs += 1
        return self._answer("start_run", self._runs)

    def events(self, name: str, after: int) -> tuple[list[dict], int]:
        self.calls.append(("events", name, after))
        return self._answer("events", ([], after))

    def stop(self, name: str) -> dict:
        self.calls.append(("stop", name))
        return self._answer("stop", {"state": "stopped"})
