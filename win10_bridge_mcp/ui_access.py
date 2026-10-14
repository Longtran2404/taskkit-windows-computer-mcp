"""Bounded Windows UI Automation; resolve controls freshly for every operation."""
from contextlib import contextmanager
from .policy import UnsupportedControlError

SCROLL_AMOUNTS = {"large_decrement": 0, "small_decrement": 1, "none": 2,
                  "large_increment": 3, "small_increment": 4}
APP_PATTERNS = {"set_value": ("UIA_ValuePatternId", "IUIAutomationValuePattern"),
                "invoke": ("UIA_InvokePatternId", "IUIAutomationInvokePattern"),
                "select": ("UIA_SelectionItemPatternId", "IUIAutomationSelectionItemPattern"),
                "scroll": ("UIA_ScrollPatternId", "IUIAutomationScrollPattern")}


@contextmanager
def elements(hwnd, *, with_root=False):
    import comtypes
    import comtypes.client as client
    comtypes.CoInitialize()
    try:
        types = client.GetModule("UIAutomationCore.dll")
        automation = client.CreateObject(types.CUIAutomation, interface=types.IUIAutomation)
        root = automation.ElementFromHandle(hwnd)
        collection = root.FindAll(types.TreeScope_Descendants, automation.CreateTrueCondition())
        if collection.Length > 2500:
            raise RuntimeError("Control tree too large; choose a smaller target window")
        controls = [collection.GetElement(i) for i in range(collection.Length)]
        yield (types, controls, automation, root) if with_root else (types, controls)
    finally:
        comtypes.CoUninitialize()


def _inspect(hwnd, guard, expected_pid=None):
    result = []
    with elements(hwnd) as (types, controls):
        for control in controls:
            guard()
            if control.CurrentIsPassword or expected_pid is not None and control.CurrentProcessId != expected_pid:
                continue
            rect = control.CurrentBoundingRectangle
            patterns = []
            for action, (pattern_id, _) in APP_PATTERNS.items():
                guard()
                try:
                    if control.GetCurrentPattern(getattr(types, pattern_id)):
                        patterns.append(action)
                except Exception:
                    pass  # Unsupported provider pattern; never synthesize input.
            guard()
            if control.CurrentIsPassword:
                continue
            result.append({"automation_id": control.CurrentAutomationId or "",
                           "name": (control.CurrentName or "")[:300],
                           "control_type": control.CurrentControlType,
                           "enabled": bool(control.CurrentIsEnabled),
                           "process_id": control.CurrentProcessId,
                           "app_only_patterns": patterns,
                           "rect": [rect.left, rect.top, rect.right, rect.bottom]})
    return result


def _value(hwnd, automation_id, new_value, guard):
    with elements(hwnd) as (types, controls):
        matches = [c for c in controls if c.CurrentAutomationId == automation_id
                   and c.CurrentControlType == types.UIA_EditControlTypeId and not c.CurrentIsPassword]
        if len(matches) != 1:
            raise ValueError("Expected exactly one non-password edit control with this ID")
        control = matches[0]
        if not control.CurrentIsEnabled:
            raise RuntimeError("Edit control is disabled")
        raw = control.GetCurrentPattern(types.UIA_ValuePatternId)
        if not raw:
            raise RuntimeError("Edit control does not support ValuePattern")
        pattern = raw.QueryInterface(types.IUIAutomationValuePattern)
        if new_value is not None:
            guard()
            pattern.SetValue(new_value)
        guard()
        return pattern.CurrentValue


def _invoke(hwnd, automation_id, guard):
    with elements(hwnd) as (types, controls):
        matches = [c for c in controls if c.CurrentAutomationId == automation_id
                   and c.CurrentControlType == types.UIA_ButtonControlTypeId and not c.CurrentIsPassword]
        if len(matches) != 1 or not matches[0].CurrentIsEnabled:
            raise ValueError("Expected exactly one enabled button with this ID")
        raw = matches[0].GetCurrentPattern(types.UIA_InvokePatternId)
        if not raw:
            raise RuntimeError("Button does not support InvokePattern")
        pattern = raw.QueryInterface(types.IUIAutomationInvokePattern)
        guard()
        pattern.Invoke()


def _dispatch(operation, hwnd, args, guard):
    if operation == "inspect":
        return _inspect(hwnd, guard, *args)
    if operation in {"value_read", "set_value"}:
        return _value(hwnd, *args, guard)
    if operation == "invoke":
        return _invoke(hwnd, *args, guard)
    raise ValueError("Unsupported UIA operation")


def _run(operation, win, args, guard, deadline=None, authorization=None):
    from .bounded_worker import run
    from .windows_native import _native_job, latch_stop
    from .permissions import REQUEST_LEASE
    from .server import load_config
    from .permissions import config_fingerprint
    cfg = load_config()
    if authorization is None and REQUEST_LEASE.get() is not None:
        from .server import load_config, worker_permission
        cfg = load_config()
        capability = "physical_input" if operation in {"set_value", "invoke"} else "uia_read"
        descriptor = worker_permission(cfg, capability, win.exe)
        authorization = {"mode_key": "authorization_mode", "mode": "persistent",
                         "allowed": sorted(cfg["allowed"]), "persistent": descriptor}
        deadline = descriptor["deadline"]
    if authorization is None:
        authorization = {"mode_key": "authorization_mode", "mode": cfg.get("authorization_mode", "legacy"),
                         "allowed": sorted(cfg["allowed"]), "persistent": None}
    authorization = dict(authorization, authorization_policy=config_fingerprint(cfg))
    try:
        return run(_native_job, (operation, win, args, deadline, authorization), timeout=3.0,
                   guard=guard, on_unreaped=latch_stop)
    except InterruptedError:
        latch_stop()
        raise


