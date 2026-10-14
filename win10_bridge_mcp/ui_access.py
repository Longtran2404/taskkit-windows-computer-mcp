"""Bounded Windows UI Automation; resolve controls freshly for every operation."""
from contextlib import contextmanager


def focus_window(hwnd):
    import comtypes
    import comtypes.client as client
    comtypes.CoInitialize()
    try:
        types = client.GetModule("UIAutomationCore.dll")
        automation = client.CreateObject(types.CUIAutomation, interface=types.IUIAutomation)
        automation.ElementFromHandle(hwnd).SetFocus()
    finally:
        comtypes.CoUninitialize()


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


def inspect(hwnd):
    result = []
    with elements(hwnd) as (types, controls):
        for control in controls:
            if control.CurrentIsPassword:
                continue
            rect = control.CurrentBoundingRectangle
            result.append({"automation_id": control.CurrentAutomationId or "",
                           "name": (control.CurrentName or "")[:300],
                           "control_type": control.CurrentControlType,
                           "enabled": bool(control.CurrentIsEnabled),
                           "rect": [rect.left, rect.top, rect.right, rect.bottom]})
    return result


def value(hwnd, automation_id, new_value=None):
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
            pattern.SetValue(new_value)
        return pattern.CurrentValue


def invoke(hwnd, automation_id):
    with elements(hwnd) as (types, controls):
        matches = [c for c in controls if c.CurrentAutomationId == automation_id
                   and c.CurrentControlType == types.UIA_ButtonControlTypeId]
        if len(matches) != 1 or not matches[0].CurrentIsEnabled:
            raise ValueError("Expected exactly one enabled button with this ID")
        raw = matches[0].GetCurrentPattern(types.UIA_InvokePatternId)
        if not raw:
            raise RuntimeError("Button does not support InvokePattern")
        raw.QueryInterface(types.IUIAutomationInvokePattern).Invoke()
