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
import re
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
        if info.st_nlink > 1:
            raise Refused("a hard link")
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


def is_dir_under(root: Path, rel: str) -> bool:
    """True when `root/rel` opens as a directory without following any link."""
    parts = [] if rel in ("", ".") else components(rel)
    fds: list[int] = []
    try:
        fds.append(os.open(root, _DIR_FLAGS))
        for part in parts:
            fds.append(os.open(part, _DIR_FLAGS, dir_fd=fds[-1]))
        return True
    except (OSError, Refused):
        return False
    finally:
        for opened in reversed(fds):
            os.close(opened)


#: Bounds of one tree walk, besides the file and byte caps.
MAX_DEPTH = 12
MAX_DIRS = 200
MAX_SKIPPED_LISTED = 200
#: A bundle name may not hold these (they mean something else on other systems
#: or could forge what a path looks like).
_BAD_NAME = re.compile(r"[\\:\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]")


def read_tree(root: Path, rel: str, *, max_files: int, max_bytes: int) -> tuple[dict[str, bytes], list[str]]:
    """Every regular file under `root/rel`, walked through directory fds (each
    opened with O_NOFOLLOW relative to its parent) and read from its own fd.
    Links, special files and hidden entries are skipped and named in the second
    value. Refused as soon as the files or bytes exceed the caps."""
    parts = [] if rel in ("", ".") else components(rel)
    files: dict[str, bytes] = {}
    skipped: list[str] = []
    total = 0
    dirs = 0
    fds: list[int] = []

    def skip(path: str) -> None:
        if len(skipped) < MAX_SKIPPED_LISTED:
            skipped.append(path)

    try:
        try:
            fds.append(os.open(root, _DIR_FLAGS))
            for part in parts:
                fds.append(os.open(part, _DIR_FLAGS, dir_fd=fds[-1]))
        except OSError as exc:
            raise Refused("not a plain directory") from exc

        def walk(dir_fd: int, prefix: str, depth: int) -> None:
            nonlocal total, dirs
            if depth > MAX_DEPTH:
                raise Refused("too deep")
            for entry in sorted(os.scandir(dir_fd), key=lambda e: e.name):
                name = entry.name
                path = f"{prefix}{name}"
                if name.startswith(".") or _BAD_NAME.search(name):
                    skip(path)
                    continue
                try:
                    info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                except OSError:
                    skip(path)
                    continue
                if stat.S_ISDIR(info.st_mode):
                    dirs += 1
                    if dirs > MAX_DIRS:
                        raise Refused("too many directories")
                    try:
                        sub = os.open(name, _DIR_FLAGS, dir_fd=dir_fd)
                    except OSError:
                        skip(path)
                        continue
                    try:
                        walk(sub, f"{path}/", depth + 1)
                    finally:
                        os.close(sub)
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                    skip(path)  # links, FIFOs, devices, hard links
                    continue
                if len(files) >= max_files:
                    raise Refused("too many files")
                try:
                    fd = os.open(name, _FILE_FLAGS, dir_fd=dir_fd)
                except OSError:
                    skip(path)
                    continue
                try:
                    opened = os.fstat(fd)
                    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        skip(path)
                        continue
                    left = max_bytes - total
                    chunks: list[bytes] = []
                    budget = left + 1
                    while budget > 0:
                        chunk = os.read(fd, min(budget, 1 << 20))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        budget -= len(chunk)
                    data = b"".join(chunks)
                    if len(data) > left:
                        raise Refused("over the size cap")
                finally:
                    os.close(fd)
                total += len(data)
                files[path] = data

        walk(fds[-1], "", 0)
        return files, skipped
    finally:
        for opened in reversed(fds):
            os.close(opened)
