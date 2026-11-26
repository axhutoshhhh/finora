"""Desktop startup, single-instance locking, server readiness, and shutdown."""

from __future__ import annotations

import fcntl
import http.client
import os
import socket
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from flask import Flask
from waitress import create_server

from app.config import BUNDLE_IDENTIFIER
from app.database import ensure_secure_data_dir


class StartupError(RuntimeError):
    """Startup failure with user-facing title and actionable message."""

    def __init__(self, title: str, message: str) -> None:
        super().__init__(message)
        self.title = title
        self.message = message


class SingleInstanceGuard:
    """Non-blocking file lock preventing duplicate simultaneous Finora instances."""

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._fd: int | None = None

    def acquire(self) -> bool:
        """Attempt to acquire exclusive instance lock; returns False if already running."""
        ensure_secure_data_dir(self._lock_path.parent)
        fd = os.open(os.fspath(self._lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        except OSError:
            os.close(fd)
            raise

        self._fd = fd
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("ascii"))
        return True

    def release(self) -> None:
        """Release and close the lock descriptor cleanly."""
        if self._fd is not None:
            with suppress(OSError):
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            with suppress(OSError):
                os.close(self._fd)
            self._fd = None


def focus_existing_instance() -> bool:
    """Attempt to bring an already-running Finora macOS bundle window to the front."""
    if sys.platform != "darwin":
        return False
    try:
        import AppKit

        running = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(
            BUNDLE_IDENTIFIER
        )
        for app_proc in running:
            if int(app_proc.processIdentifier()) != os.getpid():
                app_proc.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
                return True
    except Exception:
        return False
    return False


def allocate_loopback_port() -> int:
    """Reserve an available ephemeral TCP port on 127.0.0.1."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
    except OSError as exc:
        raise StartupError(
            "Unable to Start Local Server",
            "Finora could not allocate a local loopback port on 127.0.0.1.",
        ) from exc


def start_waitress_server(app: Flask, *, port: int) -> tuple[Any, threading.Thread]:
    """Start Waitress WSGI server strictly on 127.0.0.1 in a daemon thread."""
    try:
        server = create_server(app, host="127.0.0.1", port=port, threads=8)
    except OSError as exc:
        raise StartupError(
            "Local Port Unavailable",
            f"Finora could not bind to local port {port}. Please close conflicting processes and retry.",
        ) from exc

    thread = threading.Thread(
        target=server.run,
        name="finora-local-wsgi",
        daemon=True,
    )
    thread.start()
    return server, thread


def wait_for_server_ready(port: int, *, timeout_seconds: float = 5.0) -> None:
    """Poll GET /health on 127.0.0.1 until ready or raise StartupError on timeout."""
    deadline = time.monotonic() + timeout_seconds
    host_header = f"127.0.0.1:{port}"
    while time.monotonic() < deadline:
        conn: http.client.HTTPConnection | None = None
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.4)
            conn.request("GET", "/health", headers={"Host": host_header})
            resp = conn.getresponse()
            resp.read()
            if resp.status == 200:
                return
        except OSError:
            time.sleep(0.03)
        finally:
            if conn is not None:
                conn.close()

    raise StartupError(
        "Finora Server Timed Out",
        "The local Finora backend did not become ready in time. Please relaunch Finora.",
    )


def stop_waitress_server(server: Any, thread: threading.Thread | None) -> None:
    """Shut down Waitress cleanly inside its asyncore event loop without orphaned sockets."""
    if server is None:
        return

    def _shutdown() -> None:
        with suppress(Exception):
            server.task_dispatcher.shutdown()
        for channel in list(server._map.values()):
            with suppress(Exception):
                channel.close()
        with suppress(Exception):
            server.close()

    try:
        server.trigger.pull_trigger(_shutdown)
    except Exception:
        with suppress(Exception):
            server.close()

    if thread is not None and thread.is_alive():
        thread.join(timeout=2.5)


def show_native_alert(title: str, message: str, *, critical: bool = True) -> None:
    """Display a native macOS dialog for startup/lifecycle failures."""
    if sys.platform != "darwin":
        print(f"{title}: {message}", file=sys.stderr)
        return
    try:
        import AppKit

        app = AppKit.NSApplication.sharedApplication()
        app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
        app.activateIgnoringOtherApps_(True)
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        if critical:
            alert.setAlertStyle_(AppKit.NSAlertStyleCritical)
        else:
            alert.setAlertStyle_(AppKit.NSAlertStyleInformational)
        alert.addButtonWithTitle_("OK")
        alert.runModal()
    except Exception:
        print(f"{title}: {message}", file=sys.stderr)
