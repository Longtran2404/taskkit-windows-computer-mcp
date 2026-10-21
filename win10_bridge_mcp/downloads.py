"""Bounded metadata-only download observations; never fetch URLs or open files."""
from __future__ import annotations

import os
from pathlib import Path
import threading
import time
import uuid

PARTIAL = ('.crdownload', '.tmp', '.part', '.partial', '.download')
NOTICE = ('File observation is not browser/source attribution. Verify the browser UI and '
          'expected filename. Never repeat an uncertain download click; inspect Save As, '
          'permission or browser download prompts explicitly.')


def directory(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('download_dir must be an existing absolute local directory')
    if not path.is_dir():
        raise ValueError('download_dir must exist; use the browser configured destination')
    resolved = path.resolve()
    if str(resolved).startswith(('\\\\', '//')):
        raise ValueError('Network download directories are not supported')
    if os.name == 'nt':
        import ctypes
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(resolved.anchor))
        if drive_type not in {2, 3, 6}:  # removable, fixed, RAM disk
            raise ValueError('download_dir must be on a local writable drive')
    return resolved


def snapshot(path: Path) -> dict:
    result = {}
    with os.scandir(path) as entries:
        for count, entry in enumerate(entries):
            if count >= 5000:
                raise ValueError('Download directory too large; choose a dedicated folder')
            try:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    continue
                stat = entry.stat(follow_symlinks=False)
                result[entry.name] = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
            except FileNotFoundError:
                continue  # Chromium can rename its temporary file during enumeration.
    return result


class DownloadRegistry:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.jobs = {}

    def prepare(self, raw: str, expected: str = '') -> str:
        if expected and (len(expected) > 255 or any(c in expected for c in '/\\:*?"<>|')
                         or expected in {'.', '..'}):
            raise ValueError('expected_filename must be a plain filename, without wildcards')
        path = directory(raw)
        baseline = snapshot(path)
        if expected and expected.casefold() in {n.casefold() for n in baseline}:
            raise ValueError('Expected filename already exists; choose a new name explicitly')
        with self.lock:
            now = self.clock()
            self.jobs = {k: v for k, v in self.jobs.items() if now - v['created'] < 3600}
            if len(self.jobs) >= 32:
                raise ValueError('Download observation capacity reached; observations expire after one hour')
            token = uuid.uuid4().hex
            self.jobs[token] = dict(path=path, baseline=baseline, expected=expected,
                                    created=now, observed={}, invocation='not_requested')
            return token

    def invocation(self, token: str, state: str):
        with self.lock:
            self.jobs[token]['invocation'] = state

    def status(self, token: str) -> dict:
        with self.lock:
            job = self.jobs.get(token)
            if job is None or self.clock() - job['created'] >= 3600:
                raise ValueError('Unknown or expired download_id; do not repeat the click')
            try:
                current = snapshot(job['path'])
            except (OSError, ValueError) as exc:
                return {'download_id': token, 'status': 'observation_error',
                        'invocation': job['invocation'], 'error': str(exc)[:500],
                        'source_verified': False, 'notice': NOTICE}
            changed = {n: s for n, s in current.items() if job['baseline'].get(n) != s}
            partial = [n for n in changed if n.lower().endswith(PARTIAL)]
            candidates = {n: s for n, s in changed.items() if n not in partial
                          and (not job['expected'] or n.casefold() == job['expected'].casefold())}
            now = self.clock()
            observations = {}
            files = []
            for name, signature in candidates.items():
                previous = job['observed'].get(name)
                since = previous[1] if previous and previous[0] == signature else now
                observations[name] = (signature, since)
                files.append({'name': name, 'path': str(job['path'] / name), 'size_bytes': signature[0],
                              'stable': now - since >= 1.0,
                              'replaced_existing': name in job['baseline']})
            job['observed'] = observations
            state = 'waiting'
            if partial:
                state = 'in_progress'
            elif len(files) > 1 or any(f['replaced_existing'] for f in files):
                state = 'needs_review'
            elif files:
                state = 'file_observed' if files[0]['stable'] else 'settling'
            return {'download_id': token, 'status': state, 'invocation': job['invocation'],
                    'files': files, 'partial_files': partial, 'source_verified': False,
                    'notice': NOTICE}


REGISTRY = DownloadRegistry()
