

import vlc

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QTimer, QEvent, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtDBus import QDBusConnection, QDBusMessage
from PySide6.QtDBus import QDBusInterface

import os
import sys
import signal
import subprocess
import argparse
import json
import fcntl
import gc
from datetime import datetime
from pathlib import Path

import shutil
import re

import time
try:
    from Xlib import X, display as xlib_display
    from Xlib.error import XError
    XLIB_AVAILABLE = True
except ImportError:
    XLIB_AVAILABLE = False
_GSETTINGS_KEYS_CACHE: dict[str, set[str]] = {}
try:
    from gi.repository import Gio  # pyright: ignore[reportMissingImports]
    GIO_AVAILABLE = True
except ImportError:
    GIO_AVAILABLE = False

def _gsettings_list_keys(schema: str) -> set[str] | None:
    try:
        out = subprocess.check_output(["gsettings", "list-keys", schema], text=True, stderr=subprocess.STDOUT)
        return {line.strip() for line in out.splitlines() if line.strip()}
    except Exception:
        return None


def _gsettings_has_key(schema: str, key: str) -> bool:
    if GIO_AVAILABLE:
        source = Gio.SettingsSchemaSource.get_default()
        schema_obj = source.lookup(schema, True)
        return schema_obj.has_key(key) if schema_obj else False
    
    cached = _GSETTINGS_KEYS_CACHE.get(schema)
    if cached is None:
        keys = _gsettings_list_keys(schema)
        cached = keys if keys is not None else set()
        _GSETTINGS_KEYS_CACHE[schema] = cached
    return key in cached

def _detect_vlc_plugin_path() -> str | None:
    candidates = [
        "/usr/lib/x86_64-linux-gnu/vlc/plugins",
        "/usr/lib/aarch64-linux-gnu/vlc/plugins",
        "/usr/lib/arm-linux-gnueabihf/vlc/plugins",
        "/usr/lib/vlc/plugins",
        "/usr/lib64/vlc/plugins",
        "/usr/local/lib/vlc/plugins",
        "/snap/vlc/current/usr/lib/vlc/plugins",
    ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    return None


def _configure_vlc_env() -> str | None:
    existing = os.environ.get("VLC_PLUGIN_PATH")
    if existing and os.path.isdir(existing):
        return existing

    detected = _detect_vlc_plugin_path()
    if detected:
        os.environ["VLC_PLUGIN_PATH"] = detected
        return detected
    return None


_VLC_PLUGIN_PATH = _configure_vlc_env()

_MONITOR_CACHE = {"data": [], "timestamp": 0, "min_interval": 5.0}

_session_type = os.environ.get("XDG_SESSION_TYPE", "x11").lower()

_force_xcb = os.environ.get("KOMOREBI_FORCE_XCB", "1").strip().lower() in {"1", "true", "yes", "on"}

if _session_type == "wayland" and _force_xcb and "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "xcb"
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland" if _session_type == "wayland" else "xcb")

if os.environ.get("QT_QPA_PLATFORM", "").lower().startswith("wayland"):
    os.environ.setdefault("QT_WAYLAND_DISABLE_WINDOWDECORATION", "1")

LOG_FILE = Path("/dev/shm/komorebi_wall.log")
SERVER_NAME = "komorebi_wallpaper_service"

GNOME_WALLPAPER_SYNC_INTERVAL_MS = 30000
GNOME_WALLPAPER_MAX_DIMENSION = 480
GNOME_WALLPAPER_DIR = Path("/dev/shm/komorebi-sync")
GNOME_WALLPAPER_BASENAME = "komorebi-wallpaper"
GNOME_WALLPAPER_SYNC_STARTUP_DELAY_MS = 1200
GNOME_WALLPAPER_DEFAULT_MODE = "static"

CONFIG_PATH = Path.home() / ".config" / "komorebi" / "config.json"


MIN_RATE = 0.25
SAFE_MAX_RATE = 2.0
HARD_MAX_RATE = 2.5


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _load_config() -> dict:
    try:
        if not CONFIG_PATH.exists():
            return {"version": 1, "monitors": []}
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "monitors": []}
        data.setdefault("version", 1)
        data.setdefault("monitors", [])
        if not isinstance(data["monitors"], list):
            data["monitors"] = []
        return data
    except Exception as e:
        _log(f"ERROR leyendo config: {e}")
        return {"version": 1, "monitors": []}


def _save_config(data: dict) -> None:
    try:
        _atomic_write_json(CONFIG_PATH, data)
    except Exception as e:
        _log(f"ERROR guardando config: {e}")


def _normalize_monitor_entry(entry: dict) -> dict:
    """Normaliza esquema de monitor para compatibilidad futura."""
    out = dict(entry or {})
    out.setdefault("enabled", True)
    out.setdefault("screen", 0)
    out.setdefault("screen_name", None)
    out.setdefault("video_path", None)
    out.setdefault("volume", 0)
    out.setdefault("pause_on_max", False)
    out.setdefault("paused", False)
    out.setdefault("speed", 1.0)
    return out


def _upsert_monitor_config(
    *,
    screen_index: int,
    screen_name: str | None,
    video_path: str,
    volume: int,
    pause_on_max: bool,
    paused: bool,
    speed: float = 1.0,
) -> None:
    data = _load_config()
    monitors = [_normalize_monitor_entry(m) for m in (data.get("monitors") or []) if isinstance(m, dict)]

    matched = False
    for m in monitors:
        if screen_name and m.get("screen_name") == screen_name:
            m.update(
                {
                    "enabled": True,
                    "screen": int(screen_index),
                    "screen_name": screen_name,
                    "video_path": video_path,
                    "volume": int(volume),
                    "pause_on_max": bool(pause_on_max),
                    "paused": bool(paused),
                    "speed": float(speed),
                }
            )
            matched = True
            break

    if not matched:
        for m in monitors:
            if int(m.get("screen", -1)) == int(screen_index) and not m.get("screen_name"):
                m.update(
                    {
                        "enabled": True,
                        "screen": int(screen_index),
                        "screen_name": screen_name,
                        "video_path": video_path,
                        "volume": int(volume),
                        "pause_on_max": bool(pause_on_max),
                        "paused": bool(paused),
                        "speed": float(speed),
                    }
                )
                matched = True
                break

    if not matched:
        monitors.append(
            {
                "enabled": True,
                "screen": int(screen_index),
                "screen_name": screen_name,
                "video_path": video_path,
                "volume": int(volume),
                "pause_on_max": bool(pause_on_max),
                "paused": bool(paused),
                "speed": float(speed),
            }
        )

    data["monitors"] = monitors
    _save_config(data)


def _disable_monitor_config(*, screen_index: int, screen_name: str | None) -> None:
    data = _load_config()
    monitors = [_normalize_monitor_entry(m) for m in (data.get("monitors") or []) if isinstance(m, dict)]
    for m in monitors:
        if screen_name and m.get("screen_name") == screen_name:
            m["enabled"] = False
        elif int(m.get("screen", -1)) == int(screen_index) and not screen_name:
            m["enabled"] = False
    data["monitors"] = monitors
    _save_config(data)


def _xrandr_monitors(force_refresh: bool = False) -> list[dict]:
    now = time.time()

    if not force_refresh and (now - _MONITOR_CACHE["timestamp"]) < _MONITOR_CACHE["min_interval"]:
        return _MONITOR_CACHE["data"]
    
    if not shutil.which("xrandr"):
        return []
    try:
        out = subprocess.check_output(
            ["xrandr", "--listmonitors"], 
            text=True, 
            stderr=subprocess.STDOUT,
            timeout=2
        )
    except Exception as e:
        _log(f" Error ejecutando xrandr: {e}")
        return _MONITOR_CACHE["data"]

    monitors: list[dict] = []
    geom_re = re.compile(r"(?P<w>\d+)/(?:\d+)x(?P<h>\d+)/(?:\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)")

    for line in out.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("monitors:"):
            continue
        parts = line.split()
        if len(parts) < 3 or not parts[0].endswith(":"):
            continue
        m = None
        for p in parts:
            m = geom_re.match(p)
            if m:
                break
        if not m:
            continue
        name = parts[-1]
        monitors.append(
            {
                "name": name,
                "x": int(m.group("x")),
                "y": int(m.group("y")),
                "w": int(m.group("w")),
                "h": int(m.group("h")),
            }
        )
    
    if monitors:
        _MONITOR_CACHE["data"] = monitors
        _MONITOR_CACHE["timestamp"] = now
    
    return monitors


def _current_monitor_inventory() -> list[dict]:
    """Devuelve inventario de monitores preferentemente por xrandr (Wayland+XWayland),
    con fallback a Qt screens.

    Cada elemento: {name, index, x, y, w, h}
    """
    xmon = _xrandr_monitors(force_refresh=False)  # Usar cache
    if len(xmon) > 0:
        inv = []
        for i, m in enumerate(xmon):
            inv.append({"index": i, **m})
        return inv

    inv = []
    for i, s in enumerate(QGuiApplication.screens()):
        g = s.geometry()
        inv.append(
            {
                "index": i,
                "name": s.name(),
                "x": int(g.x()),
                "y": int(g.y()),
                "w": int(g.width()),
                "h": int(g.height()),
            }
        )
    return inv


