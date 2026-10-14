"""Process-local, expiring consent; configuration alone never arms input."""
import time

SESSION_SECONDS = 300


class ConsentGate:
    def __init__(self, mode_key="mouse_control_mode"):
        self.scope = None
        self.expires = 0.0
        self.mode_key = mode_key

    def fingerprint(self, cfg):
        return cfg[self.mode_key], tuple(sorted(cfg["allowed"])), cfg.get("consent_window_id")

    def armed(self, cfg):
        return self.scope == self.fingerprint(cfg) and time.monotonic() < self.expires

    def require(self, cfg, ask, guard, *, description=None):
        guard()
        if not self.armed(cfg):
            self.scope, self.expires = None, 0.0
            if not ask(description or ("Authorize foreground input/UIA/file operations for up to 5 minutes?\n"
                       "Allowed apps: " + ", ".join(sorted(cfg["allowed"])) +
                       "\nEsc/F12 or closing preview permanently stops this process.\n"
                       "The real mouse and focus will be occupied.")):
                raise PermissionError("Owner declined local session consent")
            guard()
            self.scope = self.fingerprint(cfg)
            self.expires = time.monotonic() + SESSION_SECONDS

    def check(self, cfg):
        if not self.armed(cfg):
            raise PermissionError("Local session consent expired or configuration changed; authorize locally again")
