"""Owner-only Windows DPAPI policy storage. No plaintext credential on disk.

Same-account processes are inside the trust boundary: DPAPI is not isolation
from an agent with arbitrary code/file access as the Windows owner.
"""
from contextlib import contextmanager
import ctypes as ct
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

from .permissions import validate_record


class DATA_BLOB(ct.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ct.c_void_p)]


class WindowsProtection:
    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Persistent grants require Windows DPAPI; no plaintext fallback")
        self.k = ct.WinDLL("kernel32", use_last_error=True)
        self.a = ct.WinDLL("advapi32", use_last_error=True)
        self.c = ct.WinDLL("crypt32", use_last_error=True)
        self.k.GetCurrentProcess.restype = wt.HANDLE
        self.k.CloseHandle.argtypes = (wt.HANDLE,)
        self.k.LocalFree.argtypes = (ct.c_void_p,)
        self.k.LocalFree.restype = ct.c_void_p
        self.a.OpenProcessToken.argtypes = (wt.HANDLE, wt.DWORD, ct.POINTER(wt.HANDLE))
        self.a.GetTokenInformation.argtypes = (wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD, ct.POINTER(wt.DWORD))
        self.a.ConvertSidToStringSidW.argtypes = (ct.c_void_p, ct.POINTER(ct.c_void_p))
        self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (wt.LPCWSTR, wt.DWORD, ct.POINTER(ct.c_void_p), ct.POINTER(wt.DWORD))
        self.a.SetFileSecurityW.argtypes = (wt.LPCWSTR, wt.DWORD, ct.c_void_p)
        self.c.CryptProtectData.argtypes = (ct.POINTER(DATA_BLOB), wt.LPCWSTR, ct.c_void_p, ct.c_void_p, ct.c_void_p, wt.DWORD, ct.POINTER(DATA_BLOB))
        self.c.CryptUnprotectData.argtypes = (ct.POINTER(DATA_BLOB), ct.c_void_p, ct.c_void_p, ct.c_void_p, ct.c_void_p, wt.DWORD, ct.POINTER(DATA_BLOB))
        self.sid = self.owner_sid()

    def owner_sid(self):
        token = wt.HANDLE()
        if not self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8, ct.byref(token)):
            raise ct.WinError(ct.get_last_error())
        try:
            size = wt.DWORD()
            self.a.GetTokenInformation(token, 1, None, 0, ct.byref(size))
            if not 0 < size.value <= 65536:
                raise OSError("Cannot read owner token")
            buffer = ct.create_string_buffer(size.value)
            if not self.a.GetTokenInformation(token, 1, buffer, size, ct.byref(size)):
                raise ct.WinError(ct.get_last_error())
            sid = ct.cast(buffer, ct.POINTER(ct.c_void_p))[0]
            string = ct.c_void_p()
            if not self.a.ConvertSidToStringSidW(sid, ct.byref(string)):
                raise ct.WinError(ct.get_last_error())
            try:
                return ct.wstring_at(string)
            finally:
                self.k.LocalFree(string)
        finally:
            self.k.CloseHandle(token)

    def secure(self, path):
        descriptor = ct.c_void_p()
        sddl = f"D:P(A;;FA;;;{self.sid})(A;;FA;;;SY)"
        if not self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ct.byref(descriptor), None):
            raise ct.WinError(ct.get_last_error())
        try:
            if not self.a.SetFileSecurityW(str(path), 0x80000004, descriptor):
                raise ct.WinError(ct.get_last_error())
        finally:
            self.k.LocalFree(descriptor)

    def crypt(self, data, *, decrypt=False):
        buffer = ct.create_string_buffer(data)
        source = DATA_BLOB(len(data), ct.cast(buffer, ct.c_void_p))
        result = DATA_BLOB()
        entropy_buffer = ct.create_string_buffer(b"TaskKit.vn/bridge-owner-policy/v1")
        entropy = DATA_BLOB(len(entropy_buffer.raw), ct.cast(entropy_buffer, ct.c_void_p))
        if decrypt:
            ok = self.c.CryptUnprotectData(ct.byref(source), None, ct.byref(entropy), None, None, 1, ct.byref(result))
        else:
            ok = self.c.CryptProtectData(ct.byref(source), "TaskKit bridge owner grant", ct.byref(entropy), None, None, 1, ct.byref(result))
        if not ok:
            raise ct.WinError(ct.get_last_error())
        try:
            if not 0 < result.cbData <= 65536:
                raise OSError("Invalid protected grant size")
            return ct.string_at(result.pbData, result.cbData)
        finally:
            self.k.LocalFree(result.pbData)