def _log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")
    except Exception:
        pass

class X11WindowDetector:
    """Detecta ventanas maximizadas sin subprocess usando python-xlib directamente."""
    def __init__(self):
        if not XLIB_AVAILABLE:
            self.display = None
            return
        try:
            self.display = xlib_display.Display()
            self.root = self.display.screen().root
            self._net_active = self.display.intern_atom('_NET_ACTIVE_WINDOW')
            self._net_wm_state = self.display.intern_atom('_NET_WM_STATE')
            self._maximized_vert = self.display.intern_atom('_NET_WM_STATE_MAXIMIZED_VERT')
            self._maximized_horz = self.display.intern_atom('_NET_WM_STATE_MAXIMIZED_HORZ')
        except Exception as e:
            _log(f"Error inicializando X11WindowDetector: {e}")
            self.display = None
    
    def is_any_window_maximized(self) -> bool:
        """Retorna True si la ventana activa está maximizada."""
        if self.display is None:
            return False
        
        try:
            active = self.root.get_full_property(
                self._net_active, X.AnyPropertyType
            )
            if not active or not active.value:
                return False
            
            win_id = active.value[0]
            if win_id == 0:
                return False
            
            window = self.display.create_resource_object('window', win_id)
            state = window.get_full_property(
                self._net_wm_state, X.AnyPropertyType
            )
            
            if not state:
                return False
            
            states = state.value
            return (self._maximized_vert in states and 
                    self._maximized_horz in states)
        except (XError, Exception):
            return False

def check_session_type():
    """Retorna el tipo de sesión (wayland o x11) y si es GNOME"""
    session = os.environ.get("XDG_SESSION_TYPE", "x11").lower()
    is_gnome_env = is_gnome()
    session_type = "Wayland" if session == "wayland" else "X11"
    desktop = "GNOME" if is_gnome_env else os.environ.get('XDG_CURRENT_DESKTOP', 'Desconocido')
    _log(f" Sesión detectada: {desktop} ({session_type})")
    return session, is_gnome_env


def is_gnome() -> bool:
    return "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


def _gsettings_get(key: str) -> str | None:
    schema = "org.gnome.desktop.background"
    if GIO_AVAILABLE:
        try:
            settings = Gio.Settings.new(schema)
            return settings.get_value(key).print_(True)
        except: return None

    if not _gsettings_has_key(schema, key): return None
    try:
        out = subprocess.check_output(["gsettings", "get", schema, key], text=True).strip()
        return out
    except: return None


def _gsettings_quote(value: str) -> str:
    """Convierte un string Python a un literal válido para `gsettings set`.

    - Si ya viene con comillas simples (ej. "'zoom'"), lo deja intacto.
    - Si no, lo envuelve en comillas simples y escapa comillas simples internas.
    """
    v = str(value)
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        return v
    v = v.replace("'", "\\'")
    return f"'{v}'"


def _gsettings_set_schema(schema: str, key: str, value: str) -> bool:
    if GIO_AVAILABLE:
        try:
            settings = Gio.Settings.new(schema)
            clean_value = value.strip("'").strip('"')
            return settings.set_string(key, clean_value)
        except Exception as e:
            _log(f"Error Gio: {e}")

    try:
        res = subprocess.run(["gsettings", "set", schema, key, value], capture_output=True)
        return res.returncode == 0
    except: return False


def _gsettings_set(key: str, value: str) -> bool:
    return _gsettings_set_schema("org.gnome.desktop.background", key, _gsettings_quote(value))

def _cleanup_old_snapshots(directory: Path, max_age_seconds: int = 300):
    """Borra snapshots más viejos de N segundos para evitar acumulación en /dev/shm."""
    try:
        if not directory.exists():
            return
        
        now = time.time()
        count = 0
        for file in directory.glob(f"{GNOME_WALLPAPER_BASENAME}-*.jpg"):
            try:
                if (now - file.stat().st_mtime) > max_age_seconds:
                    file.unlink()
                    count += 1
            except Exception:
                pass
        
        if count > 0:
            _log(f"Cleanup: eliminados {count} snapshots viejos de {directory}")
    except Exception as e:
        _log(f"Error en cleanup de snapshots: {e}")

