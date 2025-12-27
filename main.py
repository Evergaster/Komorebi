#!/usr/bin/env python3
import sys
import argparse
import time
import os
import traceback

# Nota: No importes módulos pesados (Qt/BackgroundPlayer) antes de decidir
# el modo de ejecución; esto evita side-effects (env vars) en el modo GUI.

os.environ["QT_MEDIA_BACKEND"] = "gstreamer"  # Por si queda algún fallback


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
    """Inicia servidor local para single-instance.

    `on_message(str)` se invoca al recibir una orden (p.ej. 'show').
    """
    try:
        from PySide6.QtNetwork import QLocalServer

        # Limpiar socket stale de una instancia anterior que crasheó.
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
    # Modo servicio: permite que el ejecutable PyInstaller se reinvoque a sí mismo.
    # Engine usa: <exe> --background-player <args-de-background_player>
    if "--background-player" in sys.argv:
        idx = sys.argv.index("--background-player")
        bg_argv = sys.argv[idx + 1 :]
        from src import background_player

        raise SystemExit(background_player.main(bg_argv))

    parser = argparse.ArgumentParser()
    parser.add_argument("--restore-only", action="store_true")
    parser.add_argument("--delay", type=int, default=0)
    args = parser.parse_args()

    if args.delay:
        time.sleep(args.delay)

    # Si se lanza desde el .desktop y ya hay una instancia corriendo,
    # reutilizarla (traer ventana al frente) en vez de abrir otra.
    if _notify_existing_instance():
        raise SystemExit(0)

    from PySide6.QtWidgets import QApplication
    from src.gui import MainWindow

    app = QApplication(sys.argv)
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
    #window.restore_wallpapers()  # Implementar si guardas estado

    try:
        if args.restore_only:
            sys.exit(app.exec())
        else:
            window.show()
            sys.exit(app.exec())
    except Exception:
        # Log de arranque: útil si la app falla al ejecutarse desde el .deb
        try:
            log_path = os.path.expanduser("/tmp/komorebi_startup_error.log")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
                f.write("\n")
        finally:
            raise