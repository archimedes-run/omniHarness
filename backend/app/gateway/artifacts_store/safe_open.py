"""Read a file under a chat's outputs without following any link (Spec 012 FR-037, FR-028).

A model's sandbox writes those directories, so anything in them can change
between a check and an open. Nothing here checks a path and then reopens it:

* the outputs directory is opened once with O_NOFOLLOW | O_DIRECTORY;
* each further component is opened RELATIVE to the directory fd above it
  (`dir_fd=`), with O_NOFOLLOW, so a symlink anywhere (a swapped file or a
  swapped parent directory) fails the open instead of being followed;
* the file itself is opened with O_NOFOLLOW | O_NONBLOCK (a FIFO cannot block
  the importer) and checked with `fstat` on THAT fd: a regular file, the same
  (st_dev, st_ino) as the listing saw when given, at most `cap` bytes;
* it is read from that fd only, at most cap + 1 bytes, so a file that grows
  past the cap after the check is refused, never truncated.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path

#: Test hook: called with (root, rel) after the listing and before the open,
#: to change the filesystem in the window a race would use.
BEFORE_OPEN: Callable[[Path, str], None] | None = None

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class Refused(Exception):
    """Not a plain regular file inside the root, or over the cap."""


def components(rel: str) -> list[str]:
    parts = rel.split("/")
    if not rel or any(p in ("", ".", "..") or "\x00" in p for p in parts):
        raise Refused("not a plain relative path")
    return parts


def read_under(root: Path, rel: str, cap: int, *, expect: os.stat_result | None = None) -> bytes:
    """The bytes of `root/rel`, opened without following links; Refused otherwise."""
    parts = components(rel)
    if BEFORE_OPEN is not None:
        BEFORE_OPEN(root, rel)
    fds: list[int] = []
    try:
        try:
            fds.append(os.open(root, _DIR_FLAGS))
            for part in parts[:-1]:
                fds.append(os.open(part, _DIR_FLAGS, dir_fd=fds[-1]))
            fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=fds[-1])
        except OSError as exc:  # ELOOP (a link), ENOTDIR, ENOENT, ...
            raise Refused("could not be opened as a plain file") from exc
        fds.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise Refused("not a regular file")
        if expect is not None and (info.st_dev, info.st_ino) != (expect.st_dev, expect.st_ino):
            raise Refused("changed since it was listed")
        if info.st_size > cap:
            raise Refused("over the cap")
        chunks: list[bytes] = []
        left = cap + 1
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
        data = b"".join(chunks)
        if len(data) > cap:
            raise Refused("grew past the cap")
        return data
    finally:
        for opened in reversed(fds):
            os.close(opened)