class BackgroundPlayer(QWidget):
    def __init__(
        self,
        video_path: str,
        pause_on_max: bool = False,
        screen_index: int = 0,
        volume: int = 0,
        paused: bool = False,
        vlc_instance: vlc.Instance | None = None,
        start_position: float | None = None,
    ):
        super().__init__()
        self.video_path = video_path
        self.pause_on_max = pause_on_max
        self.screen_index = screen_index
        self.volume = int(volume)
        self.paused = bool(paused)
        self._user_paused = bool(paused)
        self._start_position = start_position
        self.speed = 1.0

        self._xprop_failed_count = 0
        self.screen_name = None
        self.is_suspended = False


        self._idle_mode = False
        self._last_activity = time.time()
        self._idle_threshold_ms = 60000  
        
        self._xprop_cache = (None, 0.0)  
        self._xprop_cache_ttl_ms = 2000  
        
        # Cache adicional para _NET_WM_STATE: más agresivo (5s)
        self._wm_state_cache = (None, 0.0)  # (is_maximized, timestamp)
        self._wm_state_cache_ttl_ms = 5000  # 5s TTL

        self.gnome_interface = QDBusInterface(
    "org.gnome.Shell",
    "/org/gnome/Shell",
    "org.gnome.Shell",
    QDBusConnection.sessionBus()
)

        if XLIB_AVAILABLE:
            try:
                self._x11_detector = X11WindowDetector()
                if self._x11_detector.display is None:
                    self._x11_detector = None
            except Exception:
                self._x11_detector = None
        else:
            self._x11_detector = None

        self._vlc_media: vlc.Media | None = None
        self._vlc_events_attached = False
        self._vlc_restart_in_progress = False
        self._vlc_restart_count = 0
        self._vlc_restart_count_reset_timer: QTimer | None = None
        self._vlc_restart_backoff_ms = 500
        self._vlc_stable_timer: QTimer | None = None
        self._playback_ready = False
        self._pause_on_max_enabled = bool(pause_on_max)

        self._vlc_instance = vlc_instance or self._create_vlc_instance()
        self._vlc_player: vlc.MediaPlayer | None = None

        self._crop_retry = 0
        self._crop_timer: QTimer | None = None
        self._last_crop: str | None = None

        self._startup_pause_pending = bool(paused)

        self._fade_anim: QPropertyAnimation | None = None

        self._setup_window()

        self.screen_timer = QTimer(self)
        self.screen_timer.timeout.connect(self._check_screen_alive)
        self._update_screen_timer_interval()
        self.screen_timer.start()

        self.monitor_timer: QTimer | None = None
        self._check_count = 0
        if self._pause_on_max_enabled:
            self.monitor_timer = QTimer(self)
            self.monitor_timer.timeout.connect(self._check_maximized_window)

    def _update_screen_timer_interval(self) -> None:
        """Ajusta el intervalo del timer según si está en idle o no."""
        interval_ms = 30000 if self._idle_mode else 10000
        self.screen_timer.setInterval(interval_ms)

    def _mark_activity(self) -> None:
        """Marca actividad visible y sale del modo idle si es necesario."""
        now = time.time() * 1000  # ms
        self._last_activity = now
        if self._idle_mode:
            self._idle_mode = False
            self._update_screen_timer_interval()
            _log(f"Pantalla {self.screen_index}: Saliendo de modo idle")

    def _check_idle_status(self) -> None:
        """Verifica si la ventana lleva inactiva demasiado tiempo y entra en idle."""
        if self.is_suspended or self._user_paused:
            return
        
        now = time.time() * 1000
        inactive_ms = now - self._last_activity
        
        # Si no es visible y ha pasado el threshold, entrar en idle
        should_idle = (
            (not self.isVisible() or 
             (self.windowState() & Qt.WindowState.WindowMinimized)) and
            inactive_ms >= self._idle_threshold_ms
        )
        
        if should_idle and not self._idle_mode:
            self._idle_mode = True
            self._update_screen_timer_interval()
            _log(f"Pantalla {self.screen_index}: Entrando en modo idle (inactiva {inactive_ms/1000:.1f}s)")
        elif not should_idle and self._idle_mode:
            self._idle_mode = False
            self._update_screen_timer_interval()

    def _get_active_window_cached(self) -> str | None:
        """Retorna active window ID desde xprop, con caché de 2s."""
        now = time.time() * 1000
        cached_result, cached_time = self._xprop_cache
        
        # Si está en caché y no ha expirado, devolverlo
        if cached_result is not None and (now - cached_time) < self._xprop_cache_ttl_ms:
            return cached_result
        
        try:
            res = subprocess.check_output(
                ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                stderr=subprocess.DEVNULL,
                timeout=0.4
            ).decode()
            if "window id #" in res:
                wid = res.split("#")[1].split(",")[0].strip()
                self._xprop_cache = (wid, now)
                return wid
        except Exception:
            pass
        
        self._xprop_cache = (None, now)
        return None

    def _reapply_speed(self) -> None:
        """Reaplicar velocidad actual tras eventos de lifecycle.
        
        Evita que VLC vuelva a 1.0x silenciosamente tras set_media, play, resume.
        """
        if self._vlc_player is None or self.speed <= 0:
            return
        real_speed = self._apply_speed_safely(self.speed)
        self.speed = real_speed

    def _apply_speed_safely(self, requested: float) -> float:
        """Aplica velocidad con validación y fallback seguro.

        - Clampa al rango permitido (MIN_RATE..HARD_MAX_RATE).
        - Verifica aceptación vía retorno y get_rate().
        - Si falla, cae a SAFE_MAX_RATE sin reiniciar ni pausar.
        """
        try:
            target = float(requested)
        except Exception:
            target = 1.0

        target = max(MIN_RATE, min(HARD_MAX_RATE, target))
        applied = target

        player = self._vlc_player
        if player is None:
            return applied

        result = None
        try:
            result = player.set_rate(target)
        except Exception:
            result = -1

        try:
            actual = float(player.get_rate() or 0.0)
        except Exception:
            actual = 0.0

        success_res = (result is None) or (isinstance(result, (int, float)) and result >= 0)
        close_enough = actual > 0 and abs(actual - target) <= max(0.1, 0.15 * target)

        if success_res and close_enough:
            return actual

        fallback = SAFE_MAX_RATE if target > SAFE_MAX_RATE else target
        try:
            player.set_rate(fallback)
        except Exception:
            pass

        try:
            actual_fb = float(player.get_rate() or 0.0)
        except Exception:
            actual_fb = 0.0

        if actual_fb > 0:
            applied = actual_fb
        else:
            applied = fallback

        return applied

    def apply_runtime_settings(
        self,
        *,
        volume: int | None = None,
        paused: bool | None = None,
        pause_on_max: bool | None = None,
        speed: float | None = None,
    ) -> None:
        if volume is not None:
            try:
                self.volume = int(volume)
            except Exception:
                self.volume = 0
            try:
                if self._vlc_player is not None:
                    self._vlc_player.audio_set_volume(max(0, min(100, int(self.volume))))
            except Exception:
                pass

        if speed is not None:
            self.speed = self._apply_speed_safely(speed)

        if pause_on_max is not None:
            self.pause_on_max = bool(pause_on_max)
            self._pause_on_max_enabled = bool(pause_on_max)
            if self._pause_on_max_enabled:
                if self.monitor_timer is None:
                    self.monitor_timer = QTimer(self)
                    self.monitor_timer.timeout.connect(self._check_maximized_window)
                if not self.monitor_timer.isActive():
                    self.monitor_timer.start(2000)
            else:
                try:
                    if self.monitor_timer is not None and self.monitor_timer.isActive():
                        self.monitor_timer.stop()
                except Exception:
                    pass

        if paused is not None:
            self.paused = bool(paused)
            self._user_paused = bool(paused)
            if self._user_paused:
                self._suspend_video()
            else:
                # No reanudar si hay ventana maximizada activa.
                if not getattr(self, "_maximized_active", False):
                    self._resume_video()

    @staticmethod
    def _create_vlc_instance() -> vlc.Instance:
        base_options = [
            "--avcodec-hw=any",
            "--hwdec=auto",
            "--no-video-title-show",
            "--video-title-timeout=0",
            "--no-osd",
            "--no-snapshot-preview",
            "--video-on-top",
            "--quiet",
            "--file-caching=300",
            "--network-caching=300",
            "--disc-caching=300",
            "--live-caching=300",
            "--drop-late-frames",
            "--skip-frames",
            "--no-sub-autodetect-file",
            "--no-spu",
            "--no-disable-screensaver",
            "--no-inhibit",
        ]

        if os.environ.get("KOMOREBI_VLC_NO_XLIB", "0").strip().lower() in {"1", "true", "yes", "on"}:
            base_options.append("--no-xlib")
            _log("libVLC: --no-xlib habilitado (KOMOREBI_VLC_NO_XLIB=1)")

        plugin_path = os.environ.get("VLC_PLUGIN_PATH")
        plugin_opt = []
        if plugin_path and os.path.isdir(plugin_path):
            plugin_opt = [f"--plugin-path={plugin_path}"]

        if plugin_path:
            _log(f"libVLC: VLC_PLUGIN_PATH={plugin_path}")
        else:
            _log("libVLC: VLC_PLUGIN_PATH no seteado")

        try:
            get_ver = getattr(vlc, "libvlc_get_version", None)
            if callable(get_ver):
                _log(f"libVLC: version={get_ver()}")
        except Exception:
            pass

        vout_candidates = ["x11", "xcb_x11"]
        candidate_sets: list[list[str]] = []
        for vout in vout_candidates:
            candidate_sets.append(base_options + plugin_opt + [f"--vout={vout}"])
        candidate_sets += [
            base_options + plugin_opt,
            base_options,
            plugin_opt,
            [],
        ]

        last_err: str | None = None
        for opts in candidate_sets:
            try:
                inst = vlc.Instance(opts)
                if inst is None:
                    last_err = f"vlc.Instance devolvió None (opts={opts})"
                    continue

                selected_vout = "auto"
                for o in opts:
                    if o.startswith("--vout="):
                        selected_vout = o.split("=", 1)[1]
                        break
                _log(f"libVLC: instancia creada OK (vout={selected_vout})")
                return inst
            except Exception as e:
                last_err = f"{type(e).__name__}: {e} (opts={opts})"
                _log(f"ERROR creando instancia VLC: {last_err}")

        raise RuntimeError(f"No se pudo inicializar libVLC. {last_err or ''}")

    def _ensure_vlc_player(self):
        if self._vlc_player is not None:
            return
        if self._vlc_instance is None:
            raise RuntimeError("libVLC no está inicializado (vlc_instance=None)")
        self._vlc_player = self._vlc_instance.media_player_new()

    def _attach_vlc_events(self):
        if self._vlc_player is None or self._vlc_events_attached:
            return
        try:
            em = self._vlc_player.event_manager()

            def _on_end(event):
                def _check_and_restart():
                    if self._vlc_player is None:
                        return
                    st = self._vlc_player.get_state()
                    if str(st).lower().endswith(("ended", "stopped")):
                        self._restart_vlc_playback("end-reached")
                QTimer.singleShot(200, _check_and_restart)

            def _on_error(event):
                QTimer.singleShot(0, lambda: self._restart_vlc_playback("error"))

            try:
                em.event_attach(vlc.EventType.MediaPlayerEndReached, _on_end)
            except Exception:
                pass

            try:
                em.event_attach(vlc.EventType.MediaPlayerEncounteredError, _on_error)
            except Exception:
                pass

            def _on_playing(event):
                QTimer.singleShot(100, self._force_aspect_ratio)

            try:
                em.event_attach(vlc.EventType.MediaPlayerPlaying, _on_playing)
            except Exception:
                pass

            self._vlc_events_attached = True
        except Exception as e:
            _log(f"ERROR adjuntando eventos VLC: {e}")

    def _set_vlc_media(self):
        if self._vlc_instance is None or self._vlc_player is None: return
        media = self._vlc_instance.media_new(self.video_path)
        
        media.add_option("input-repeat=999999") 
        media.add_option("loop")
        media.add_option("no-video-title-show")
        media.add_option("file-caching=300")
        
        self._vlc_player.set_media(media)
        self._vlc_media = media
        # VLC resetea rate a 1.0 al setear media; reaplicar después.
        QTimer.singleShot(50, self._reapply_speed)

    def _mark_playback_ready(self):
        if self._playback_ready:
            return
        self._playback_ready = True

        if self._vlc_stable_timer is None:
            self._vlc_stable_timer = QTimer(self)
            self._vlc_stable_timer.setSingleShot(True)

            def _reset_after_stable():
                try:
                    if self._vlc_player is None:
                        return
                    st = self._vlc_player.get_state()
                    t = int(self._vlc_player.get_time() or 0)
                    if t > 0 and str(st).lower().endswith("playing"):
                        self._vlc_restart_count = 0
                        self._vlc_restart_backoff_ms = 500
                        _log("VLC: reproducción estable detectada; reset backoff")
                except Exception:
                    pass

            self._vlc_stable_timer.timeout.connect(_reset_after_stable)

        if not self._vlc_stable_timer.isActive():
            self._vlc_stable_timer.start(3000)

        if self._pause_on_max_enabled and self.monitor_timer is not None and not self.monitor_timer.isActive():
            self.monitor_timer.start(2000)

    def _restart_vlc_playback(self, reason: str):
        if self._vlc_player is None or getattr(self, "_vlc_restart_in_progress", False):
            return

        self._vlc_restart_in_progress = True
        self._playback_ready = False
        _log(f"VLC: Hard Reset por {reason}")

        def _do_restart():
            try:
                if self._vlc_player is None: return
                self._vlc_player.stop()

                self._last_crop = None

                self._set_vlc_media() 
                self._vlc_player.play()
                
                if self.is_suspended:
                    QTimer.singleShot(100, lambda: self._vlc_player.set_pause(1))
                    
            finally:
                self._vlc_restart_in_progress = False

        QTimer.singleShot(300, _do_restart)

    def _start_vlc(self):
        if not os.path.exists(self.video_path):
            _log(f"ERROR: El archivo de video no existe: {self.video_path}")
            return

        if not self.isVisible():
            tries = getattr(self, "_start_vlc_visible_tries", 0)
            if tries < 20:
                setattr(self, "_start_vlc_visible_tries", tries + 1)
                QTimer.singleShot(100, self._start_vlc)
            else:
                _log("ERROR: ventana no visible tras varios intentos; no se inicializa VLC")
            return

        self._ensure_vlc_player()

        # Evitar VLC flotante: si no estamos en backend X11 (xcb), no podemos incrustar.
        try:
            platform = (QGuiApplication.platformName() or "").lower()
        except Exception:
            platform = ""
        if platform and platform != "xcb":
            _log(f"VLC: embedding no soportado en Qt platform='{platform}'. Se omite inicio para evitar ventana flotante.")
            return

        if getattr(self, "_vlc_xwindow_set", False) is not True:
            tries = getattr(self, "_start_vlc_xid_tries", 0)
            if tries >= 20:
                _log("ERROR: no se pudo setear XWindow para VLC tras varios intentos")
                return
            setattr(self, "_start_vlc_xid_tries", tries + 1)

            def _set_xid_later():
                try:
                    if not self.isVisible() or self._vlc_player is None:
                        QTimer.singleShot(100, self._start_vlc)
                        return
                    # Esperar a que el servidor gráfico haya creado el XID real.
                    if self.windowHandle() is not None:
                        try:
                            if not self.windowHandle().isExposed():
                                QTimer.singleShot(50, self._start_vlc)
                                return
                        except Exception:
                            pass

                    xid = int(self.winId())
                    if xid == 0:
                        QTimer.singleShot(50, self._start_vlc)
                        return

                    self._vlc_player.set_xwindow(xid)
                    setattr(self, "_vlc_xwindow_set", True)
                    _log(f"VLC: set_xwindow OK xid={xid}")
                    QTimer.singleShot(0, self._start_vlc)
                except Exception as e:
                    _log(f"ERROR: No se pudo setear XWindow para VLC: {e}")
                    QTimer.singleShot(150, self._start_vlc)

            QTimer.singleShot(100, _set_xid_later)
            return

        self._attach_vlc_events()
        self._set_vlc_media()

        self._vlc_player.audio_set_volume(max(0, min(100, int(self.volume))))
        self._vlc_player.video_set_mouse_input(False)
        self._vlc_player.video_set_key_input(False)

        try:
            self._vlc_player.video_set_scale(0)
        except Exception:
            pass

        # Hacer ventana completamente visible - sin animación en Wayland
        self.setWindowOpacity(1.0)
        
        # Forzar ventana al fondo repetidamente
        for i in range(50):
            QTimer.singleShot(i * 50, self.lower)
        
        # Continuar forzando al fondo
        def keep_lowering():
            if self.isVisible():
                self.lower()
        
        self._lower_timer = QTimer(self)
        self._lower_timer.timeout.connect(keep_lowering)
        self._lower_timer.start(500)

        try:
            rc = self._vlc_player.play()
            _log(f"VLC play() -> {rc}")
        except Exception as e:
            _log(f"ERROR VLC play(): {e}")
            return
        
        # Reaplicar velocidad tras play().
        QTimer.singleShot(100, self._reapply_speed)
        
        if self._startup_pause_pending:
            self._startup_pause_pending = False

            def _pause_when_ready(tries: int = 0):
                try:
                    if self._vlc_player is None:
                        return
                    st = self._vlc_player.get_state()
                    t = int(self._vlc_player.get_time() or 0)
                    vw, vh = self._get_video_size()

                    if str(st).lower().endswith("ended"):
                        self._restart_vlc_playback("ended-during-startup")
                        if tries < 40:
                            QTimer.singleShot(150, lambda: _pause_when_ready(tries + 1))
                        return

                    
                    if (vw > 0 and vh > 0 and t > 0) or str(st).lower().endswith("playing"):
                        self._mark_playback_ready()
                        self._suspend_video()
                        return

                    if tries < 20:
                        QTimer.singleShot(150, lambda: _pause_when_ready(tries + 1))
                    else:
                    
                        _log("ADVERTENCIA: timeout esperando primer frame; pausando de todos modos")
                        self._mark_playback_ready()
                        self._suspend_video()
                except Exception as e:
                    _log(f"ERROR esperando primer frame para pausar: {e}")

            QTimer.singleShot(150, _pause_when_ready)

        def _log_playback_state(tag: str):
            try:
                if self._vlc_player is None:
                    return
                st = self._vlc_player.get_state()
                t = self._vlc_player.get_time()
                l = self._vlc_player.get_length()
                vw, vh = self._get_video_size()
                _log(f"VLC state({tag})={st} time={t} len={l} size={vw}x{vh}")
            except Exception as e:
                _log(f"ERROR leyendo estado VLC ({tag}): {e}")

        QTimer.singleShot(500, lambda: _log_playback_state("0.5s"))
        QTimer.singleShot(1500, lambda: _log_playback_state("1.5s"))

        
    def _watchdog(self):
        try:
            if self._vlc_player is None: return
            
            st = self._vlc_player.get_state()
            t = int(self._vlc_player.get_time() or 0)
            length = int(self._vlc_player.get_length() or 0)

            
            if str(st).lower().endswith(("ended", "stopped")):
                _log(f"Watchdog: Estado {st} detectado. Reviviendo video.")
                self._restart_vlc_playback("state-ended-recovery")
                return

            
            if self.is_suspended: return
            
            
            if length > 0 and t >= (length - 150):
                _log(f"Watchdog: Fin de tiempo detectado ({t}/{length}ms). Reiniciando...")
                self._restart_vlc_playback("time-limit-reached")
                return

            
            if str(st).lower().endswith("playing") and t == 0:
                clock_zero = getattr(self, "_watchdog_stuck_zero", 0) + 1
                setattr(self, "_watchdog_stuck_zero", clock_zero)
                if clock_zero > 3: 
                    _log("Watchdog: Reloj clavado en 0ms. Hard Reset.")
                    self._restart_vlc_playback("stuck-at-zero")
                    setattr(self, "_watchdog_stuck_zero", 0)
            else:
                setattr(self, "_watchdog_stuck_zero", 0)
                
        except Exception as e:
            _log(f"ERROR en watchdog: {e}")

    def snapshot_to_file(self, path: Path, width: int, height: int) -> bool:
        """Toma snapshot usando ffmpeg."""
        if self._vlc_player is None or not os.path.exists(self.video_path):
            return False
        
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            current_time_ms = self._vlc_player.get_time()
            timestamp = max(0, current_time_ms / 1000.0)

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(timestamp), 
                "-i", self.video_path,
                "-frames:v", "1",
                "-an", "-sn",
                
                "-vf", f"scale={width}:{height},gblur=sigma=5:steps=3,eq=saturation=1.1",
                "-q:v", "2", 
                "-f", "mjpeg",
                str(path)
            ]

            
            subprocess.run(
                cmd, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL, 
                timeout=5
            )
            
            return path.exists()
            
        except Exception as e:
            _log(f"Error en snapshot: {e}")
            return False
     
    def _get_video_size(self) -> tuple[int, int]:
        if self._vlc_player is None:
            return (0, 0)
        try:
            w, h = self._vlc_player.video_get_size(0)
            return int(w or 0), int(h or 0)
        except Exception:
            return (0, 0)


    def _apply_crop_if_ready(self):
        if self._vlc_player is None:
            return

        w_w = int(self.width())
        w_h = int(self.height())
        
        if w_w <= 0 or w_h <= 0:
            return

        # Forzar aspect ratio a la ventana para evitar barras negras.
        aspect_str = f"{w_w}:{w_h}"
        
        if aspect_str != self._last_crop:
            try:
                self._vlc_player.video_set_crop_geometry(None)
            except Exception:
                pass
            
            try:
                self._vlc_player.video_set_aspect_ratio(aspect_str)
                self._vlc_player.video_set_scale(0) # 0 = Ajustar a ventana
                self._last_crop = aspect_str
                _log(f"Aspect Ratio forzado a ventana: {aspect_str}")
            except Exception as e:
                _log(f"ERROR aplicando aspect ratio: {e}")

    def _force_aspect_ratio(self):
        """Fuerza el aspect ratio después de que VLC comience a reproducir.
        VLC tiende a resetear la proporción al cargar el primer frame."""
        if self._vlc_player is None:
            return

        self._crop_retry = 0
        self._last_crop = None  # Forzar re-aplicación
        self._apply_crop_if_ready()

        QTimer.singleShot(250, self._delayed_aspect_fix)
        QTimer.singleShot(750, self._delayed_aspect_fix)
        QTimer.singleShot(1500, self._delayed_aspect_fix)

    def _delayed_aspect_fix(self):
        """Aplicación tardía del crop para casos donde VLC resetea después del primer frame."""
        if self._vlc_player is None:
            return

        self._last_crop = None
        self._apply_crop_if_ready()

    def _schedule_crop(self, reset: bool = False):
        if reset:
            self._crop_retry = 0
        if self._crop_timer is None:
            self._crop_timer = QTimer(self)
            self._crop_timer.setSingleShot(True)
            self._crop_timer.timeout.connect(self._apply_crop_if_ready)
        self._crop_timer.start(150)

    def _check_screen_alive(self):
        screens = QGuiApplication.screens()
        xmon = _xrandr_monitors(force_refresh=False)
        use_xrandr_layout = len(xmon) > 1 and len(screens) <= 1

        if self.windowHandle():
            current_screen = self.windowHandle().screen()
            if current_screen:
                geo = current_screen.geometry()
                window_geo = self.geometry()
                
                if (abs(window_geo.width() - geo.width()) > 50 or 
                    abs(window_geo.height() - geo.height()) > 50):
                    _log(f"⚠️ Geometría cambió en pantalla {self.screen_index}")
                    self._update_geometry(geo)
                    self._schedule_crop(reset=True)

        if self.screen_name:
            found_index = -1
            for i, s in enumerate(screens):
                if s.name() == self.screen_name:
                    found_index = i
                    break

            if found_index != -1 and found_index != self.screen_index:
                _log(f"🔄 Pantalla '{self.screen_name}' movida de {self.screen_index} a {found_index}")
                self.screen_index = found_index
                if self.windowHandle():
                    self.windowHandle().setScreen(screens[found_index])
                    self._update_geometry(screens[found_index].geometry())
                    self._schedule_crop(reset=True)
                    if self.is_suspended:
                        self._resume_video()

        qt_has = self.screen_index < len(screens)
        xr_has = self.screen_index < len(xmon)
        
        if not qt_has and not xr_has:
            self.missing_screen_count = getattr(self, "missing_screen_count", 0) + 1
            _log(f"⚠️ Pantalla {self.screen_index} no detectada ({self.missing_screen_count}/2)")

            if self.missing_screen_count >= 2:
                _log(f"❌ Auto-destruyendo player {self.screen_index}")
                self.close()
                self.deleteLater()
                return
        else:
            self.missing_screen_count = 0

        current_screen = screens[self.screen_index] if (qt_has and not use_xrandr_layout) else None

        if not self.screen_name:
            if current_screen is not None:
                self.screen_name = current_screen.name()
            elif xr_has:
                self.screen_name = xmon[self.screen_index]["name"]

        window_handle = self.windowHandle()

        if window_handle and current_screen is not None:
            assigned_screen = window_handle.screen()
            if assigned_screen != current_screen:
                _log(f" Reasignando a pantalla {self.screen_index}")
                window_handle.setScreen(current_screen)
                self._update_geometry(current_screen.geometry())
                self._schedule_crop(reset=True)
        elif xr_has and (use_xrandr_layout or not qt_has):
            xm = xmon[self.screen_index]
            if (self.geometry().x() != xm["x"] or self.geometry().y() != xm["y"] or
                self.width() != xm["w"] or self.height() != xm["h"]):
                self.setGeometry(xm["x"], xm["y"], xm["w"], xm["h"])
                self.setFixedSize(xm["w"], xm["h"])
                self.move(xm["x"], xm["y"])
                _log(f" Geometría (xrandr) {self.screen_index}: {xm['x']},{xm['y']} {xm['w']}x{xm['h']}")
                self._schedule_crop(reset=True)

        if not self.isVisible() and not (self.windowState() & Qt.WindowState.WindowMinimized):
            _log(f" Ventana {self.screen_index} oculta. Forzando show()")
            self.show()
            self.lower()

        self._check_idle_status()

    def _setup_window(self):

        try:
            base_type = Qt.WindowType.Desktop
        except Exception:
            base_type = Qt.WindowType.Tool

        flags = base_type | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus

        try:
            flags |= Qt.WindowType.Tool
        except Exception:
            pass
        
        try:
            flags |= Qt.WindowType.WindowTransparentForInput
        except Exception:
            pass
        try:
            flags |= Qt.WindowType.WindowStaysOnBottomHint
        except Exception:
            pass

        self.setWindowFlags(flags)
        self.setWindowTitle(f"WallpaperPlayer_{self.screen_index}")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


        try:
            self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        except Exception:
            pass

        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_X11DoNotAcceptFocus, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_X11NetWmWindowTypeDesktop, True)
        except Exception:
            pass
        try:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        except Exception:
            pass
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self.setStyleSheet("background-color: black;")

        self._find_screen_and_show()

    def showEvent(self, event):
        super().showEvent(event)
        _log(f"Ventana {self.screen_index} mostrada (ShowEvent)")

        if self._vlc_player is None:
            self._start_vlc()

        # Por si el compositor aplica cambios de tamaño/scale al mostrar.
        self._schedule_crop(reset=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_crop(reset=False)

    def _find_screen_and_show(self, attempt=1):
        screens = QGuiApplication.screens()
        _log(f"Intento {attempt}: Detectadas {len(screens)} pantallas. Buscando índice {self.screen_index}")
        xmon = _xrandr_monitors()
        use_xrandr_layout = len(xmon) > 1 and len(screens) <= 1

        if use_xrandr_layout and 0 <= self.screen_index < len(xmon):
            xm = xmon[self.screen_index]
            self.screen_name = xm["name"]

            self.setGeometry(xm["x"], xm["y"], xm["w"], xm["h"])
            self.setFixedSize(xm["w"], xm["h"])
            self.move(xm["x"], xm["y"])

            _log(
                f"Configurando geometría (xrandr) para pantalla {self.screen_index} '{self.screen_name}': {xm['x']},{xm['y']} {xm['w']}x{xm['h']}"
            )

            self._apply_x11_props()

            self.show()
            self.lower()
            for i in range(5):
                QTimer.singleShot(i * 300, self.lower)

            if self._vlc_player is None:
                self._start_vlc()

        elif 0 <= self.screen_index < len(screens):
            screen = screens[self.screen_index]
            self.screen_name = screen.name()
            if self.windowHandle():
                self.windowHandle().setScreen(screen)

            geo = screen.geometry()
            self.setGeometry(geo)
            self.setFixedSize(geo.width(), geo.height())
            self.move(geo.x(), geo.y())

            try:
                screen.geometryChanged.disconnect(self._update_geometry)
            except Exception:
                pass
            screen.geometryChanged.connect(self._update_geometry)

            _log(f"Configurando geometría para pantalla {self.screen_index}: {geo.x()},{geo.y()} {geo.width()}x{geo.height()}")

            self._apply_x11_props()

            self.show()
            self.lower()
            for i in range(5):
                QTimer.singleShot(i * 300, self.lower)

            if self._vlc_player is None:
                self._start_vlc()

        else:
            if 0 <= self.screen_index < len(xmon):
                xm = xmon[self.screen_index]
                self.screen_name = xm["name"]

                self.setGeometry(xm["x"], xm["y"], xm["w"], xm["h"])
                self.setFixedSize(xm["w"], xm["h"])
                self.move(xm["x"], xm["y"])

                _log(
                    f"Configurando geometría (xrandr) para pantalla {self.screen_index} '{self.screen_name}': {xm['x']},{xm['y']} {xm['w']}x{xm['h']}"
                )

                self._apply_x11_props()

                self.show()
                self.lower()
                for i in range(5):
                    QTimer.singleShot(i * 300, self.lower)

                if self._vlc_player is None:
                    self._start_vlc()
            else:
                if attempt < 10:
                    QTimer.singleShot(1000, lambda: self._find_screen_and_show(attempt + 1))
                else:
                    _log(f"ERROR: No se encontró la pantalla {self.screen_index} tras varios intentos. Cerrando.")
                    self.close()
                    self.deleteLater()

    def _update_geometry(self, geo):
        self.setGeometry(geo)
        self.setFixedSize(geo.width(), geo.height())
        self.move(geo.x(), geo.y())
        _log(f"Actualizando geometría por cambio en pantalla {self.screen_index}: {geo}")

        self._schedule_crop(reset=True)

        for i in range(10):
            QTimer.singleShot(i * 200, self.lower)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                QTimer.singleShot(0, self.show)
                QTimer.singleShot(10, self.lower)
        super().changeEvent(event)

    def _apply_x11_props(self):
        if not shutil.which("xprop"):
            _log("ADVERTENCIA: 'xprop' no encontrado. La ventana podría no comportarse como fondo de pantalla.")
            return

        try:
            wid = self.winId()

            cmd_type = [
                "xprop",
                "-id",
                str(wid),
                "-f",
                "_NET_WM_WINDOW_TYPE",
                "32a",
                "-set",
                "_NET_WM_WINDOW_TYPE",
                "_NET_WM_WINDOW_TYPE_DESKTOP",
            ]
            res_type = subprocess.run(cmd_type, capture_output=True, text=True)
            if res_type.returncode != 0:
                _log(f"Error xprop type: {res_type.stderr}")

            cmd_state = [
                "xprop",
                "-id",
                str(wid),
                "-f",
                "_NET_WM_STATE",
                "32a",
                "-set",
                "_NET_WM_STATE",
                "_NET_WM_STATE_SKIP_TASKBAR,_NET_WM_STATE_SKIP_PAGER,_NET_WM_STATE_BELOW,_NET_WM_STATE_STICKY",
            ]
            res_state = subprocess.run(cmd_state, capture_output=True, text=True)
            if res_state.returncode != 0:
                _log(f"Error xprop state: {res_state.stderr}")

            _log(f"Propiedades X11 aplicadas a ventana {wid}")
        except Exception as e:
            _log(f"Error aplicando propiedades X11: {e}")

    def _suspend_video(self):
        if self.is_suspended:
            return
        self.is_suspended = True
        try:
            if self._vlc_player is not None:
                self._vlc_player.set_pause(1)
        except Exception:
            pass
        _log(f"Pantalla {self.screen_index} suspendida (pausa VLC)")
        gc.collect()

    def _resume_video(self):
        if not self.is_suspended:
            return
        self.is_suspended = False
        try:
            if self._vlc_player is not None:
                self._vlc_player.set_pause(0)
                self._vlc_player.play()
        except Exception:
            pass
        _log(f"Pantalla {self.screen_index} reanudada")
        # Reaplicar velocidad tras reanudar.
        QTimer.singleShot(75, self._reapply_speed)

    def _check_maximized_window(self):
        if not self._playback_ready:
            return
        
        self._check_count = getattr(self, "_check_count", 0) + 1
        if self._check_count >= 20:
            self._check_count = 0

        is_maximized = False
        method_ok = False

        try:
            script = f"global.display.focus_window && global.display.focus_window.get_monitor() === {self.screen_index} ? global.display.focus_window.get_maximized() : 0"
            reply = self.gnome_interface.call("Eval", script)
            
            if reply.type() == QDBusMessage.MessageType.ReplyMessage:
                val = str(reply.arguments()[1]).strip('"')
                is_maximized = (val == "3")
                method_ok = True
        except:
            method_ok = False

        if not method_ok:
            if self._x11_detector is not None:
                try:
                    is_maximized = self._x11_detector.is_any_window_maximized()
                    method_ok = True
                except: pass
            
            if not method_ok and self._xprop_failed_count <= 5:
                try:
                    # Usar caché de WM_STATE para reducir subprocess calls
                    now = time.time() * 1000
                    cached_is_max, cached_time = self._wm_state_cache
                    
                    # Si está en caché y no ha expirado, usar valor cacheado
                    if cached_is_max is not None and (now - cached_time) < self._wm_state_cache_ttl_ms:
                        is_maximized = cached_is_max
                    else:
                        # Hacer consulta fresca
                        wid = self._get_active_window_cached()
                        if wid and wid != "0x0":
                            state = subprocess.check_output(["xprop", "-id", wid, "_NET_WM_STATE"], stderr=subprocess.DEVNULL, timeout=0.4).decode()
                            is_maximized = "_NET_WM_STATE_MAXIMIZED_VERT" in state and "_NET_WM_STATE_MAXIMIZED_HORZ" in state
                        self._wm_state_cache = (is_maximized, now)
                    self._xprop_failed_count = 0
                except: 
                    self._xprop_failed_count += 1

        if is_maximized and not self.is_suspended:
            self._maximized_active = True
            self._suspend_video()
        elif not is_maximized:
            self._maximized_active = False
            if self.is_suspended and not self._user_paused:
                self._resume_video()

        self._check_idle_status()


class WallpaperService(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setApplicationName("KomorebiWallpaperService")
        self.setQuitOnLastWindowClosed(False)

        self.players: dict[int, BackgroundPlayer] = {}
        self._monitor_layout_hash = ""

        try:
            self.vlc_instance = BackgroundPlayer._create_vlc_instance()
        except Exception as e:
            self.vlc_instance = None
            _log(f"ERROR inicializando instancia VLC global: {e}")

        env_sync = os.environ.get("KOMOREBI_GNOME_WALLPAPER_SYNC", "1").strip().lower()
        env_mode = os.environ.get("KOMOREBI_GNOME_WALLPAPER_MODE", GNOME_WALLPAPER_DEFAULT_MODE).strip().lower()
        if env_mode not in {"static", "live"}:
            env_mode = GNOME_WALLPAPER_DEFAULT_MODE
        self._gnome_wallpaper_mode = env_mode
        self._gnome_wallpaper_enabled = is_gnome() and env_sync not in {"0", "false", "no", "off"}
        self._gnome_wallpaper_timer: QTimer | None = None
        self._gnome_wallpaper_source_screen = 0
        self._gnome_wallpaper_last_uri: str | None = None
        self._gnome_wallpaper_current_path: Path | None = None
        self._gnome_wallpaper_pending_tries = 0

        self._gnome_original_picture_uri = None
        self._gnome_original_picture_uri_dark = None
        self._gnome_original_picture_options = None
        if self._gnome_wallpaper_enabled:
            self._gnome_original_picture_uri = _gsettings_get("picture-uri")
            if _gsettings_has_key("org.gnome.desktop.background", "picture-uri-dark"):
                self._gnome_original_picture_uri_dark = _gsettings_get("picture-uri-dark")
            self._gnome_original_picture_options = _gsettings_get("picture-options")

        self.server = QLocalServer(self)
        QLocalServer.removeServer(SERVER_NAME)

        self.primary_screen = self.primaryScreen()
        if self.primary_screen:
            self.primary_screen.geometryChanged.connect(self._on_global_screen_change)
        self.screenRemoved.connect(self._on_screen_removed)
        self.screenAdded.connect(self._on_screen_added)

        self._layout_monitor_timer = QTimer(self)
        self._layout_monitor_timer.timeout.connect(self._check_layout_changes)
        self._layout_monitor_timer.start(3000)

        if self.server.listen(SERVER_NAME):
            _log(f"Servidor iniciado en socket: {SERVER_NAME}")
            self.server.newConnection.connect(self._handle_new_connection)
        else:
            _log(f"Error iniciando servidor: {self.server.errorString()}")

        QTimer.singleShot(0, self._autoload_from_config)

    def _compute_monitor_layout_hash(self) -> str:
        inv = _current_monitor_inventory()
        layout_str = "|".join([
            f"{m.get('name', '')}:{m.get('x', 0)},{m.get('y', 0)},{m.get('w', 0)}x{m.get('h', 0)}"
            for m in sorted(inv, key=lambda x: x.get('index', 0))
        ])
        import hashlib
        return hashlib.md5(layout_str.encode()).hexdigest()

    def _check_layout_changes(self):
        current_hash = self._compute_monitor_layout_hash()
        
        if not self._monitor_layout_hash:
            self._monitor_layout_hash = current_hash
            return
            
        if current_hash != self._monitor_layout_hash:
            _log(f" Layout de monitores cambió: {self._monitor_layout_hash[:8]} -> {current_hash[:8]}")
            self._monitor_layout_hash = current_hash
            _xrandr_monitors(force_refresh=True)
            self._cleanup_orphaned_players()
            QTimer.singleShot(1500, self._autoload_from_config)

    def _cleanup_orphaned_players(self):
        inv = _current_monitor_inventory()
        valid_indices = {m['index'] for m in inv}
        valid_names = {m['name'] for m in inv if m.get('name')}
        
        to_remove = []
        for idx, player in list(self.players.items()):
            if idx not in valid_indices:
                to_remove.append(idx)
                continue
            if player.screen_name and player.screen_name not in valid_names:
                to_remove.append(idx)
                continue
        
        for idx in to_remove:
            _log(f" Eliminando player huérfano {idx}")
            self._stop_player(idx, persist_disable=False)

    def _resolve_config_entry_to_screen_index(self, entry: dict) -> int | None:
        entry = _normalize_monitor_entry(entry)
        inv = _current_monitor_inventory()
        if not inv:
            return None

        name = entry.get("screen_name")
        if name:
            for m in inv:
                if m.get("name") == name:
                    return int(m["index"])

        try:
            idx = int(entry.get("screen", 0))
        except Exception:
            idx = 0
        if 0 <= idx < len(inv):
            return idx
        return None

    def _autoload_from_config(self):
        data = _load_config()
        monitors = [_normalize_monitor_entry(m) for m in (data.get("monitors") or []) if isinstance(m, dict)]
        if not monitors:
            return

        _xrandr_monitors(force_refresh=True)
        inv = _current_monitor_inventory()
        valid_indices = {m['index'] for m in inv}

        started = 0
        for entry in monitors:
            if not entry.get("enabled", True):
                continue
            video_path = entry.get("video_path")
            if not video_path or not os.path.exists(str(video_path)):
                continue

            resolved = self._resolve_config_entry_to_screen_index(entry)
            if resolved is None:
                continue
                
            if resolved not in valid_indices:
                _log(f" Saltando monitor {resolved}: no existe en layout actual")
                continue

            if resolved in self.players:
                _log(f" Recreando player {resolved}")
                self._stop_player(resolved, persist_disable=False)

            self._start_player(
                str(video_path),
                int(resolved),
                bool(entry.get("pause_on_max", False)),
                int(entry.get("volume", 0)),
                bool(entry.get("paused", False)),
                persist=False,
            )
            started += 1

        if started:
            _log(f"✅ Autoload: {started} player(s) iniciados")

    def _on_screen_added(self, screen):
        try:
            _log(f"➕ Pantalla conectada: {screen.name()}")
        except Exception:
            _log("➕ Pantalla conectada")
        
        _xrandr_monitors(force_refresh=True)
        self._monitor_layout_hash = self._compute_monitor_layout_hash()
        QTimer.singleShot(2000, self._autoload_from_config)

    def _start_gnome_wallpaper_sync(self):
        if not self._gnome_wallpaper_enabled:
            return
        if self._gnome_wallpaper_timer is None:
            self._gnome_wallpaper_timer = QTimer(self)
            self._gnome_wallpaper_timer.timeout.connect(self._tick_gnome_wallpaper)

        try:
            _gsettings_set("picture-options", "zoom")
        except Exception:
            pass

        QTimer.singleShot(GNOME_WALLPAPER_SYNC_STARTUP_DELAY_MS, self._tick_gnome_wallpaper)

        if self._gnome_wallpaper_mode == "live":
            if not self._gnome_wallpaper_timer.isActive():
                self._gnome_wallpaper_timer.start(GNOME_WALLPAPER_SYNC_INTERVAL_MS)
                _log("GNOME wallpaper sync: iniciado (live)")
        else:
            _log("GNOME wallpaper sync: iniciado (static)")

    def _stop_gnome_wallpaper_sync(self, restore: bool = True):
        if self._gnome_wallpaper_timer is not None and self._gnome_wallpaper_timer.isActive():
            self._gnome_wallpaper_timer.stop()
            _log("GNOME wallpaper sync: detenido")
        if restore:
            self._restore_gnome_wallpaper()

    def _restore_gnome_wallpaper(self):
        if not self._gnome_wallpaper_enabled:
            return
        if self._gnome_original_picture_uri:
            _gsettings_set_schema("org.gnome.desktop.background", "picture-uri", self._gnome_original_picture_uri)
        if self._gnome_original_picture_uri_dark and _gsettings_has_key("org.gnome.desktop.background", "picture-uri-dark"):
            _gsettings_set_schema("org.gnome.desktop.background", "picture-uri-dark", self._gnome_original_picture_uri_dark)
        if self._gnome_original_picture_options:
            _gsettings_set_schema("org.gnome.desktop.background", "picture-options", self._gnome_original_picture_options)
        try:
            if self._gnome_wallpaper_current_path and self._gnome_wallpaper_current_path.exists():
                self._gnome_wallpaper_current_path.unlink()
        except Exception:
            pass

    def _request_gnome_wallpaper_update(self, source_screen: int | None = None):
        if not self._gnome_wallpaper_enabled:
            return
        if source_screen is not None:
            self._gnome_wallpaper_source_screen = int(source_screen)
        self._gnome_wallpaper_pending_tries = 0
        QTimer.singleShot(0, self._tick_gnome_wallpaper)

    def _gnome_shell_eval(self, script: str) -> tuple[bool, str | None]:
        """Ejecuta JS en GNOME Shell via DBus Eval (best-effort)."""
        try:
            msg = QDBusMessage.createMethodCall(
                "org.gnome.Shell",
                "/org/gnome/Shell",
                "org.gnome.Shell",
                "Eval",
            )
            msg.setArguments([script])
            reply = QDBusConnection.sessionBus().call(msg)
            if reply.type() != QDBusMessage.MessageType.ReplyMessage:
                return False, None
            args = reply.arguments()
            if len(args) >= 2 and args[0] is True:
                return True, str(args[1])
        except Exception:
            pass
        return False, None

    def _force_gnome_background_refresh(self):
        """Fuerza refresh del background en GNOME Shell (para Overview)."""
        scripts = [
            "try { const Main = imports.ui.main; Main.layoutManager._bgManagers.forEach(m => { try { m._updateBackground(); } catch(e) {} }); true; } catch(e) { false; }",
            "try { const Main = imports.ui.main; Main.layoutManager._bgManagers.forEach(m => { try { m._createBackgroundActor(); } catch(e) {} }); true; } catch(e) { false; }",
        ]
        for s in scripts:
            ok, _ = self._gnome_shell_eval(s)
            if ok:
                return

    def _tick_gnome_wallpaper(self):
        player = self.players.get(self._gnome_wallpaper_source_screen)
        if player is None and self.players:
            self._gnome_wallpaper_source_screen = sorted(self.players.keys())[0]
            player = self.players.get(self._gnome_wallpaper_source_screen)
        if player is None:
            return
        if player.is_suspended:
            return

        geo = player.geometry()
        src_w = max(1, int(geo.width()))
        src_h = max(1, int(geo.height()))

        max_dim = int(GNOME_WALLPAPER_MAX_DIMENSION)
        scale = min(1.0, max_dim / max(src_w, src_h))
        width = max(1, int(src_w * scale))
        height = max(1, int(src_h * scale))

        GNOME_WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = GNOME_WALLPAPER_DIR / f"{GNOME_WALLPAPER_BASENAME}-{ts}.jpg"

        ok = player.snapshot_to_file(path, width, height)
        if not ok:
            self._gnome_wallpaper_pending_tries += 1
            if self._gnome_wallpaper_pending_tries <= 12:
                QTimer.singleShot(350, self._tick_gnome_wallpaper)
            else:
                _log("GNOME wallpaper sync: no se pudo tomar snapshot (VLC sin frame)")
            return

        uri = path.resolve().as_uri()
        ok_bg = _gsettings_set("picture-uri", uri)
        ok_bg_dark = False
        if _gsettings_has_key("org.gnome.desktop.background", "picture-uri-dark"):
            ok_bg_dark = _gsettings_set("picture-uri-dark", uri)

        ok_ss = _gsettings_set_schema("org.gnome.desktop.screensaver", "picture-uri", uri)
        ok_ss_dark = False
        if _gsettings_has_key("org.gnome.desktop.screensaver", "picture-uri-dark"):
            ok_ss_dark = _gsettings_set_schema("org.gnome.desktop.screensaver", "picture-uri-dark", _gsettings_quote(uri))

        try:
            now_uri = _gsettings_get("picture-uri")
            _log(f"GNOME picture-uri actual: {now_uri}")
        except Exception:
            pass

        if ok_bg or ok_bg_dark or ok_ss or ok_ss_dark:
            self._force_gnome_background_refresh()

        self._gnome_wallpaper_last_uri = uri
        _log(f"GNOME wallpaper sync: actualizado -> {uri}")

        cleanup_counter = getattr(self, "_cleanup_counter", 0) + 1
        if cleanup_counter >= 10:
            _cleanup_old_snapshots(GNOME_WALLPAPER_DIR, max_age_seconds=300)
            cleanup_counter = 0
        setattr(self, "_cleanup_counter", cleanup_counter)

        try:
            if self._gnome_wallpaper_current_path and self._gnome_wallpaper_current_path.exists():
                self._gnome_wallpaper_current_path.unlink()
        except Exception:
            pass
        self._gnome_wallpaper_current_path = path

    def _on_global_screen_change(self, geo):
        _log("Cambio de geometría global detectado. Verificando players...")
        for player in self.players.values():
            player._check_screen_alive()

    def _on_screen_removed(self, screen):
        _log(f"➖ Pantalla desconectada: {screen.name()}")
        _xrandr_monitors(force_refresh=True)
        self._monitor_layout_hash = self._compute_monitor_layout_hash()
        
        to_remove = []
        for idx, player in list(self.players.items()):
            if player.screen_name == screen.name():
                to_remove.append(idx)
            elif player.windowHandle() and player.windowHandle().screen() == screen:
                to_remove.append(idx)

        for idx in to_remove:
            _log(f" Cerrando player {idx}")
            self._stop_player(idx, persist_disable=False)

        QTimer.singleShot(500, self._cleanup_orphaned_players)

    def _handle_new_connection(self):
        socket = self.server.nextPendingConnection()
        socket.readyRead.connect(lambda: self._read_client_message(socket))
        socket.disconnected.connect(socket.deleteLater)

    def _read_client_message(self, socket):
        try:
            data = socket.readAll().data()
            message = json.loads(data.decode("utf-8"))
            _log(f"Mensaje recibido: {message}")
            self._process_command(message)
        except Exception as e:
            _log(f"Error leyendo mensaje: {e}")

    def _process_command(self, cmd):
        action = cmd.get("action")
        screen = cmd.get("screen", 0)

        if action == "play":
            self._start_player(
                cmd.get("video_path"),
                screen,
                cmd.get("pause_on_max", False),
                cmd.get("volume", 0),
                cmd.get("paused", False),
                persist=True,
            )
        elif action == "stop":
            self._stop_player(screen)
        elif action == "update":
            self._update_players(cmd)
        elif action == "ping":
            _log("Ping recibido: servicio activo")
        elif action == "status":
 
            status = {
                "service": "alive",
                "players_count": len(self.players),
                "players": {
                    str(idx): {
                        "screen_index": player.screen_index,
                        "screen_name": player.screen_name,
                        "paused": player.is_suspended or player._user_paused,
                        "volume": player.volume,
                        "video_path": player.video_path,
                        "rate": getattr(player, "speed", 1.0),
                    }
                    for idx, player in self.players.items()
                }
            }
            _log(f"Status: {json.dumps(status)}")
        elif action == "quit":
            self._stop_gnome_wallpaper_sync(restore=True)
            self.quit()

    def _update_players(self, cmd: dict) -> None:
        """Actualiza settings en caliente sin reiniciar players.

        Formatos soportados:
        - {action:update, screen:N, volume:int?, paused:bool?, pause_on_max:bool?}
        - {action:update, per_screen:{"0":{...},"1":{...}}, pause_on_max:bool?}
        """
        per_screen = cmd.get("per_screen")
        global_pause_on_max = cmd.get("pause_on_max", None)

        def _apply(idx: int, payload: dict):
            player = self.players.get(idx)
            if not player:
                return
            player.apply_runtime_settings(
                volume=payload.get("volume", None),
                paused=payload.get("paused", None),
                pause_on_max=(global_pause_on_max if global_pause_on_max is not None else payload.get("pause_on_max", None)),
                speed=payload.get("speed", None),
            )
            try:
                _upsert_monitor_config(
                    screen_index=int(idx),
                    screen_name=getattr(player, "screen_name", None),
                    video_path=str(getattr(player, "video_path", "")),
                    volume=int(getattr(player, "volume", 0)),
                    pause_on_max=bool(getattr(player, "pause_on_max", False)),
                    paused=bool(getattr(player, "paused", False)),
                    speed=float(getattr(player, "speed", 1.0)),
                )
            except Exception:
                pass

        if isinstance(per_screen, dict):
            for k, payload in per_screen.items():
                try:
                    idx = int(k)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    _apply(idx, payload)
            return

        try:
            idx = int(cmd.get("screen", 0))
        except Exception:
            idx = 0

        payload = {
            "volume": cmd.get("volume", None),
            "paused": cmd.get("paused", None),
            "pause_on_max": cmd.get("pause_on_max", None),
            "speed": cmd.get("speed", None),
        }

        if idx == -1:
            for sidx in list(self.players.keys()):
                _apply(int(sidx), payload)
        else:
            _apply(idx, payload)

    def _start_player(self, video_path, screen_index, pause_on_max, volume, paused, persist: bool = True):
        start_position = None
        old_player = self.players.get(screen_index)
        if old_player is not None:
            try:
                if old_player._vlc_player is not None:
                    start_position = old_player._vlc_player.get_position()
            except Exception:
                start_position = None

        _log(f"Iniciando player VLC en pantalla {screen_index}")

        if not video_path or not os.path.exists(video_path):
            _log(f"ERROR: El archivo de video no existe: {video_path}")
            return

        def _create_and_show():
            player = BackgroundPlayer(
                video_path,
                pause_on_max,
                screen_index,
                volume,
                paused,
                vlc_instance=self.vlc_instance,
                start_position=start_position,
            )
            self.players[screen_index] = player
            player.show()

            if persist:
                try:
                    _upsert_monitor_config(
                        screen_index=int(screen_index),
                        screen_name=player.screen_name,
                        video_path=str(video_path),
                        volume=int(volume),
                        pause_on_max=bool(pause_on_max),
                        paused=bool(paused),
                    )
                except Exception:
                    pass

            if self._gnome_wallpaper_enabled:
                if 0 in self.players:
                    self._gnome_wallpaper_source_screen = 0
                else:
                    self._gnome_wallpaper_source_screen = screen_index
                self._start_gnome_wallpaper_sync()
                self._request_gnome_wallpaper_update(self._gnome_wallpaper_source_screen)

        if old_player is not None:
            try:
                # Pausar el player antiguo para congelar su último frame visual.
                # Luego destruirlo suavemente con fade.
                try:
                    if old_player._vlc_player is not None:
                        old_player._vlc_player.set_pause(1)
                except Exception:
                    pass

                old_player.setWindowOpacity(1.0)
                anim = QPropertyAnimation(old_player, b"windowOpacity")
                anim.setDuration(250)
                anim.setStartValue(1.0)
                anim.setEndValue(0.0)
                anim.setEasingCurve(QEasingCurve.InOutQuad)

                def _after_fade():
                    try:
                        self._stop_player(screen_index, persist_disable=False)
                    finally:
                        _create_and_show()

                anim.finished.connect(_after_fade)
                anim.start()
                setattr(old_player, "_swap_fade_anim", anim)
                return
            except Exception:
                self._stop_player(screen_index, persist_disable=False)
                _create_and_show()
                return

        _create_and_show()

    def _stop_player(self, screen_index, *, persist_disable: bool = True):
        if screen_index in self.players:
            _log(f"Deteniendo player en pantalla {screen_index}")
            player = self.players[screen_index]

            try:
                if player._vlc_player is not None:
                    player._vlc_player.stop()
            except Exception:
                pass

            player.close()
            player.deleteLater()
            del self.players[screen_index]

            if persist_disable:
                try:
                    _disable_monitor_config(screen_index=int(screen_index), screen_name=getattr(player, "screen_name", None))
                except Exception:
                    pass

            if self._gnome_wallpaper_enabled and screen_index == self._gnome_wallpaper_source_screen:
                self._stop_gnome_wallpaper_sync(restore=True)

            try:
                if player._vlc_player is not None:
                    player._vlc_player.release()
                    player._vlc_player = None
            except Exception:
                pass

            try:
                if getattr(player, "_vlc_media", None) is not None:
                    player._vlc_media.release()
                    player._vlc_media = None
            except Exception:
                pass
    gc.collect()


def send_command_to_server(args):
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)

    if socket.waitForConnected(1000):
        if args.quit_service:
            msg = {"action": "quit"}
        elif args.stop:
            msg = {"action": "stop", "screen": args.screen}
        else:
            msg = {
                "action": "play",
                "video_path": args.video_path,
                "screen": args.screen,
                "pause_on_max": args.pause_on_max,
                "volume": args.volume,
                "paused": args.paused,
            }

        data = json.dumps(msg).encode("utf-8")
        socket.write(data)
        socket.flush()
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        _log("Comando enviado al servidor existente.")
        return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("video_path", nargs="?", help="Ruta al archivo de video")
    parser.add_argument("--pause-on-max", action="store_true", help="Pausar si hay ventana maximizada")
    parser.add_argument("--paused", action="store_true", help="Iniciar pausado")
    parser.add_argument("--screen", type=int, default=0, help="Índice de la pantalla")
    parser.add_argument("--volume", type=int, default=0, help="Volumen (0-100)")
    parser.add_argument("--stop", action="store_true", help="Detener reproducción en la pantalla indicada")
    parser.add_argument("--quit-service", action="store_true", help="Detener todo el servicio")
    args = parser.parse_args(argv)

    try:
        os.nice(19)
    except Exception:
        pass

    session, is_gnome_env = check_session_type()

    if send_command_to_server(args):
        return 0

    lock_path = Path("/tmp/komorebi.lock")
    lock_file = open(lock_path, "w")

    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX)

        if send_command_to_server(args):
            return 0

        if args.stop or args.quit_service:
            _log("No hay servicio corriendo para detener.")
            return 0

        if not args.video_path:
            _log("Iniciando servicio sin comando play: se intentará autoload desde config...")

        _log("Iniciando nuevo servicio de wallpapers...")
        qt_argv = [sys.argv[0]] + (argv if argv is not None else sys.argv[1:])
        app = WallpaperService(qt_argv)

        if args.video_path:
            app._process_command(
                {
                    "action": "play",
                    "video_path": args.video_path,
                    "screen": args.screen,
                    "pause_on_max": args.pause_on_max,
                    "volume": args.volume,
                    "paused": args.paused,
                }
            )

        def handle_term(*_):
            app.quit()

        signal.signal(signal.SIGTERM, handle_term)

        return app.exec()

    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    sys.exit(main())

