from dataclasses import dataclass, replace
import threading
from win10_bridge_mcp.policy import Rect


@dataclass(frozen=True)
class FakeWindow:
    id: str = '123:abc:creation1'
    hwnd: int = 0xabc
    pid: int = 123
    exe: str = 'notepad.exe'
    title: str = 'Fake editor'
    rect: Rect = Rect(-1200, -200, -400, 400)
    dpi: int = 144


class FakeAdapter:
    key_codes = {'ctrl': 17, 'alt': 18, 'shift': 16, 'space': 32, 'a': 65, 's': 83}

    def __init__(self, win=None):
        self.current = win or FakeWindow()
        self.foreground = self.current.hwnd
        self.pointer = (-1000, 0)
        self.stopped = False
        self.overlay = False
        self.clamp = False
        self.user_held = set()
        self.depressed = []
        self.events = []
        self.stages = []
        self.hook = lambda stage, adapter: None
        self.clock = 0.0
        self.check_count = 0

    def stage(self, name):
        self.stages.append(name)
        self.hook(name, self)

    def check(self, win, *, foreground=True):
        self.check_count += 1
        self.stage('check')
        if self.stopped:
            raise InterruptedError('stop latched')
        if (self.current.id, self.current.rect, self.current.dpi) != (win.id, win.rect, win.dpi):
            raise RuntimeError('identity/geometry/DPI changed')
        if foreground and self.foreground != win.hwnd:
            raise RuntimeError('focus stolen')

    def activate(self, win):
        self.stage('activate')

    def cursor(self):
        self.stage('cursor')
        return self.pointer

    def held_inputs(self):
        self.stage('held')
        return self.user_held | set().union(*(self.code(k, v) for k, v in self.depressed))

    def code(self, kind, value):
        if kind == 'button':
            return {{'left': 1, 'right': 2, 'middle': 4, 'x1': 5, 'x2': 6}[value]}
        if kind == 'unicode':
            return {231}
        return {17: {17, 162, 163}, 16: {16, 160, 161}, 18: {18, 164, 165}}.get(value, {value})

    def emit(self, kind, value, down):
        self.stage('down' if down else 'up')
        self.events.append((kind, value, down))
        if down:
            self.depressed.append((kind, value))
        else:
            self.depressed.remove((kind, value))

    def position(self, x, y):
        self.stage('position')
        self.pointer = (x + 10 if self.clamp else x, y)

    def verify_hit(self, win, x, y):
        self.stage('hit')
        if self.overlay:
            raise RuntimeError('overlay covers target')
        if (x, y) != self.pointer:
            raise InterruptedError('cursor changed during hit query')

    def wait(self, seconds):
        self.stage('wait')
        self.clock += seconds

    def wheel(self, axis, value):
        self.stage('wheel')
        self.events.append(('wheel', axis, value))


class FakeBackend:
    KEY_CODES = FakeAdapter.key_codes

    def __init__(self):
        self.current = FakeWindow()
        self.SESSION_STOP = threading.Event()
        self.operations = []
        self.capture_hook = lambda: None
        from win10_bridge_mcp.capture_policy import Display, DesktopLayout
        self.layout = DesktopLayout((Display('left', Rect(-1280,0,0,720),144,144,scale_percent=150),
                                     Display('right', Rect(0,0,1920,1080),96,96)))
        self.screen_hook = lambda: None

    def enable_session_stop(self):
        pass

    def latch_stop(self):
        self.SESSION_STOP.set()

    def release_all(self):
        self.operations.append('emergency release')
        return []

    def local_path(self, path, *, directory=False):
        self._stop_if_needed()
        return path

    def _stop_if_needed(self):
        if self.SESSION_STOP.is_set():
            raise InterruptedError('permanent stop')

    def get_window(self, window_id, allowed):
        self._stop_if_needed()
        if window_id != self.current.id or self.current.exe not in allowed:
            raise ValueError('identity changed')
        return self.current

    def check_window(self, win, *, foreground=False):
        self._stop_if_needed()
        if (win.id, win.rect, win.dpi) != (self.current.id, self.current.rect, self.current.dpi):
            raise ValueError('identity/geometry/DPI changed')

    def capture_window(self, win, **kwargs):
        from PIL import Image
        from io import BytesIO
        stream = BytesIO()
        Image.new('RGB', (win.rect.width, win.rect.height), 'blue').save(stream, 'PNG')
        self.capture_hook()
        if 'guard' in kwargs: kwargs['guard']()
        return stream.getvalue(), 'fake PrintWindow', False

    def screen_layout(self):
        self._stop_if_needed()
        return self.layout

    def capture_screen(self, rect, layout, *, guard, deadline, authorization):
        from PIL import Image
        from io import BytesIO
        guard()
        stream = BytesIO()
        Image.new('RGB', (rect.width, rect.height), 'blue').save(stream, 'PNG')
        self.screen_hook()
        guard()
        return stream.getvalue(), 'fake desktop BitBlt', False

    def _activate(self, win):
        self.check_window(win)

    def _apply(self, *args, guard, **kwargs):
        guard()
        self.operations.append(args)

    apply_mouse = apply_keys = apply_text = _apply

    def enumerate_windows(self, allowed):
        self._stop_if_needed()
        return [self.current]
