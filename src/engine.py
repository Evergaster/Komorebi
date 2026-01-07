"""
Engine de Wallpaper - Versión simplificada estilo Hidamari
Soporta Wayland y X11. Lanza un proceso de fondo sin barra ni icono.
"""
import os
import sys
import subprocess
import json
import hashlib
from pathlib import Path
from datetime import datetime
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QLocalSocket

PID_DIR = Path("/tmp/komorebi_pids")
LOG_FILE = Path("/tmp/komorebi_wall.log")
THUMB_DIR = Path.home() / ".cache" / "komorebi" / "thumbnails"
ROOT_DIR = Path(__file__).parent.parent.absolute()

# Debe coincidir con SERVER_NAME en src/background_player.py
WALLPAPER_SERVER_NAME = "komorebi_wallpaper_service"

class WallpaperEngine:
    """Motor de reproducción de wallpapers animados"""
    
    def __init__(self):
        self.current_videos = {} # {screen_index: video_path}
        PID_DIR.mkdir(parents=True, exist_ok=True)
        THUMB_DIR.mkdir(parents=True, exist_ok=True)

        self.session = os.environ.get('XDG_SESSION_TYPE', 'x11').lower()
        self.is_gnome = 'GNOME' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper()
        
        session_type = "Wayland" if self.session == "wayland" else "X11"
        desktop = "GNOME" if self.is_gnome else os.environ.get('XDG_CURRENT_DESKTOP', 'Desconocido')
        self._log(f"🖥️ Iniciando en {desktop} ({session_type})")


    def get_screen_count(self):
        """Retorna el número de pantallas detectadas"""
        if not QGuiApplication.instance():
            return 1
        return len(QGuiApplication.screens())

    def _log(self, msg):
        """Log con timestamp"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)
    
    def stop(self, screen_index=None):
        """Detiene la reproducción en una pantalla o en todas"""
        if screen_index is not None:
            self._send_stop_command(screen_index)
            if screen_index in self.current_videos:
                del self.current_videos[screen_index]
        else:
            self._send_quit_command()
            self.current_videos.clear()
    
    def play(self, video_path, screen_index=0, pause_on_max=False, volume=0, paused=False):
        """Reproduce un video como wallpaper en una pantalla específica"""
        self.current_videos[screen_index] = video_path
        self._log(f"▶ Reproduciendo en pantalla {screen_index}: {os.path.basename(video_path)}")

        if screen_index == 0:
            self._set_gnome_background(video_path)
        
        self._start_daemon(video_path, screen_index, pause_on_max, volume, paused)

    def _set_gnome_background(self, video_path: str) -> None:
        """Best-effort: setea un fondo estático en GNOME usando un thumbnail del video.

        Esto evita que `play()` rompa si esta función no existe y mantiene compatibilidad.
        Si falla (no GNOME, no gsettings, no ffmpeg), se ignora silenciosamente.
        """
        if not self.is_gnome:
            return
        try:
            thumb = self.get_thumbnail(video_path)
            if not thumb or not os.path.exists(thumb):
                return
            uri = Path(thumb).resolve().as_uri()
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.background", "picture-uri", uri],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                subprocess.run(
                    ["gsettings", "set", "org.gnome.desktop.background", "picture-uri-dark", uri],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
        except Exception:
            return

    def _background_player_base_cmd(self):
        """Construye el comando base para invocar el servicio de fondo.

        - En modo fuente: usa el intérprete de Python con `-m src.background_player`.
        - En modo PyInstaller (frozen): reinvoca el ejecutable con `--background-player`.
        """
        if getattr(sys, "frozen", False):
            return [sys.executable, "--background-player"]
        return [sys.executable, "-m", "src.background_player"]

    def _start_daemon(self, video_path, screen_index, pause_on_max, volume, paused):
        """Lanza el proceso de fondo (o conecta al existente)"""
        cmd = self._background_player_base_cmd() + [
            video_path,
            "--screen", str(screen_index),
            "--volume", str(volume),
        ]
        
        if pause_on_max:
            cmd.append("--pause-on-max")
        if paused:
            cmd.append("--paused")
            
        subprocess.Popen(
                    cmd, 
                    cwd=str(ROOT_DIR), 
                    start_new_session=True, 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )

    def _send_stop_command(self, screen_index):
        cmd = self._background_player_base_cmd() + [
            "",  # Dummy path
            "--screen", str(screen_index),
            "--stop",
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _send_quit_command(self):
        cmd = self._background_player_base_cmd() + [
            "",  # Dummy path
            "--quit-service",
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        try:
            pattern = "src.background_player" if not getattr(sys, "frozen", False) else "--background-player"
            subprocess.run(["pkill", "-f", pattern], 
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._log(f"Error pkill: {e}")

    def get_thumbnail_path(self, video_path):
        """Retorna la ruta esperada del thumbnail para un video"""
        if not video_path:
            return ""

        h = hashlib.md5(video_path.encode()).hexdigest()
        return str(THUMB_DIR / f"{h}.jpg")

    def get_thumbnail(self, video_path):
        """Genera y retorna la ruta del thumbnail"""
        thumb_path = self.get_thumbnail_path(video_path)
        if not thumb_path:
            return ""
            
        if os.path.exists(thumb_path):
            return thumb_path
            
        try:
            subprocess.run([
                "ffmpeg", "-y", "-ss", "00:00:05", "-i", video_path,
                "-vframes", "1", "-q:v", "2", "-vf", "scale=320:-1",
                thumb_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return thumb_path
        except Exception as e:
            self._log(f"Error generando thumbnail: {e}")
            return ""

    def update_settings(self, config):
        """Actualiza la configuración de los wallpapers activos"""

        try:
            config = config or {}
        except Exception:
            config = {}

        mute = bool(config.get("mute", False))
        base_volume = int(config.get("volume", 50) or 0)
        if mute:
            base_volume = 0

        global_paused = bool(config.get("paused", False)) or bool(config.get("battery_paused", False))
        pause_on_max = bool(config.get("pause_on_max", False))

        monitor_settings = config.get("monitor_settings", {})
        if not isinstance(monitor_settings, dict):
            monitor_settings = {}

        targets = set()
        wallpapers = config.get("wallpapers", {})
        if isinstance(wallpapers, dict):
            for k in wallpapers.keys():
                try:
                    targets.add(int(k))
                except Exception:
                    pass
        for k in getattr(self, "current_videos", {}).keys():
            try:
                targets.add(int(k))
            except Exception:
                pass

        if not targets:
            return

        per_screen: dict[str, dict] = {}
        for idx in sorted(targets):
            ms = monitor_settings.get(str(idx), {})
            if not isinstance(ms, dict):
                ms = {}
            vol = ms.get("volume", base_volume)
            try:
                vol = int(vol)
            except Exception:
                vol = base_volume
            vol = max(0, min(100, vol))

            paused_override = ms.get("paused", None)
            if paused_override is None:
                paused_val = global_paused
            else:
                paused_val = bool(paused_override) or global_paused

            per_screen[str(idx)] = {
                "volume": vol,
                "paused": paused_val,
            }

        msg = {
            "action": "update",
            "pause_on_max": pause_on_max,
            "per_screen": per_screen,
        }
        self._send_command_to_service(msg)

    def _send_command_to_service(self, msg: dict) -> bool:
        """Envía un comando JSON al servicio de wallpapers si está corriendo."""
        try:
            sock = QLocalSocket()
            sock.connectToServer(WALLPAPER_SERVER_NAME)
            if not sock.waitForConnected(300):
                return False

            payload = json.dumps(msg).encode("utf-8")
            sock.write(payload)
            sock.flush()
            sock.waitForBytesWritten(500)
            sock.disconnectFromServer()
            return True
        except Exception:
            return False
