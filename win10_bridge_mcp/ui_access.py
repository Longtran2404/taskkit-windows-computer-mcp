"""Bounded Windows UI Automation; resolve controls freshly for every operation."""
from contextlib import contextmanager


@contextmanager
def elements(hwnd):
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
        yield types, [collection.GetElement(i) for i in range(collection.Length)]
    finally:
        comtypes.CoUninitialize()


def _inspect(hwnd, guard):
    result = []
    with elements(hwnd) as (types, controls):
        for control in controls:
            guard()
            if control.CurrentIsPassword:
                continue
            rect = control.CurrentBoundingRectangle
            result.append({"automation_id": control.CurrentAutomationId or "",
                           "name": (control.CurrentName or "")[:300],
                           "control_type": control.CurrentControlType,
                           "enabled": bool(control.CurrentIsEnabled),
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
        return _inspect(hwnd, guard)
    if operation in {"value_read", "set_value"}:
        return _value(hwnd, *args, guard)
    if operation == "invoke":
        return _invoke(hwnd, *args, guard)
    raise ValueError("Unsupported UIA operation")


def _run(operation, win, args, guard, deadline=None):
    from .bounded_worker import run
    from .windows_native import _native_job, latch_stop
    try:
        return run(_native_job, (operation, win, args, deadline), timeout=3.0,
                   guard=guard, on_unreaped=latch_stop)
    except InterruptedError:
        latch_stop()
        raise


def inspect(win, guard):
    return _run("inspect", win, (), guard)


def value(win, automation_id, new_value=None, *, guard, deadline=None):
    return _run("value_read" if new_value is None else "set_value",
                win, (automation_id, new_value), guard, deadline)


def invoke(win, automation_id, guard, *, deadline=None):
    return _run("invoke", win, (automation_id,), guard, deadline)
