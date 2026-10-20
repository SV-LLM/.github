"""S1 required-checks probe: records any wall-clock or network read by a check's Python processes.

Loaded through PYTHONPATH by sandbox/s1_required_checks_verifier.py only. Each
wall-clock read (time.time/time_ns/localtime/gmtime/ctime/asctime/strftime
without a supplied time, datetime.now/utcnow/today, date.today) and each
network attempt (socket connect/getaddrinfo/create_connection) is appended to
the file named by S1_PROBE_LOG with the first caller outside this probe. A
network attempt is also refused. Monotonic and performance counters are not
wall clocks and are not recorded, nor is a standard-library module's own
import-time stamp (logging's _startTime).
"""
import os as _os

_LOG = _os.environ.get("S1_PROBE_LOG")


def _caller():
    """The first frame outside this probe, as <stdlib>/..., <site>/... or a path relative to the check's cwd."""
    import sys as _sys
    frame = _sys._getframe(2)
    while frame is not None and frame.f_code.co_filename == __file__:
        frame = frame.f_back
    if frame is None:
        return "?"
    path = frame.f_code.co_filename
    cwd = _os.getcwd() + _os.sep
    stdlib = _os.path.dirname(_os.__file__) + _os.sep
    if path.startswith(stdlib):
        # A standard-library module stamping itself at import (logging's _startTime)
        # is not the check reading the clock; any other standard-library read is
        # recorded, without a line number, which varies across Python versions.
        if frame.f_code.co_name == "<module>":
            return None
        return "<stdlib>/" + path[len(stdlib):]
    for prefix, label in ((cwd, ""),):
        if path.startswith(prefix):
            path = label + path[len(prefix):]
            break
    else:
        marker = _os.sep + "deps" + _os.sep
        path = ("<dep>/" + path.split(marker, 1)[1]) if marker in path else "<other>/" + _os.path.basename(path)
    return path + ":" + str(frame.f_lineno)


def _record(kind, name):
    if not _LOG:
        return
    try:
        where = _caller()
    except Exception:  # noqa: BLE001 - the probe never breaks the check
        where = "?"
    if where is None:
        return
    try:
        with open(_LOG, "a", encoding="utf-8") as stream:
            stream.write(kind + " " + name + " @ " + where + "\n")
    except OSError:
        pass


if _LOG:
    import time as _time
    import datetime as _datetime
    import socket as _socket

    def _wrap_time(name, needs_arg=False):
        original = getattr(_time, name)

        def probe(*args, **kwargs):
            if not needs_arg or not args or args[-1] is None:
                _record("CLOCK", "time." + name)
            return original(*args, **kwargs)
        setattr(_time, name, probe)

    for _name in ("time", "time_ns"):
        _wrap_time(_name)
    for _name in ("localtime", "gmtime", "ctime", "asctime"):
        _wrap_time(_name, needs_arg=True)
    _strftime = _time.strftime

    def _probe_strftime(fmt, *args):
        if not args:
            _record("CLOCK", "time.strftime")
        return _strftime(fmt, *args)
    _time.strftime = _probe_strftime

    class _ProbeDatetime(_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            _record("CLOCK", "datetime.now")
            return super().now(tz)

        @classmethod
        def utcnow(cls):
            _record("CLOCK", "datetime.utcnow")
            return super().utcnow()

        @classmethod
        def today(cls):
            _record("CLOCK", "datetime.today")
            return super().today()

    class _ProbeDate(_datetime.date):
        @classmethod
        def today(cls):
            _record("CLOCK", "date.today")
            return super().today()

    _datetime.datetime = _ProbeDatetime
    _datetime.date = _ProbeDate

    def _refuse_network(name):
        def probe(*args, **kwargs):
            _record("NETWORK", "socket." + name)
            raise OSError("S1 required-checks probe: network refused (offline check)")
        return probe

    _socket.getaddrinfo = _refuse_network("getaddrinfo")
    _socket.create_connection = _refuse_network("create_connection")
    _socket.socket.connect = _refuse_network("connect")
    _socket.socket.connect_ex = _refuse_network("connect_ex")
