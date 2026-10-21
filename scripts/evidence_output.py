"""Reserve a fresh report destination before work; publish once without clobbering."""

import json
import os
from pathlib import Path
import tempfile


class FreshEvidenceOutput:
    """A sibling reservation coordinates runners; an atomic link claims the report.

    The destination stays absent until the complete report is ready. A concurrent
    creator is never overwritten, even if it doesn't honor the reservation. An
    interrupted process may leave its reservation/staging file for inspection.
    """

    def __init__(self, path):
        self.path = Path(path).absolute()
        self.reservation = self.path.with_name("." + self.path.name + ".reserve")
        self._lock = self._temporary = None
        self._published = False

    def __enter__(self):
        if os.path.lexists(self.path):
            raise FileExistsError("output already exists; choose a fresh evidence path")
        self._lock = self.reservation.open("xb")
        try:
            # Actual file creation checks the existing parent's writability before
            # any runtime, child or case entry, without permission-bit guesses.
            self._temporary = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="." + self.path.name + ".",
                suffix=".tmp",
                dir=self.path.parent,
                delete=False,
            )
            if os.path.lexists(self.path):
                raise FileExistsError("output appeared during reservation")
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def checkpoint_json(self, value):
        if self._temporary is None or self._published:
            raise ValueError("report output must be reserved and published only once")
        self._temporary.seek(0)
        json.dump(value, self._temporary, indent=2, allow_nan=False)
        self._temporary.write("\n")
        self._temporary.truncate()
        self._temporary.flush()
        os.fsync(self._temporary.fileno())

    def publish_json(self, value):
        self.checkpoint_json(value)
        # Same-parent hard link is atomic and fails if any destination exists.
        os.link(self._temporary.name, self.path)
        self._published = True

    def __exit__(self, *args):
        if self._temporary is not None:
            # Preserve a fully written report if publication failed (for
            # example, another writer created the destination meanwhile).
            retain_report = not self._published and self._temporary.tell() > 0
            self._temporary.close()
            if not retain_report:
                Path(self._temporary.name).unlink()
            self._temporary = None
        if self._lock is not None:
            # Remove only this process's reservation, never a replaced record.
            own = os.fstat(self._lock.fileno())
            try:
                current = self.reservation.lstat()
                if (own.st_dev, own.st_ino) == (current.st_dev, current.st_ino):
                    self.reservation.unlink()
            except FileNotFoundError:
                pass
            self._lock.close()
            self._lock = None
