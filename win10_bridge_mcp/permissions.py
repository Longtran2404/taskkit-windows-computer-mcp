"""Explicit owner policy + authenticated launch profile + disposable MCP lease.

The bearer key authenticates a bridge profile, not a ChatGPT account. Neither
clientInfo nor a successful initialize is evidence of Windows authorization.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import threading
import time
import uuid

AUDIENCE = "taskkit-windows-bridge/v1"
MAX_DAYS = 30
CAPABILITIES = {
    "read_targets": "Read selected app window titles and monitor geometry",
    "uia_read": "Read selected apps' non-password UI Automation controls/text",
    "capture_window": "Send screenshots of current/future windows of selected apps to the AI host",
    "app_actions": "SetValue / Invoke / Select / Scroll in selected apps (provider may affect focus)",
    "physical_input": "Use the real mouse, keyboard and foreground focus in selected apps",
    "file_save": "Create a Notepad UTF-8 .txt copy at an absolute local path; optionally open it",
    "open_directory": "Open local folders in Explorer",
    "read_drives": "Read local drive root names",
    "local_preview": "Show a local preview of selected app windows",
    "capture_monitor": "SEND monitor pixels, including other apps and visible secrets",
    "capture_region": "SEND arbitrary region pixels, including other apps and visible secrets",
    "capture_desktop": "SEND all-monitor desktop pixels, including other apps and visible secrets",
}
DEPENDENCIES = {"app_actions": {"capture_window"}, "physical_input": {"capture_window"},
                "file_save": {"capture_window", "uia_read"}}
REQUEST_LEASE = ContextVar("taskkit_permission_lease", default=None)


def key_digest(secret):
    if not isinstance(secret, str) or not re.fullmatch(r"tkcu_v1_[A-Za-z0-9_-]{43}", secret):
        raise PermissionError("Missing or invalid bridge profile credential")
    return hashlib.sha256((AUDIENCE + "\0" + secret).encode("ascii")).hexdigest()


def eligible_capabilities(cfg):
    caps = {"read_targets", "uia_read", "read_drives", "local_preview"}
    mapping = {"window": "capture_window", "monitor": "capture_monitor",
               "region": "capture_region", "virtual_desktop": "capture_desktop"}
    caps.update(mapping[m] for m in cfg["capture_modes"])
    if cfg["semantic_control_mode"] == "app_session":
        caps.add("app_actions")
    if cfg["mouse_control_mode"] == "foreground_session":
        caps.update({"physical_input", "file_save"})
        if "explorer.exe" in cfg["allowed"]:
            caps.add("open_directory")
    return frozenset(caps)


def config_fingerprint(cfg):
    return (cfg.get("authorization_mode", "legacy"), tuple(sorted(cfg["allowed"])),
            cfg["mouse_control_mode"], cfg["semantic_control_mode"],
            tuple(cfg["capture_modes"]), cfg["capture_consent_mode"])


def validate_record(record, *, now=None):
    now = time.time() if now is None else now
    required = {"schema", "audience", "profile_id", "key_digest", "apps", "capabilities",
                "issued_at", "expires_at", "state", "revision", "lease_id"}
    if not isinstance(record, dict) or set(record) != required:
        raise PermissionError("Invalid owner grant record")
    if record["schema"] != 1 or record["audience"] != AUDIENCE:
        raise PermissionError("Wrong bridge grant schema/audience")
    for field in ("profile_id", "revision"):
        if not isinstance(record[field], str) or str(uuid.UUID(record[field])) != record[field]:
            raise PermissionError("Invalid owner grant identity")
    if not re.fullmatch(r"[0-9a-f]{64}", record["key_digest"] or ""):
        raise PermissionError("Invalid owner grant credential digest")
    from .policy import normalize_allowlist
    apps = record["apps"]
    if not isinstance(apps, list) or sorted(normalize_allowlist(apps)) != apps or not apps:
        raise PermissionError("Owner must explicitly select apps")
    caps = record["capabilities"]
    if not isinstance(caps, list) or not caps or any(c not in CAPABILITIES for c in caps) or len(set(caps)) != len(caps):
        raise PermissionError("Invalid owner capability selection")
    for capability in caps:
        missing = DEPENDENCIES.get(capability, set()) - set(caps)
        if missing:
            raise PermissionError(capability + " requires explicit owner selection of: " + ", ".join(sorted(missing)))
    issued, expires = record["issued_at"], record["expires_at"]
    if (type(issued) not in {float, int} or type(expires) not in {float, int} or
            not 0 < expires - issued <= MAX_DAYS * 86400 or not issued <= now < expires):
        raise PermissionError("Owner grant expired, future-dated or exceeds 30 days")
    if record["state"] not in {"active", "running", "paused", "revoked"}:
        raise PermissionError("Invalid owner grant state")
    if record["state"] == "running":
        if not isinstance(record["lease_id"], str) or str(uuid.UUID(record["lease_id"])) != record["lease_id"]:
            raise PermissionError("Invalid connection lease")
    elif record["lease_id"] is not None:
        raise PermissionError("Unexpected connection lease")
    return record


@dataclass
class Lease:
    record: dict
    policy: tuple
    expires: float
    cancelled: threading.Event
    session: object = None
    params: object = None
    client_fingerprint: str = ""
    operations: list = None
    unclean: bool = False


class PermissionRuntime:
    def __init__(self, store_factory=None):
        self.store_factory = store_factory
        self.lease = None
        self.store = None
        self.profile_id = None
        self.proof_digest = None
        self.error = "No authenticated launch profile"
        self.stopping = False
        self.lock = threading.RLock()

    def configure(self, cfg, environment):
        """Called locally at startup; credentials never enter MCP arguments/results."""
        secret = environment.pop("TASKKIT_CLIENT_SECRET", None)
        if cfg.get("authorization_mode", "legacy") != "persistent":
            return
        try:
            self.profile_id = environment.get("TASKKIT_CLIENT_ID")
            if str(uuid.UUID(self.profile_id)) != self.profile_id:
                raise PermissionError("Invalid bridge profile ID")
            self.proof_digest = key_digest(secret)
            if self.store_factory is None:
                from .permission_store import WindowsGrantStore
                self.store = WindowsGrantStore()
            else:
                self.store = self.store_factory()
            record = validate_record(self.store.read(self.profile_id))
            if not hmac.compare_digest(record["key_digest"], self.proof_digest):
                raise PermissionError("Bridge profile authentication failed")
            self.error = "Connection has not started"
        except Exception:
            self.store = None
            self.proof_digest = None
            self.error = "Bridge profile authentication unavailable/failed; enroll locally and supply its credential"
        finally:
            secret = None

    def start(self, cfg):
        if cfg.get("authorization_mode", "legacy") != "persistent":
            return
        with self.lock:
            if self.store is None or self.stopping:
                return
            try:
                candidate = validate_record(self.store.read(self.profile_id))
                if not set(candidate["apps"]) <= cfg["allowed"] or not set(candidate["capabilities"]) <= eligible_capabilities(cfg):
                    raise PermissionError("Stored scope exceeds current eligibility")
                record = self.store.claim(self.profile_id, self.proof_digest)
                validate_record(record)
                if not set(record["apps"]) <= cfg["allowed"] or not set(record["capabilities"]) <= eligible_capabilities(cfg):
                    raise PermissionError("Owner policy changed during connection claim")
                self.lease = Lease(record, config_fingerprint(cfg),
                                   time.monotonic() + record["expires_at"] - time.time(), threading.Event())
                self.lease.operations = []
                self.error = ""
            except Exception:
                self.error = "Grant paused/revoked/expired, already in use, or previous bridge did not close cleanly; inspect locally"

    @contextmanager
    def request(self, session):
        with self.lock:
            lease = self.lease
            if lease is not None:
                params = getattr(session, "client_params", None)
                if params is None:
                    lease.cancelled.set()
                elif lease.session is None:
                    lease.session, lease.params = session, params
                    lease.client_fingerprint = params.model_dump_json()
                elif (session is not lease.session or params is not lease.params or
                      params.model_dump_json() != lease.client_fingerprint):
                    lease.cancelled.set()  # Also detect an identical second initialize.
            token = REQUEST_LEASE.set(lease)
        try:
            yield lease
        finally:
            REQUEST_LEASE.reset(token)

    def check(self, cfg, capability=None, exe=None, *, lease=None):
        if cfg.get("authorization_mode", "legacy") != "persistent":
            # Changing persistent -> legacy mid-transaction cannot shed its lease.
            if REQUEST_LEASE.get() is not None:
                raise PermissionError("Authorization mode changed; reconnect after local review")
            return None
        lease = REQUEST_LEASE.get() if lease is None else lease
        with self.lock:
            if lease is None or lease is not self.lease or lease.cancelled.is_set() or self.stopping:
                raise PermissionError("No live authenticated MCP connection lease")
            if (lease.session is None or getattr(lease.session, "client_params", None) is not lease.params or
                    lease.params.model_dump_json() != lease.client_fingerprint):
                lease.cancelled.set()
                raise PermissionError("MCP connection/initialize identity changed")
            if config_fingerprint(cfg) != lease.policy or time.monotonic() >= lease.expires:
                lease.cancelled.set()
                raise PermissionError("Owner policy changed or grant expired")
            record = validate_record(self.store.read(self.profile_id))
            if (record != lease.record or record["state"] != "running" or
                    not hmac.compare_digest(record["key_digest"], self.proof_digest)):
                lease.cancelled.set()
                raise PermissionError("Owner grant paused, revoked or replaced")
            if not set(record["apps"]) <= cfg["allowed"] or not set(record["capabilities"]) <= eligible_capabilities(cfg):
                lease.cancelled.set()
                raise PermissionError("Grant exceeds current local eligibility")
            if capability is not None and capability not in record["capabilities"]:
                raise PermissionError("Capability not granted by owner: " + capability)
            if exe is not None and exe not in record["apps"]:
                raise PermissionError("Application not granted by owner")
            return lease

    def allowed(self, cfg):
        lease = self.check(cfg)
        return frozenset(lease.record["apps"]) if lease else cfg["allowed"]

    def operation(self, lease):
        done = threading.Event()
        if lease is not None:
            with self.lock:
                lease.operations[:] = [event for event in lease.operations if not event.is_set()]
                lease.operations.append(done)
        return done

    def cancel(self, lease, *, unclean=False):
        if lease is not None:
            if unclean:
                lease.unclean = True
            lease.cancelled.set()

    def pause(self):
        """Only reduces authority; never resumes or provisions a grant."""
        with self.lock:
            self.stopping = True
            self.cancel(self.lease)
            if self.store and self.profile_id:
                # A running marker stays on disk even if this write fails. Thus a
                # restart cannot silently reuse a stopped/crashed connection.
                self.store.set_state(self.profile_id, "paused")

    def end(self):
        with self.lock:
            lease = self.lease
            self.cancel(lease)
            if lease is not None and not self.stopping and not lease.unclean and all(e.is_set() for e in lease.operations):
                try:
                    self.store.release(self.profile_id, lease.record)
                except Exception:
                    self.error = "Connection release failed; running marker requires local recovery"
            self.lease = None

    def status(self, cfg=None):
        with self.lock:
            lease = self.lease
            alive = bool(lease and not lease.cancelled.is_set() and not self.stopping)
            if alive:
                try:
                    alive = validate_record(self.store.read(self.profile_id)) == lease.record and time.monotonic() < lease.expires
                    if cfg is not None and config_fingerprint(cfg) != lease.policy:
                        alive = False
                except Exception:
                    alive = False
            return {"mode": "persistent_bridge_profile", "authenticated": alive,
                    "profile_id": self.profile_id if alive else None,
                    "connection_id": lease.record["lease_id"] if alive else None,
                    "client_label_authenticated": False, "native_chatgpt_permission_import": False,
                    "apps": lease.record["apps"] if alive else [],
                    "capabilities": lease.record["capabilities"] if alive else [],
                    "expires_at_unix": lease.record["expires_at"] if alive else None,
                    "error": "" if alive else self.error or "Connection grant is inactive"}


def check_worker_authorization(descriptor, cfg):
    """No secret in worker payload. Parent authenticated; child rechecks policy."""
    if descriptor is None:
        if cfg.get("authorization_mode", "legacy") == "persistent":
            raise PermissionError("Persistent native operation requires an authenticated owner grant")
        return
    from .permission_store import WindowsGrantStore
    record = validate_record(WindowsGrantStore().read(descriptor["profile_id"]))
    if (record != descriptor["record"] or config_fingerprint(cfg) != tuple_policy(descriptor["policy"]) or
            time.monotonic() >= descriptor["deadline"]):
        raise PermissionError("Persistent grant changed/expired before native effect")
    if descriptor["capability"] not in record["capabilities"]:
        raise PermissionError("Native capability outside owner grant")
    if descriptor.get("exe") and descriptor["exe"] not in record["apps"]:
        raise PermissionError("Native target outside owner grant")


def tuple_policy(value):
    # JSON/spawn may reconstruct sequence fields as lists.
    return (value[0], tuple(value[1]), value[2], value[3], tuple(value[4]), value[5])
