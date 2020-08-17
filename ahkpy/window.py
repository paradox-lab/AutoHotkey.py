import dataclasses as dc
import enum
import functools

from . import colors
from . import keys as hotkeys
from .converters import default, optional_ms
from .exceptions import Error
from .flow import ahk_call, global_ahk_lock
from .settings import get_settings

__all__ = [
    "Control",
    "ExWindowStyle",
    "TitleMatchMode",
    "Window",
    "Windows",
    "WindowStyle",
    "all_windows",
    "visible_windows",
    "windows",
]


class TitleMatchMode(enum.Enum):
    STARTSWITH = "startswith"
    CONTAINS = "contains"
    EXACT = "exact"
    REGEX = "regex"


class TextMatchMode(enum.Enum):
    FAST = "fast"
    SLOW = "slow"


class UnsetType:
    def __repr__(self):
        return "UNSET"


UNSET = UnsetType()


def filtering(func):
    @functools.wraps(func)
    def wrapper(
        self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET, **kwargs,
    ):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text, match=match)
        return func(self, **kwargs)
    return wrapper


@dc.dataclass(frozen=True)
class Windows:
    title: str = UNSET
    class_name: str = UNSET
    id: int = UNSET
    pid: int = UNSET
    exe: str = UNSET
    text: str = UNSET
    exclude_title: str = UNSET
    exclude_text: str = UNSET
    exclude_hidden_windows: bool = UNSET  # True by default
    exclude_hidden_text: bool = UNSET  # True by default
    title_mode: str = UNSET  # "startswith" by default
    text_mode: str = UNSET  # "fast" by default

    def filter(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        if (
            title is UNSET and class_name is UNSET and id is UNSET and pid is UNSET and exe is UNSET and
            text is UNSET and match is UNSET
        ):
            return self

        if isinstance(match, str):
            match = TitleMatchMode(match.lower())

        return dc.replace(
            self,
            title=default(title, self.title, none=UNSET),
            class_name=default(class_name, self.class_name, none=UNSET),
            id=default(id, self.id, none=UNSET),
            pid=default(pid, self.pid, none=UNSET),
            exe=default(exe, self.exe, none=UNSET),
            text=default(text, self.text, none=UNSET),
            title_mode=default(match, self.title_mode, none=UNSET),
        )

    def exclude(self, title=UNSET, *, text=UNSET, hidden_windows=UNSET, hidden_text=UNSET):
        # XXX: Consider implementing class_name, id, pid, and exe exclusion in
        # Python.
        if title is UNSET and text is UNSET and hidden_windows is UNSET and hidden_text is UNSET:
            return self
        return dc.replace(
            self,
            exclude_title=default(title, self.exclude_title, none=UNSET),
            exclude_text=default(text, self.exclude_text, none=UNSET),
            exclude_hidden_windows=default(hidden_windows, self.exclude_hidden_windows, none=UNSET),
            exclude_hidden_text=default(hidden_text, self.exclude_hidden_text, none=UNSET),
        )

    def match_text_slow(self, is_slow=True):
        # Not including the parameter in filter() because it's used very rarely.
        if is_slow:
            return dc.replace(self, text_mode=TextMatchMode.SLOW)
        else:
            return dc.replace(self, text_mode=TextMatchMode.FAST)

    @filtering
    def exist(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        win_id = self._call("WinExist", *self._query()) or 0
        return Window(win_id)

    first = exist
    top = exist

    @filtering
    def last(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        win_id = self._call("WinGet", "IDLast", *self._query()) or 0
        return Window(win_id)

    bottom = last

    @filtering
    def get_active(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        query = self._query()
        if query == ("", "", "", ""):
            query = ("A", "", "", "")
        win_id = self._call("WinActive", *query) or 0
        return Window(win_id)

    @filtering
    def wait(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET,
             timeout=None):
        return self._wait("WinWait", timeout)

    @filtering
    def wait_active(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET,
                    timeout=None):
        return self._wait("WinWaitActive", timeout)

    @filtering
    def wait_inactive(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET,
                      timeout=None):
        return self._wait("WinWaitNotActive", timeout)

    @filtering
    def wait_close(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET,
                   timeout=None):
        # WinWaitClose doesn't set Last Found Window, return False if the wait
        # was timed out.
        timed_out = self._call("WinWaitClose", *self._include(), timeout or "", *self._exclude(), set_delay=True)
        # If some of the query parameters is None, then the self._call will also
        # return None. Returning `not None` is ok because the matching window
        # doesn't exist, and that's what we are waiting for.
        return not timed_out

    def _wait(self, cmd, timeout):
        # Calling WinWait[Not]Active and WinWait sets an implicit Last Found
        # Window that is local to the current AHK thread. Let's retrieve it
        # while protecting it from being overwritten by other Python threads.
        with global_ahk_lock:
            timed_out = self._call(cmd, *self._include(), timeout or "", *self._exclude(), set_delay=True)
            if timed_out is None or timed_out:
                # timed_out may be None if some of the query parameters is None.
                return Window(0)
            # Return the Last Found Window.
            return windows.first()

    @filtering
    def activate(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET,
                 timeout=None):
        with global_ahk_lock:
            self._call("WinActivate", *self._query(), set_delay=True)
            if timeout is not None:
                return self.wait_active(timeout=timeout)

    @filtering
    def close(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET,
              timeout=None):
        self._call("WinClose", *self._include(), timeout, *self._exclude(), set_delay=True)

    @filtering
    def hide(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinHide", *self._query(), set_delay=True)

    @filtering
    def kill(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET,
             timeout=None):
        self._call("WinKill", *self._include(), timeout, *self._exclude(), set_delay=True)

    @filtering
    def maximize(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinMaximize", *self._query(), set_delay=True)

    @filtering
    def minimize(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinMinimize", *self._query(), set_delay=True)

    @filtering
    def restore(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinRestore", *self._query(), set_delay=True)

    @filtering
    def show(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinShow", *self._query(), set_delay=True)

    @filtering
    def pin_to_top(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinSet", "AlwaysOnTop", "On", *self._query())

    @filtering
    def unpin_from_top(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinSet", "AlwaysOnTop", "Off", *self._query())

    @filtering
    def toggle_always_on_top(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinSet", "AlwaysOnTop", "Toggle", *self._query())

    @filtering
    def bring_to_top(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinSet", "Top", "", *self._query())

    @filtering
    def send_to_bottom(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinSet", "Bottom", "", *self._query())

    @filtering
    def disable(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinSet", "Disable", "", *self._query())

    @filtering
    def enable(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinSet", "Enable", "", *self._query())

    @filtering
    def redraw(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._call("WinSet", "Redraw", "", *self._query())

    @filtering
    def close_all(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET,
                  timeout=None):
        return self._group_action("WinClose", timeout)

    @filtering
    def hide_all(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        return self._group_action("WinHide")

    @filtering
    def kill_all(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET,
                 timeout=None):
        return self._group_action("WinKill", timeout)

    @filtering
    def maximize_all(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        return self._group_action("WinMaximize")

    @filtering
    def minimize_all(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        return self._group_action("WinMinimize")

    # TODO: Implement WinMinimizeAllUndo.

    @filtering
    def restore_all(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._group_action("WinRestore")

    @filtering
    def show_all(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self._group_action("WinShow")

    def _group_action(self, cmd, timeout=None):
        if self == Windows() and cmd == "WinMinimize":
            # If the filter matches all the windows, minimize everything except
            # the desktop window.
            self._call("WinMinimizeAll", set_delay=True)
            return

        query_hash = hash(self)
        query_hash_str = str(query_hash).replace("-", "m")  # AHK doesn't allow "-" in group names
        label = ""
        self._call("GroupAdd", query_hash_str, *self._include(), label, *self._exclude())
        self._call(cmd, f"ahk_group {query_hash_str}", "", timeout, set_delay=True)
        if timeout is not None:
            return not self.exist()

    @filtering
    def window_context(self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        # Not using Hotkey, IfWinActive/Exist because:
        #
        # 1. It doesn't support excluding windows.
        # 2. It doesn't set DetectHiddenWindows from the given query before
        #    enumerating the windows.
        return hotkeys.HotkeyContext(lambda: self.exist())

    @filtering
    def nonexistent_window_context(
            self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        return hotkeys.HotkeyContext(lambda: not self.exist())

    @filtering
    def active_window_context(
            self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        return hotkeys.HotkeyContext(lambda: self.get_active())

    @filtering
    def inactive_window_context(
            self, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        return hotkeys.HotkeyContext(lambda: not self.get_active())

    def send(self, keys, title=UNSET, *, class_name=UNSET, id=UNSET, pid=UNSET, exe=UNSET, text=UNSET, match=UNSET):
        self = self.filter(title=title, class_name=class_name, id=id, pid=pid, exe=exe, text=text, match=match)
        with global_ahk_lock:
            hotkeys._set_key_delay()
            control = ""
            self._call("ControlSend", control, str(keys), *self._query())

    def __iter__(self):
        """Return matching windows ordered from top to bottom."""
        win_ids = self._call("WinGet", "List", *self._query())
        if win_ids is None:
            return
        for win_id in win_ids.values():
            yield Window(win_id)

    def __len__(self):
        return self._call("WinGet", "Count", *self._query()) or 0

    def __repr__(self):
        field_strs = []
        for field in dc.fields(self):
            value = getattr(self, field.name)
            if value is not UNSET:
                field_strs.append(f"{field.name}={value!r}")
        return self.__class__.__qualname__ + f"({', '.join(field_strs)})"

    def _call(self, cmd, *args, set_delay=False):
        if (
            self.title is None or self.class_name is None or self.id is None or self.pid is None or self.exe is None or
            self.text is None
        ):
            # Querying a non-existent window's attributes.
            return
        with global_ahk_lock:
            if self.exclude_hidden_windows:  # Also matches UNSET
                ahk_call("DetectHiddenWindows", "Off")
            else:
                ahk_call("DetectHiddenWindows", "On")

            if self.text is not UNSET:
                if self.exclude_hidden_text:  # Also matches UNSET
                    ahk_call("DetectHiddenText", "Off")
                else:
                    ahk_call("DetectHiddenText", "On")

            if self.title_mode is TitleMatchMode.STARTSWITH or self.title_mode is UNSET:
                ahk_call("SetTitleMatchMode", 1)
            elif self.title_mode is TitleMatchMode.CONTAINS:
                ahk_call("SetTitleMatchMode", 2)
            elif self.title_mode is TitleMatchMode.EXACT:
                ahk_call("SetTitleMatchMode", 3)
            elif self.title_mode is TitleMatchMode.REGEX:
                ahk_call("SetTitleMatchMode", "regex")
            else:
                raise ValueError(f"unknown title match mode: {self.title_mode!r}")

            if self.text_mode is TextMatchMode.FAST or self.text_mode is UNSET:
                ahk_call("SetTitleMatchMode", "fast")
            elif self.text_mode is TextMatchMode.SLOW:
                ahk_call("SetTitleMatchMode", "slow")
            else:
                raise ValueError(f"unknown text match mode: {self.text_mode!r}")

            if set_delay:
                ahk_call("SetWinDelay", optional_ms(get_settings().win_delay))

            return ahk_call(cmd, *args)

    def _query(self):
        return (*self._include(), *self._exclude())

    def _include(self):
        parts = []
        if self.title is not UNSET:
            parts.append(str(self.title))
        if self.class_name is not UNSET:
            parts.append(f"ahk_class {self.class_name}")
        if self.id is not UNSET:
            parts.append(f"ahk_id {self.id}")
        if self.pid is not UNSET:
            parts.append(f"ahk_pid {self.pid}")
        if self.exe is not UNSET:
            parts.append(f"ahk_exe {self.exe}")

        return (
            " ".join(parts),
            default(str, self.text, "", none=UNSET),
        )

    def _exclude(self):
        return (
            default(str, self.exclude_title, "", none=UNSET),
            default(str, self.exclude_text, "", none=UNSET),
        )


windows = visible_windows = Windows()
all_windows = Windows(exclude_hidden_windows=False)


@dc.dataclass(frozen=True)
class _Window:
    # I'd like the Window and Control classes to be hashable, and making the
    # dataclass frozen also makes it hashable. However, frozen dataclasses
    # cannot have setter properties unless it's a subclass.

    id: int

    def __bool__(self):
        return self.id != 0

    def _call(self, cmd, *args, exclude_hidden_windows=False, set_delay=True):
        # Call the command only if the window was found previously. This makes
        # optional chaining possible. For example,
        # `ahk.windows.first(class_name="Notepad").close()` doesn't error out
        # when there are no Notepad windows.
        if self.id == 0:
            return
        with global_ahk_lock:
            if exclude_hidden_windows:
                ahk_call("DetectHiddenWindows", "Off")
            else:
                ahk_call("DetectHiddenWindows", "On")
            if set_delay:
                ahk_call("SetWinDelay", optional_ms(get_settings().win_delay))
            return ahk_call(cmd, *args)

    def _include(self):
        win_text = ""
        return f"ahk_id {self.id}", win_text


class Window(_Window):
    @property
    def rect(self):
        result = self._call("WinGetPos", *self._include())
        if result is not None:
            x, y, width, height = result["X"], result["Y"], result["Width"], result["Height"]
        else:
            x, y, width, height = None, None, None, None
        return (
            x if x != "" else None,
            y if y != "" else None,
            width if width != "" else None,
            height if height != "" else None,
        )

    @rect.setter
    def rect(self, new_rect):
        x, y, width, height = new_rect
        self.move(x, y, width, height)

    @property
    def position(self):
        x, y, _, _ = self.rect
        return x, y

    @position.setter
    def position(self, new_position):
        x, y = new_position
        self.move(x, y)

    @property
    def x(self):
        x, _, _, _ = self.rect
        return x

    @x.setter
    def x(self, new_x):
        self.move(x=new_x)

    @property
    def y(self):
        _, y, _, _ = self.rect
        return y

    @y.setter
    def y(self, new_y):
        self.move(y=new_y)

    @property
    def width(self):
        _, _, width, _ = self.rect
        return width

    @width.setter
    def width(self, new_width):
        self.move(width=new_width)

    @property
    def height(self):
        _, _, _, height = self.rect
        return height

    @height.setter
    def height(self, new_height):
        self.move(height=new_height)

    def move(self, x=None, y=None, width=None, height=None):
        self._call(
            "WinMove",
            *self._include(),
            default(int, x, ""),
            default(int, y, ""),
            default(int, width, ""),
            default(int, height, ""),
            set_delay=True,
        )

    @property
    def is_active(self):
        return bool(self._call("WinActive", *self._include()))

    @property
    def exists(self):
        return bool(self._call("WinExist", *self._include()))

    @property
    def class_name(self):
        class_name = self._call("WinGetClass", *self._include())
        if class_name != "":
            # Windows API doesn't allow the class name to be an empty string. If
            # the window doesn't exist or there was a problem getting the class
            # name, AHK returns an empty string.
            return class_name

    @property
    def text(self):
        try:
            return self._call("WinGetText", *self._include())
        except Error as err:
            # If target window doesn't exist or there was a problem getting the
            # text, AHK raises an error.
            if err.message == 1:
                return None
            raise

    @property
    def title(self):
        title = self._call("WinGetTitle", *self._include())
        # If the window doesn't exist, AHK returns an empty string. Check that
        # the window exists.
        if self.exists:
            return title

    @title.setter
    def title(self, new_title):
        return self._call("WinSetTitle", *self._include(), str(new_title))

    @property
    def pid(self):
        return self._get("PID")

    @property
    def process_name(self):
        return self._get("ProcessName")

    @property
    def process_path(self):
        return self._get("ProcessPath")

    @property
    def is_minimized(self):
        min_max = self._get("MinMax")
        if min_max is not None:
            return min_max == -1

    @is_minimized.setter
    def is_minimized(self, value):
        if value:
            self.minimize()
        else:
            self.restore()

    def toggle_minimized(self):
        is_minimized = self.is_minimized
        if is_minimized is not None:
            self.is_minimized = not is_minimized

    @property
    def is_restored(self):
        min_max = self._get("MinMax")
        if min_max is not None:
            return min_max == 0

    @property
    def is_maximized(self):
        min_max = self._get("MinMax")
        if min_max is not None:
            return min_max == 1

    @is_maximized.setter
    def is_maximized(self, value):
        if value:
            self.maximize()
        else:
            self.restore()

    def toggle_maximized(self):
        is_maximized = self.is_maximized
        if is_maximized is not None:
            self.is_maximized = not is_maximized

    # TODO: Add control methods to Windows

    def control_class_names(self):
        # XXX: Should the method be a property?
        names = self._get("ControlList")
        if names is not None:
            return names.splitlines()

    def controls(self):
        # XXX: Should the method be a property?
        handles = self._get("ControlListHwnd")
        if handles is None:
            return None
        hwnds = handles.splitlines()
        return [
            Control(int(hwnd, base=16))
            for hwnd in hwnds
        ]

    def get_control(self, class_name):
        if not self.exists:
            return None
        try:
            control_id = self._call("ControlGet", "Hwnd", "", class_name, *self._include())
            return Control(control_id)
        except Error as err:
            if err.message == 1:
                # Control doesn't exist.
                return None
            raise

    @property
    def always_on_top(self):
        if self.ex_style is not None:
            return ExWindowStyle.TOPMOST in self.ex_style

    @always_on_top.setter
    def always_on_top(self, value):
        if value:
            self.pin_to_top()
        else:
            self.unpin_from_top()

    def pin_to_top(self):
        self._set("AlwaysOnTop", "On")

    def unpin_from_top(self):
        self._set("AlwaysOnTop", "Off")

    def toggle_always_on_top(self):
        self._set("AlwaysOnTop", "Toggle")

    def send_to_bottom(self):
        self._set("Bottom")

    def bring_to_top(self):
        self._set("Top")

    def disable(self):
        self._set("Disable")

    def enable(self):
        self._set("Enable")

    @property
    def is_enabled(self):
        style = self.style
        if style is not None:
            return WindowStyle.DISABLED not in style

    @is_enabled.setter
    def is_enabled(self, value):
        if value:
            self.enable()
        else:
            self.disable()

    def redraw(self):
        self._set("Redraw")

    def set_region(self, options):
        # TODO: Implement better options.
        self._set("Region", options)

    def reset_region(self):
        self._set("Region", "")

    @property
    def style(self):
        style = self._get("Style")
        if style is not None:
            return WindowStyle(style)

    @style.setter
    def style(self, value):
        self._set("Style", int(value))

    @property
    def ex_style(self):
        ex_style = self._get("ExStyle")
        if ex_style is not None:
            return ExWindowStyle(ex_style)

    @ex_style.setter
    def ex_style(self, value):
        self._set("ExStyle", int(value))

    @property
    def opacity(self):
        return self._get("Transparent")

    @opacity.setter
    def opacity(self, value):
        if value is None:
            ahk_value = "Off"
        elif not 0 <= value <= 255:
            raise ValueError("opacity value must be between 0 and 255")
        else:
            ahk_value = int(value)
        self._set("Transparent", ahk_value)

    @property
    def transparent_color(self):
        result = self._get("TransColor")
        if result is not None:
            hex_color = hex(result)[2:]
            return colors.to_tuple(hex_color)

    @transparent_color.setter
    def transparent_color(self, value):
        if value is None:
            ahk_value = "Off"
        else:
            r, g, b = value
            ahk_value = colors.to_hex(r, g, b)
        self._set("TransColor", ahk_value)

    def hide(self):
        self._call("WinHide", *self._include(), set_delay=True)

    def show(self):
        self._call("WinShow", *self._include(), set_delay=True)

    @property
    def is_visible(self):
        style = self.style
        if style is not None:
            return WindowStyle.VISIBLE in style

    @is_visible.setter
    def is_visible(self, value):
        if value:
            self.show()
        else:
            self.hide()

    def activate(self, timeout=None):
        self._call("WinActivate", *self._include())
        if timeout is not None:
            return self.wait_active(timeout=timeout)

    def get_status_bar_text(self, part=1):
        if not self._status_bar_exists():
            return None
        try:
            return self._call("StatusBarGetText", int(part), *self._include())
        except Error as err:
            if err.message == 1:
                err.message = "status bar cannot be accessed"
            raise

    def wait_status_bar(self, bar_text="", timeout=None, part=1, interval=0.05):
        if not self._status_bar_exists():
            return None
        try:
            timed_out = self._call(
                "StatusBarWait",
                bar_text,
                default(timeout, ""),
                part,
                *self._include(),
                interval * 1000,
            )
            return not timed_out
        except Error as err:
            if err.message == 2:
                err.message = "status bar cannot be accessed"
            raise

    def _status_bar_exists(self):
        status_bar = self.get_control("msctls_statusbar321")
        return status_bar is not None

    def close(self, timeout=None):
        self._call("WinClose", *self._include(), timeout, set_delay=True)
        if timeout is not None:
            # TODO: Test timeout.
            return not self.exists

    def kill(self, timeout=None):
        self._call("WinKill", *self._include(), timeout, set_delay=True)
        if timeout is not None:
            # TODO: Test timeout.
            return not self.exists

    def maximize(self):
        self._call("WinMaximize", *self._include(), set_delay=True)

    def minimize(self):
        self._call("WinMinimize", *self._include(), set_delay=True)

    def restore(self):
        self._call("WinRestore", *self._include(), set_delay=True)

    def wait_active(self, timeout=None):
        timed_out = self._call("WinWaitActive", *self._include(), timeout, set_delay=True)
        if timed_out is None:
            return False
        return not timed_out

    def wait_inactive(self, timeout=None):
        timed_out = self._call("WinWaitNotActive", *self._include(), timeout, set_delay=True)
        if timed_out is None:
            return True
        return not timed_out

    def wait_hidden(self, timeout=None):
        timed_out = self._call("WinWaitClose", *self._include(), timeout, exclude_hidden_windows=True, set_delay=True)
        if timed_out is None:
            return True
        return not timed_out

    def wait_close(self, timeout=None):
        timed_out = self._call("WinWaitClose", *self._include(), timeout, set_delay=True)
        if timed_out is None:
            return True
        return not timed_out

    def send(self, keys):
        with global_ahk_lock:
            hotkeys._set_key_delay()
            control = ""
            self._call("ControlSend", control, str(keys), *self._include())

    def send_message(self, msg, w_param, l_param, timeout=5):
        control = exclude_title = exclude_text = ""
        try:
            result = self._call(
                "SendMessage", int(msg), int(w_param), int(l_param), control,
                *self._include(), exclude_title, exclude_text,
                int(timeout * 1000),
            )
        except Error:
            raise RuntimeError("there was a problem sending message or response timed out") from None
        return result

    def post_message(self, msg, w_param, l_param):
        control = ""
        err = self._call("PostMessage", int(msg), int(w_param), int(l_param), control, *self._include())
        return not err

    def _get(self, subcmd):
        result = self._call("WinGet", subcmd, *self._include())
        if result != "":
            return result

    def _set(self, subcmd, value=""):
        return self._call("WinSet", subcmd, value, *self._include())


class Control(_Window):
    @property
    def text(self):
        return self._call("ControlGetText", "", *self._include())

    @text.setter
    def text(self, value):
        return self._call("ControlSetText", "", value, *self._include())

    def _get(self, subcmd, value=""):
        result = self._call("ControlGet", subcmd, value, "", *self._include())
        if result != "":
            return result


class WindowStyle(enum.IntFlag):
    BORDER = 0x00800000
    CAPTION = 0x00C00000
    CHILD = 0x40000000
    CHILDWINDOW = 0x40000000
    CLIPCHILDREN = 0x02000000
    CLIPSIBLINGS = 0x04000000
    DISABLED = 0x08000000
    DLGFRAME = 0x00400000
    GROUP = 0x00020000
    HSCROLL = 0x00100000
    ICONIC = 0x20000000
    MAXIMIZE = 0x01000000
    MAXIMIZEBOX = 0x00010000
    MINIMIZE = 0x20000000
    MINIMIZEBOX = 0x00020000
    OVERLAPPED = 0x00000000
    POPUP = 0x80000000
    SIZEBOX = 0x00040000
    SYSMENU = 0x00080000
    TABSTOP = 0x00010000
    THICKFRAME = 0x00040000
    TILED = 0x00000000
    VISIBLE = 0x10000000
    VSCROLL = 0x00200000
    OVERLAPPEDWINDOW = (OVERLAPPED | CAPTION | SYSMENU | THICKFRAME | MINIMIZEBOX | MAXIMIZEBOX)
    POPUPWINDOW = (POPUP | BORDER | SYSMENU)
    TILEDWINDOW = (OVERLAPPED | CAPTION | SYSMENU | THICKFRAME | MINIMIZEBOX | MAXIMIZEBOX)


class ExWindowStyle(enum.IntFlag):
    ACCEPTFILES = 0x00000010
    APPWINDOW = 0x00040000
    CLIENTEDGE = 0x00000200
    COMPOSITED = 0x02000000
    CONTEXTHELP = 0x00000400
    CONTROLPARENT = 0x00010000
    DLGMODALFRAME = 0x00000001
    LAYERED = 0x00080000
    LAYOUTRTL = 0x00400000
    LEFT = 0x00000000
    LEFTSCROLLBAR = 0x00004000
    LTRREADING = 0x00000000
    MDICHILD = 0x00000040
    NOACTIVATE = 0x08000000
    NOINHERITLAYOUT = 0x00100000
    NOPARENTNOTIFY = 0x00000004
    NOREDIRECTIONBITMAP = 0x00200000
    RIGHT = 0x00001000
    RIGHTSCROLLBAR = 0x00000000
    RTLREADING = 0x00002000
    STATICEDGE = 0x00020000
    TOOLWINDOW = 0x00000080
    TOPMOST = 0x00000008
    TRANSPARENT = 0x00000020
    WINDOWEDGE = 0x00000100
    OVERLAPPEDWINDOW = (WINDOWEDGE | CLIENTEDGE)
    PALETTEWINDOW = (WINDOWEDGE | TOOLWINDOW | TOPMOST)