def reject_reparse(path):
    info = path.lstat()
    if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
        raise PermissionError("Reparse/symlink grant paths are not supported")


class WindowsGrantStore:
    _mutex = threading.RLock()

    def __init__(self, *, root=None, protection=None, create=False):
        # Custom root/protection are Python test adapters, never MCP parameters.
        self.root = Path.home() / "Win10_ComputerBridge" / "permissions" if root is None else Path(root)
        self.protection = WindowsProtection() if protection is None else protection
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        for path in (self.root.parent, self.root):
            reject_reparse(path)
        self.protection.secure(self.root)

    def path(self, profile_id):
        if str(uuid.UUID(profile_id)) != profile_id:
            raise PermissionError("Invalid profile ID")
        return self.root / (profile_id + ".dpapi")

    def read(self, profile_id):
        path = self.path(profile_id)
        reject_reparse(path)
        self.protection.secure(path)
        with path.open("rb") as source:
            data = source.read(65537)
        if not data or len(data) > 65536:
            raise PermissionError("Invalid protected grant size")
        record = json.loads(self.protection.crypt(data, decrypt=True).decode("utf-8"))
        if record.get("profile_id") != profile_id:
            raise PermissionError("Grant identity mismatch")
        return record

    @contextmanager
    def locked(self):
        with self._mutex:
            path = self.root / "write.lock"
            if path.exists():
                reject_reparse(path)
            with path.open("a+b") as lock:
                self.protection.secure(path)
                lock.seek(0, 2)
                if lock.tell() == 0:
                    lock.write(b"0"); lock.flush()
                lock.seek(0)
                if sys.platform == "win32":
                    import msvcrt
                    deadline = time.monotonic() + 1
                    while True:
                        try:
                            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                            break
                        except OSError:
                            if time.monotonic() >= deadline:
                                raise TimeoutError("Owner grant storage is busy")
                            time.sleep(0.01)
                else:
                    # Only reachable through explicit fake protection in tests.
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    yield
                finally:
                    lock.seek(0)
                    if sys.platform == "win32":
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock, fcntl.LOCK_UN)

    def _write(self, record, *, create=False):
        data = self.protection.crypt(json.dumps(record, ensure_ascii=True).encode("utf-8"))
        destination = self.path(record["profile_id"])
        if create:
            with destination.open("xb") as output:
                self.protection.secure(destination)
                output.write(data); output.flush(); os.fsync(output.fileno())
            return
        reject_reparse(destination)
        temporary = self.root / ("pending-" + str(uuid.uuid4()) + ".dpapi")
        try:
            with temporary.open("xb") as output:
                self.protection.secure(temporary)
                output.write(data); output.flush(); os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def create(self, record):
        validate_record(record)
        with self.locked():
            self._write(record, create=True)

    def claim(self, profile_id, proof_digest):
        import hmac
        with self.locked():
            record = validate_record(self.read(profile_id))
            if not hmac.compare_digest(record["key_digest"], proof_digest) or record["state"] != "active":
                raise PermissionError("Grant unavailable or credential does not match")
            record = dict(record, state="running", revision=str(uuid.uuid4()), lease_id=str(uuid.uuid4()))
            self._write(record)
            return record

    def release(self, profile_id, expected):
        with self.locked():
            record = self.read(profile_id)
            if record == expected and record["state"] == "running":
                self._write(dict(record, state="active", revision=str(uuid.uuid4()), lease_id=None))

    def set_state(self, profile_id, state):
        if state not in {"active", "paused", "revoked"}:
            raise ValueError("Invalid owner state")
        with self.locked():
            record = self.read(profile_id)
            if record["state"] == "revoked" and state != "revoked":
                raise PermissionError("Revoked credentials cannot be resumed; enroll a new profile")
            self._write(dict(record, state=state, revision=str(uuid.uuid4()), lease_id=None))


def make_record(apps, capabilities, secret, days, *, now=None):
    from .permissions import AUDIENCE, key_digest
    from .policy import normalize_allowlist
    now = time.time() if now is None else now
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError("Select a grant duration of 1 through 30 days")
    return validate_record({"schema": 1, "audience": AUDIENCE, "profile_id": str(uuid.uuid4()),
                            "key_digest": key_digest(secret), "apps": sorted(normalize_allowlist(apps)),
                            "capabilities": sorted(capabilities), "issued_at": now,
                            "expires_at": now + days * 86400, "state": "active",
                            "revision": str(uuid.uuid4()), "lease_id": None}, now=now)