def inspect(win, guard):
    return _run("inspect", win, (win.pid,), guard)


def value(win, automation_id, new_value=None, *, guard, deadline=None):
    return _run("value_read" if new_value is None else "set_value",
                win, (automation_id, new_value), guard, deadline)


def invoke(win, automation_id, guard, *, deadline=None):
    return _run("invoke", win, (automation_id,), guard, deadline)


def _verify_app_ancestry(automation, root, control, win, guard):
    guard()
    fresh_root = automation.ElementFromHandle(win.hwnd)
    if (root.CurrentNativeWindowHandle != win.hwnd or root.CurrentProcessId != win.pid or
            not automation.CompareElements(root, fresh_root)):
        raise PermissionError("Selected UIA window root changed; inspect/capture again")
    current = control
    for _ in range(64):
        guard()
        if automation.CompareElements(current, root):
            return
        current = automation.RawViewWalker.GetParentElement(current)
        if not current:
            break
    raise PermissionError("Control is no longer a descendant of the selected window root")


def _app_dispatch(action, win, args, guard):
    """Semantic control operation rooted in the selected HWND; never focus/input.

    Providers may cause their own application focus/UI changes. Missing patterns
    are explicit errors, with no SetFocus, SendInput or PostMessage fallback.
    """
    automation_id, new_value, horizontal, vertical = args
    if action not in APP_PATTERNS:
        raise ValueError("Unsupported app-only action")
    with elements(win.hwnd, with_root=True) as (types, controls, automation, root):
        matches = [c for c in controls if not c.CurrentIsPassword
                   and c.CurrentAutomationId == automation_id]
        if len(matches) != 1:
            raise ValueError("Expected one non-password control with the selected automation ID")
        control = matches[0]
        def control_guard():
            guard()
            _verify_app_ancestry(automation, root, control, win, guard)
            if control.CurrentIsPassword or control.CurrentAutomationId != automation_id:
                raise PermissionError("Control identity/password state changed; refused")
            rect = control.CurrentBoundingRectangle
            if (control.CurrentProcessId != win.pid or rect.right <= rect.left or rect.bottom <= rect.top or
                    rect.left < win.rect.left or rect.top < win.rect.top or
                    rect.right > win.rect.right or rect.bottom > win.rect.bottom):
                raise PermissionError("Control process/bounds do not belong to the selected captured window")
            if not control.CurrentIsEnabled:
                raise UnsupportedControlError("Selected control is disabled")
            guard()
        control_guard()
        pattern_id, interface = APP_PATTERNS[action]
        try:
            raw = control.GetCurrentPattern(getattr(types, pattern_id))
            if not raw:
                raise UnsupportedControlError(f"Control does not expose {action} pattern")
            pattern = raw.QueryInterface(getattr(types, interface))
        except UnsupportedControlError:
            raise
        except Exception as exc:
            raise UnsupportedControlError(f"Control does not expose usable {action} pattern") from exc
        if action == "set_value":
            if pattern.CurrentIsReadOnly:
                raise UnsupportedControlError("Selected ValuePattern is read-only")
            control_guard()
            pattern.SetValue(new_value)
            control_guard()
            return {"value_matches": pattern.CurrentValue == new_value}
        if action == "invoke":
            control_guard()
            pattern.Invoke()
            control_guard()
            return {"invoke_requested": True, "effects_verified": False}
        if action == "select":
            control_guard()
            pattern.Select()
            control_guard()
            return {"selected": bool(pattern.CurrentIsSelected)}
        if horizontal not in SCROLL_AMOUNTS or vertical not in SCROLL_AMOUNTS or horizontal == vertical == "none":
            raise ValueError("Specify at least one bounded semantic scroll amount")
        if (horizontal != "none" and not pattern.CurrentHorizontallyScrollable or
                vertical != "none" and not pattern.CurrentVerticallyScrollable):
            raise UnsupportedControlError("Selected control does not support the requested scroll axis")
        before = [pattern.CurrentHorizontalScrollPercent, pattern.CurrentVerticalScrollPercent]
        control_guard()
        pattern.Scroll(SCROLL_AMOUNTS[horizontal], SCROLL_AMOUNTS[vertical])
        control_guard()
        after = [pattern.CurrentHorizontalScrollPercent, pattern.CurrentVerticalScrollPercent]
        return {"scroll_requested": True, "percent_before": before, "percent_after": after,
                "percent_changed": before != after, "effects_verified": False}


def app_action(win, automation_id, action, value, horizontal, vertical, *, guard, deadline, authorization):
    return _run("app_" + action, win, (automation_id, value, horizontal, vertical), guard, deadline, authorization)
