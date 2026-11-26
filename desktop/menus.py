"""Native macOS menu bar, keyboard accelerators, and NSWindow appearance syncing."""

from __future__ import annotations

import sys
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from webview.menu import Menu, MenuAction

from app.config import APP_NAME


def configure_macos_app_identity(app_name: str = APP_NAME) -> None:
    """Ensure the Cocoa menu bar displays Finora when launched directly via Python."""
    if sys.platform != "darwin":
        return
    with suppress(Exception):
        import Foundation

        bundle = Foundation.NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info is not None and "CFBundleName" in info:
            info["CFBundleName"] = app_name


def detect_macos_dark_mode() -> bool:
    """Read current macOS AppleInterfaceStyle to avoid initial flash on System mode."""
    if sys.platform != "darwin":
        return False
    try:
        import Foundation

        defaults = Foundation.NSUserDefaults.standardUserDefaults()
        style = defaults.stringForKey_("AppleInterfaceStyle")
        return str(style).lower() == "dark"
    except Exception:
        return False


def initial_window_bg_hex(appearance: str) -> str:
    """Return initial WebView background color matching theme before HTML paints."""
    if appearance == "dark":
        return "#151716"
    if appearance == "light":
        return "#F7F7F4"
    return "#151716" if detect_macos_dark_mode() else "#F7F7F4"


def apply_native_appearance(window: Any, appearance: str) -> None:
    """Synchronize NSWindow and NSApplication appearance ('system', 'light', 'dark')."""
    if sys.platform != "darwin" or window is None:
        return
    with suppress(Exception):
        import AppKit
        from PyObjCTools import AppHelper

        def _update() -> None:
            ns_window = getattr(window, "native", None)
            if ns_window is None:
                return
            if appearance == "dark":
                ns_app = AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua)
            elif appearance == "light":
                ns_app = AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameAqua)
            else:
                ns_app = None
            ns_window.setAppearance_(ns_app)

        AppHelper.callAfter(_update)


def build_native_menus(on_new_transaction: Callable[[], None]) -> list[Menu]:
    """Define Finora's macOS File menu items cleanly integrated with pywebview."""
    return [
        Menu(
            "File",
            [
                MenuAction("New Transaction", on_new_transaction),
            ],
        )
    ]


def bind_native_shortcuts() -> None:
    """Attach Cmd+N shortcut to File -> New Transaction after Cocoa builds menus."""
    if sys.platform != "darwin":
        return
    with suppress(Exception):
        import AppKit
        from PyObjCTools import AppHelper

        def _attach() -> None:
            main_menu = AppKit.NSApp.mainMenu()
            if main_menu is None:
                return
            file_item = main_menu.itemWithTitle_("File")
            if file_item is None or file_item.submenu() is None:
                return
            new_tx_item = file_item.submenu().itemWithTitle_("New Transaction")
            if new_tx_item is not None:
                new_tx_item.setKeyEquivalent_("n")
                new_tx_item.setKeyEquivalentModifierMask_(AppKit.NSEventModifierFlagCommand)

        AppHelper.callAfter(_attach)
