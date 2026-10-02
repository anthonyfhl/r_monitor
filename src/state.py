"""Atomic state writes and OS locks; corrupt state must never look empty."""
import json
import os
import errno
import logging
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)
RECOVERY_EVENTS = []


class LockBusyError(RuntimeError):
    """Another process holds the lock; never confuse file permissions with this."""


def recover_backup(path: Path, validator):
    """Keep the broken original, validate a real backup, then atomically restore.

    Refusal/cooldown state is never rolled back: that could shorten a pause.
    """
    if path.name.startswith("http_guard"):
        raise RuntimeError("Refusal state damaged; preserved original and blocked calls, cannot roll back a cooldown")
    backup = path.with_name(path.name + ".bak")
    if not backup.exists():
        raise RuntimeError(f"Repair attempted for {path.name}: no verified backup available; original preserved")
    value = validator(backup)
    quarantine = path.parent / "quarantine"
    quarantine.mkdir(exist_ok=True)
    saved = quarantine / f"{path.name}.{time.time_ns()}.broken"
    shutil.copy2(path, saved)
    temp = path.with_name(path.name + f".{os.getpid()}.repair.tmp")
    shutil.copy2(backup, temp)
    os.replace(temp, path)
    outcome = f"{path.name} 損壞；已保留原檔並從驗證過的備份復原。"
    logger.warning(outcome)
    RECOVERY_EVENTS.append(outcome)
    return value


def read_json(path: Path, default=None):
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeError):
        return recover_backup(path, lambda candidate: json.loads(candidate.read_text(encoding="utf-8-sig")))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    if path.exists():
        # A corrupt previous value cannot become the backup or be overwritten.
        read_json(path)
        backup_temp = path.with_name(path.name + f".{os.getpid()}.bak.tmp")
        shutil.copy2(path, backup_temp)
        os.replace(backup_temp, path.with_name(path.name + ".bak"))
    os.replace(temp, path)


@contextmanager
def file_lock(path: Path):
    """Nonblocking OS lock. A crashed process releases it without stale PID files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    raise LockBusyError(f"Another process owns {path.name}") from exc
                raise
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LockBusyError(f"Another process owns {path.name}") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
