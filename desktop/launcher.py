"""Desktop application launcher coordinating backend, security, and pywebview."""

from __future__ import annotations

import atexit
import json
import logging
import secrets
import signal
import sys
from contextlib import suppress
from typing import Any

import webview

from app import create_app
from app.config import APP_NAME
from app.migrations.runner import initialize_database
from app.services import settings_service
from app.utils.errors import DatabaseError
from desktop.lifecycle import (
    SingleInstanceGuard,
    StartupError,
    allocate_loopback_port,
    focus_existing_instance,
    show_native_alert,
    start_waitress_server,
    stop_waitress_server,
    wait_for_server_ready,
)
from desktop.menus import (
    apply_native_appearance,
    bind_native_shortcuts,
    build_native_menus,
    configure_macos_app_identity,
    initial_window_bg_hex,
)
from desktop.paths import (
    AssetMissingError,
    get_data_dir,
    get_db_path,
    get_icon_path,
    get_lock_path,
    verify_bundled_assets,
)

logger = logging.getLogger("finora.desktop")


def deliver_launch_token(window: webview.Window, *, token: str, expected_origin: str) -> bool:
    """Deliver ephemeral API token via CSP-safe WKWebView run_js without eval()."""
    current_url = window.get_current_url() or ""
    if not current_url.startswith(expected_origin):
        return False
    encoded_token = json.dumps(token)
    script = (
        "(function(t){"
        "if(typeof window.__finoraSetAuth==='function'){window.__finoraSetAuth(t);}"
        "else{window.__finoraPendingAuth=t;}"
        f"}})({encoded_token});"
    )
    window.run_js(script)
    return True


def _configure_webview_security() -> None:
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    webview.settings["SHOW_DEFAULT_MENUS"] = True


def launch_desktop() -> int:
    """Boot Finora cleanly as a native macOS desktop window."""
    _configure_webview_security()
    configure_macos_app_identity(APP_NAME)

    lock_guard: SingleInstanceGuard | None = None
    server: Any = None
    server_thread = None

    def _cleanup() -> None:
        nonlocal server, server_thread, lock_guard
        if server is not None:
            stop_waitress_server(server, server_thread)
            server = None
            server_thread = None
        if lock_guard is not None:
            lock_guard.release()
            lock_guard = None

    try:
        bundle_root = verify_bundled_assets()
        data_dir = get_data_dir()
        db_path = get_db_path(data_dir)
        lock_guard = SingleInstanceGuard(get_lock_path(data_dir))

        if not lock_guard.acquire():
            focused = focus_existing_instance()
            if not focused:
                show_native_alert(
                    "Finora Is Already Open",
                    "Another Finora window is already running using this local workspace.",
                    critical=False,
                )
            return 0

        migrations_dir = bundle_root / "app" / "migrations" / "sql"
        initialize_database(db_path, migrations_dir=migrations_dir)
        initial_appearance = settings_service.get_appearance(db_path)

        port = allocate_loopback_port()
        base_url = f"http://127.0.0.1:{port}"
        expected_origin = f"{base_url}/"
        api_token = secrets.token_urlsafe(32)

        window_holder: dict[str, webview.Window] = {}

        def _on_appearance_changed(new_appearance: str) -> None:
            apply_native_appearance(window_holder.get("main"), new_appearance)

        flask_app = create_app(
            data_dir=data_dir,
            db_path=db_path,
            api_token=api_token,
            server_port=port,
            testing=False,
            initialize_db=False,
            appearance_callback=_on_appearance_changed,
        )

        server, server_thread = start_waitress_server(flask_app, port=port)
        wait_for_server_ready(port, timeout_seconds=5.0)

        atexit.register(_cleanup)

        window = webview.create_window(
            APP_NAME,
            url=expected_origin,
            width=1200,
            height=780,
            min_size=(900, 600),
            resizable=True,
            background_color=initial_window_bg_hex(initial_appearance),
        )
        window_holder["main"] = window

        def _handle_sigterm(*_args: Any) -> None:
            with suppress(Exception):
                window.destroy()

        signal.signal(signal.SIGTERM, _handle_sigterm)

        def _guard_navigation() -> bool:
            current = window.get_current_url() or ""
            if current and not current.startswith(expected_origin) and current != "about:blank":
                window.load_url(expected_origin)
                return False
            return True

        def _trigger_new_tx() -> None:
            window.run_js("window.dispatchEvent(new CustomEvent('finora:new-transaction'));")

        def _on_loaded() -> None:
            if _guard_navigation():
                deliver_launch_token(window, token=api_token, expected_origin=expected_origin)
            apply_native_appearance(window, settings_service.get_appearance(db_path))

        window.events.loaded += _on_loaded
        window.events.closed += _cleanup

        def _on_gui_start() -> None:
            bind_native_shortcuts()
            apply_native_appearance(window, initial_appearance)

        icon_path = get_icon_path()
        webview.start(
            _on_gui_start,
            debug=False,
            private_mode=True,
            menu=build_native_menus(_trigger_new_tx),
            icon=str(icon_path) if icon_path is not None else None,
        )
        return 0

    except (AssetMissingError, DatabaseError, StartupError) as exc:
        title = getattr(exc, "title", "Unable to Launch Finora")
        show_native_alert(title, str(exc), critical=True)
        return 1
    except Exception as exc:
        logger.exception("Unexpected desktop launch error: %s", type(exc).__name__)
        show_native_alert(
            "Finora Could Not Start",
            "An unexpected startup error occurred while initializing the desktop workspace.",
            critical=True,
        )
        return 1
    finally:
        _cleanup()


def main() -> None:
    """Entry point for Finora desktop execution."""
    sys.exit(launch_desktop())
