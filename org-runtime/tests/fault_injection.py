"""Raise OSError at the n-th durable write under a scratch root, in this process and its children.

B-P36q. Every durable write in this repository's ledgers and node state ends
in one primitive: `os.replace` (ledger_store.PosixLedgerStore.put) or
`os.link` (node_store.PosixStateStore.put_once). This module wraps both. A
call whose destination is under STEGVERSE_FAULT_ROOT is counted (the counter
is a file, so subprocesses share it); the call numbered STEGVERSE_FAULT_AT
fails:

  before  the write does not happen
  after   the write lands and then OSError is raised (a lost acknowledgement)

With STEGVERSE_FAULT_MATCH set, only writes whose destination path contains
it are counted (HEAD.json, frames.d, seen ...).

`directory()` returns a sitecustomize directory to put first on PYTHONPATH,
so a CLI subprocess (the emitter, the release CLI) is injected the
same way. With STEGVERSE_FAULT_AT unset nothing fails and the count is a
census of the writes a clean run makes. Test support only.
"""
import fcntl
import os
import tempfile
from pathlib import Path

_ORIGINAL = {}


def _count(counter):
    with open(counter, "a+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0)
        text = stream.read().strip()
        number = int(text or 0)
        stream.seek(0)
        stream.truncate()
        stream.write(str(number + 1))
        return number


def _wrap(name):
    original = _ORIGINAL.setdefault(name, getattr(os, name))

    def call(source, destination, *args, **kwargs):
        root = os.environ.get("STEGVERSE_FAULT_ROOT")
        counter = os.environ.get("STEGVERSE_FAULT_COUNTER")
        target = str(Path(destination).resolve())
        match = os.environ.get("STEGVERSE_FAULT_MATCH")
        if not root or not counter or not target.startswith(root) or (match and match not in target):
            return original(source, destination, *args, **kwargs)
        number = _count(counter)
        at = os.environ.get("STEGVERSE_FAULT_AT")
        if at is not None and number == int(at):
            if os.environ.get("STEGVERSE_FAULT_MODE", "before") == "before":
                raise OSError("injected fault before durable write " + str(number))
            original(source, destination, *args, **kwargs)
            raise OSError("injected fault after durable write " + str(number))
        return original(source, destination, *args, **kwargs)
    setattr(os, name, call)


def install():
    _wrap("replace")
    _wrap("link")


def uninstall():
    for name, original in _ORIGINAL.items():
        setattr(os, name, original)


def directory():
    """A directory holding a sitecustomize.py that installs this module."""
    path = Path(tempfile.mkdtemp(prefix="stegverse-fault-"))
    here = Path(__file__).resolve().parent
    (path / "sitecustomize.py").write_text(
        "import sys\n"
        "sys.path.insert(0, " + repr(str(here)) + ")\n"
        "import fault_injection\n"
        "fault_injection.install()\n")
    return path


def census(counter):
    try:
        return int(Path(counter).read_text().strip() or 0)
    except FileNotFoundError:
        return 0
