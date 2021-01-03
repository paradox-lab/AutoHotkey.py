import dataclasses as dc
import functools
from typing import Callable

from .flow import ahk_call, _wrap_callback

__all__ = [
    "ClipboardHandler",
    "get_clipboard",
    "on_clipboard_change",
    "set_clipboard",
    "wait_clipboard",
]


def get_clipboard() -> str:
    """Get text from the Windows clipboard.

    :command: `Clipboard
       <https://www.autohotkey.com/docs/misc/Clipboard.htm>`_
    """
    return ahk_call("GetVar", "Clipboard")


def set_clipboard(value):
    """Put text into the Windows clipboard.

    :command: `Clipboard = Value
       <https://www.autohotkey.com/docs/misc/Clipboard.htm>`_
    """
    return ahk_call("SetVar", "Clipboard", str(value))


def wait_clipboard(timeout: float = None) -> str:
    """Wait until the clipboard contains text and return it.

    If there is no text in the clipboard after *timeout* seconds, then an empty
    string will be returned. If *timeout* is not specified or ``None``, there is
    no limit to the wait time. Specifying 0 is the same as specifying 0.5.

    :command: `ClipWait
       <https://www.autohotkey.com/docs/commands/ClipWait.htm>`_
    """
    # TODO: Implement WaitForAnyData argument.
    if timeout is not None:
        timeout = float(timeout)
    ok = ahk_call("ClipWait", timeout)
    if not ok:
        return ""
    return get_clipboard()


def on_clipboard_change(func: Callable = None, *args, prepend_handler=False):
    """Register *func* to be called on clipboard change.

    On clipboard change, *func* will be called with the clipboard text as the
    *clipboard* argument.

    The optional positional *args* will be passed to the *func* when it is
    called. If you want the callback to be called with keyword arguments use
    :func:`functools.partial`.

    If the optional *prepend_handler* argument is set to ``True``, the *func*
    will be registered to be called before any other previously registered
    functions.

    If *func* is given, returns an instance of :class:`ClipboardHandler`.
    Otherwise, the function works as a decorator::

        @ahkpy.on_clipboard_change()
        def handler(clipboard):
            print(clipboard.upper())

        assert isinstance(handler, ahkpy.ClipboardHandler)

    :command: `OnClipboardChange
       <https://www.autohotkey.com/docs/commands/OnClipboardChange.htm>`_
    """
    option = 1 if not prepend_handler else -1

    def on_clipboard_change_decorator(func):
        func = _wrap_callback(
            functools.partial(func, *args),
            ("clipboard",),
            _bare_clipboard_handler,
            _clipboard_handler,
        )
        ahk_call("OnClipboardChange", func, option)
        return ClipboardHandler(func)

    if func is None:
        return on_clipboard_change_decorator
    return on_clipboard_change_decorator(func)


def _bare_clipboard_handler(func, *_):
    return bool(func())


def _clipboard_handler(func, typ):
    # TODO: Document returning a truthy object.
    if typ == 0:
        return bool(func(clipboard=""))
    elif typ == 1:
        return bool(func(clipboard=get_clipboard()))
    elif typ == 2:
        # TODO: Return ClipboardAll.
        return bool(func(clipboard=get_clipboard()))


@dc.dataclass(frozen=True)
class ClipboardHandler:
    """This immutable object holds a function registered to be called on
    clipboard change.

    Creating an instance of :class:`!ClipboardHandler` doesn't register the
    function as a handler. Use the :func:`on_clipboard_change` function instead.
    """

    func: Callable
    __slots__ = ("func",)

    def unregister(self):
        """Unregister the clipboard handler and stop calling the function on
        clipboard change.
        """
        ahk_call("OnClipboardChange", self.func, 0)


# TODO: Implement ClipboardAll.
