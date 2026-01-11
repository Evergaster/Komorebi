#!/usr/bin/env python3
import sys
import argparse
import time
import os
import traceback

import setproctitle
from PySide6.QtGui import QIcon

setproctitle.setproctitle("komorebi")
os.environ.setdefault("QT_DESKTOP_FILE_NAME", "komorebi")

SINGLE_INSTANCE_SERVER_NAME = "komorebi_gui_single_instance"


def _notify_existing_instance() -> bool:
    """Devuelve True si ya existe una instancia y se notificó."""
    try:
        from PySide6.QtNetwork import QLocalSocket

        sock = QLocalSocket()
        sock.connectToServer(SINGLE_INSTANCE_SERVER_NAME)
        if not sock.waitForConnected(150):
            return False
        sock.write(b"show\n")
        sock.flush()
        sock.waitForBytesWritten(150)
        sock.disconnectFromServer()
        return True
    except Exception:
        return False


def _start_single_instance_server(on_message):
    """Inicia servidor local para single-instance."""
    try:
        from PySide6.QtNetwork import QLocalServer

        try:
            QLocalServer.removeServer(SINGLE_INSTANCE_SERVER_NAME)
        except Exception:
            pass

        server = QLocalServer()
        if not server.listen(SINGLE_INSTANCE_SERVER_NAME):
            return None

        def _handle_new_connection():
            sock = server.nextPendingConnection()
            if sock is None:
                return

            def _read_and_dispatch():
                try:
                    data = bytes(sock.readAll()).decode("utf-8", errors="ignore").strip()
                    if data:
                        on_message(data)
                finally:
                    sock.disconnectFromServer()

            sock.readyRead.connect(_read_and_dispatch)
            sock.disconnected.connect(sock.deleteLater)

        server.newConnection.connect(_handle_new_connection)
        return server
    except Exception:
        return None

if __name__ == "__main__":
    if "--background-player" in sys.argv:
        idx = sys.argv.index("--background-player")
        bg_argv = sys.argv[idx + 1 :]
        from src import background_player
        raise SystemExit(background_player.main(bg_argv))

    # Solo aplica a la GUI (QtMultimedia). El proceso de fondo usa libVLC.
    os.environ["QT_MEDIA_BACKEND"] = "gstreamer"

    parser = argparse.ArgumentParser()
    parser.add_argument("--restore-only", action="store_true")
    parser.add_argument("--delay", type=int, default=0)
    args = parser.parse_args()

    if args.delay:
        time.sleep(args.delay)

    if _notify_existing_instance():
        raise SystemExit(0)

    from PySide6.QtWidgets import QApplication
    from src.gui import MainWindow

    app = QApplication(sys.argv)
    
    app.setApplicationName("Komorebi")
    app.setApplicationDisplayName("Komorebi")
    app.setDesktopFileName("komorebi")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(script_dir, "icons", "Komorebi.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    app.setStyle("Fusion")

    window = MainWindow()

    def _on_single_instance_message(msg: str) -> None:
        m = (msg or "").strip().lower()
        if m == "show":
            window.show()
            window.showNormal()
            window.raise_()
            window.activateWindow()

    _single_instance_server = _start_single_instance_server(_on_single_instance_message)

    try:
        if args.restore_only:
            sys.exit(app.exec())
        else:
            window.show()
            sys.exit(app.exec())
    except Exception:
        try:
            log_path = os.path.expanduser("/tmp/komorebi_startup_error.log")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
                f.write("\n")
        finally:
            raise