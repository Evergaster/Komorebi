import os
import shutil
import sys
import json
import time
import psutil # Para batería
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QScrollArea, QGridLayout, 
                             QLabel, QFrame, QStackedWidget, QMessageBox, QCheckBox, 
                             QApplication, QSlider, QProgressBar, QSystemTrayIcon, QMenu, QStyle, QSizePolicy, QLineEdit, QComboBox, QInputDialog)
from PySide6.QtCore import Qt, QUrl, QSize, QThread, Signal, QObject, QThreadPool, QRunnable, Slot, QTimer
from PySide6.QtGui import QPixmap, QImage, QGuiApplication, QAction, QDesktopServices, QIcon, QPalette, QColor
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from src.engine import WallpaperEngine


def _get_xdg_videos_dir() -> str:
    """Devuelve el directorio de vídeos del usuario según XDG/GNOME.

    - Preferido: `xdg-user-dir VIDEOS`
    - Alternativa: ~/.config/user-dirs.dirs (XDG_VIDEOS_DIR)
    - Fallback: carpeta existente (~/Vídeos o ~/Videos) o ~/Videos
    """

    try:
        p = subprocess.run(
            ["xdg-user-dir", "VIDEOS"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        out = (p.stdout or "").strip()
        if p.returncode == 0 and out:
            return os.path.expanduser(out)
    except Exception:
        pass


    try:
        cfg = os.path.expanduser("~/.config/user-dirs.dirs")
        if os.path.exists(cfg):
            with open(cfg, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("XDG_VIDEOS_DIR="):
                        val = line.split("=", 1)[1].strip().strip('"')
                        val = val.replace("$HOME", os.path.expanduser("~"))
                        if val:
                            return os.path.expanduser(val)
    except Exception:
        pass


    home = Path.home()
    candidates = [home / "Vídeos", home / "Videos"]
    for c in candidates:
        try:
            if c.exists() and c.is_dir():
                return str(c)
        except Exception:
            pass

    return str(home / "Videos")

THEMES = {
    "dark": {
        "window": "#1e1e1e",
        "text": "#ffffff",
        "panel": "#252525",
        "panel_border": "#333",
        "accent": "#3d5afe",
        "accent_hover": "#5f73ff",
        "text_secondary": "#cccccc",
        "sidebar": "#121212",
        "sidebar_border": "#222",
        "card_bg": "#252525",
        "card_hover": "#2a2a2a",
        "monitor_bg": "#000",
        "monitor_border": "#444",
        "monitor_checked": "#00e5ff",
        "danger": "#d32f2f",
        "danger_hover": "#b71c1c"
    },
    "light": {
        "window": "#f0f2f5",
        "text": "#1a1a1a",
        "panel": "#ffffff",
        "panel_border": "#d1d5db",
        "accent": "#3d5afe",
        "accent_hover": "#5f73ff",
        "text_secondary": "#4b5563",
        "sidebar": "#ffffff",
        "sidebar_border": "#e5e7eb",
        "card_bg": "#ffffff",
        "card_hover": "#f9fafb",
        "monitor_bg": "#e5e7eb",
        "monitor_border": "#9ca3af",
        "monitor_checked": "#00b0ff",
        "danger": "#dc2626",
        "danger_hover": "#b91c1c"
    }
}

class ThumbnailWorker(QRunnable):
    def __init__(self, video_path, engine, signaller):
        super().__init__()
        self.video_path = video_path
        self.engine = engine
        self.signaller = signaller

    def run(self):
        thumb_path = self.engine.get_thumbnail(self.video_path)
        self.signaller.finished.emit(thumb_path if thumb_path else "")

class Signaller(QObject):
    finished = Signal(str)

class VideoCard(QFrame):
    def __init__(self, file_path, on_click, on_select, engine, thread_pool, colors):
        super().__init__()
        self.path = file_path
        self.on_click = on_click
        self.on_select = on_select
        self.engine = engine
        self.thread_pool = thread_pool
        self.colors = colors
        
        self.setFixedSize(180, 170) # Reducido de 220x200
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {self.colors['card_bg']};
                border-radius: 12px;
                border: 1px solid {self.colors['panel_border']};
            }}
            QFrame:hover {{ border: 1px solid {self.colors['accent']}; background-color: {self.colors['card_hover']}; }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(166, 100) # Reducido de 200x120
        self.thumbnail.setStyleSheet(f"background-color: {self.colors['monitor_bg']}; border-radius: 8px; border: none;")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._load_thumbnail()
            
        layout.addWidget(self.thumbnail)
        
        name = os.path.basename(file_path)
        lbl = QLabel(name[:22] + "..." if len(name) > 22 else name)
        lbl.setStyleSheet(f"color: {self.colors['text']}; font-weight: bold; border: none; font-size: 11px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        
        btn = QPushButton("Aplicar")
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.colors['accent']}; 
                color: white; 
                border-radius: 5px; 
                padding: 6px; 
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {self.colors['accent_hover']};
            }}
        """)
        btn.clicked.connect(lambda: self._safe_apply(on_click))
        layout.addWidget(btn)

    def _load_thumbnail(self):
        thumb_path = self.engine.get_thumbnail_path(self.path)
        if thumb_path and os.path.exists(thumb_path):
            self._set_pixmap(thumb_path)
        else:
            self.thumbnail.setText("⏳")
            self.thumbnail.setStyleSheet(self.thumbnail.styleSheet() + " font-size: 32px;")
            
            self.signaller = Signaller()
            self.signaller.finished.connect(self._on_thumb_ready)
            
            worker = ThumbnailWorker(self.path, self.engine, self.signaller)
            self.thread_pool.start(worker)

    def _on_thumb_ready(self, path):
        if path:
            self._set_pixmap(path)
        else:
            self.thumbnail.setText("🎬")

    def _set_pixmap(self, path):
        pixmap = QPixmap(path)
        self.thumbnail.setPixmap(pixmap.scaled(166, 100, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
        self.thumbnail.setText("") # Clear text

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._safe_apply(self.on_click)
            return
        super().mousePressEvent(event)

    def _show_context_menu(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #252525; color: white; border: 1px solid #444; }"
            "QMenu::item { padding: 6px 18px; }"
            "QMenu::item:selected { background-color: #3d5afe; }"
        )

        act_open_folder = QAction("Abrir carpeta", self)
        act_rename = QAction("Renombrar", self)
        act_delete = QAction("Eliminar", self)

        act_open_folder.triggered.connect(lambda: self.on_select({"action": "open_folder", "path": self.path}))
        act_rename.triggered.connect(lambda: self.on_select({"action": "rename", "path": self.path}))
        act_delete.triggered.connect(lambda: self.on_select({"action": "delete", "path": self.path}))

        menu.addAction(act_open_folder)
        menu.addAction(act_rename)
        menu.addSeparator()
        menu.addAction(act_delete)

        menu.exec(event.globalPos())
    
    def _safe_apply(self, callback):
        """Aplica wallpaper con manejo de errores"""
        try:
            callback(self.path)
        except RuntimeError as e:
            QMessageBox.critical(
                None,
                "Incompatibilidad Detectada",
                str(e),
                QMessageBox.StandardButton.Ok
            )
        except Exception as e:
            QMessageBox.warning(
                None,
                "Error al aplicar fondo",
                f"No se pudo aplicar el fondo:\n{e}",
                QMessageBox.StandardButton.Ok
            )

class ImportWorker(QThread):
    progress = Signal(int)
    finished = Signal(int)

    def __init__(self, folder_path, target_dir):
        super().__init__()
        self.folder_path = folder_path
        self.target_dir = target_dir

    def run(self):
        valid_extensions = {".mp4", ".webm", ".mkv", ".avi", ".mov"}
        files_to_copy = []
        for root, dirs, files in os.walk(self.folder_path):
            for file in files:
                if os.path.splitext(file)[1].lower() in valid_extensions:
                    files_to_copy.append(os.path.join(root, file))
        
        total = len(files_to_copy)
        count = 0
        if total == 0:
            self.finished.emit(0)
            return

        for i, src_path in enumerate(files_to_copy):
            dest_path = os.path.join(self.target_dir, os.path.basename(src_path))
            if not os.path.exists(dest_path):
                try:
                    shutil.copy(src_path, dest_path)
                    count += 1
                except Exception:
                    pass
            self.progress.emit(int((i + 1) / total * 100))
            
        self.finished.emit(count)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        QApplication.setStyle("Fusion")
        
        self.setWindowTitle("Komorebi")
        self.resize(1100, 750) # Aumentado para mejor visualización
        self.setMinimumSize(900, 650)
        self._center_window()
        
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self.rearrange_grid)

        icon_path = self._get_resource_path("icons/Komorebi.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.thread_pool = QThreadPool()
        
        try:
            self.engine = WallpaperEngine()
        except FileNotFoundError as e:
            QMessageBox.critical(
                self,
                "Dependencias Faltantes",
                f"{e}\n\nLa aplicación se cerrará.",
                QMessageBox.StandardButton.Ok
            )
            sys.exit(1)
        
        self.video_dir = os.path.join(_get_xdg_videos_dir(), "Komorebi")
        os.makedirs(self.video_dir, exist_ok=True)

        self._meta_cache_path = os.path.join(os.path.expanduser("~/.cache/komorebi"), "video_meta.json")
        self._video_meta_cache = self._load_video_meta_cache()
        
        self.config_file = os.path.expanduser("~/.config/komorebi/config.json")
        self.config = self._load_config()
        self.config.setdefault("monitor_settings", {})
        self.config.setdefault("shuffle_enabled", False)
        self.config.setdefault("shuffle_interval_min", 10)
        self.config.setdefault("shuffle_apply_all", True)

        # No persistir "paused" entre sesiones si no hay power-save.
        if not bool(self.config.get("power_save", False)) and bool(self.config.get("paused", False)):
            self.config["paused"] = False
            mons = self.config.get("monitors")
            if isinstance(mons, list):
                for m in mons:
                    if isinstance(m, dict) and "paused" in m:
                        m["paused"] = False
            self._save_config()

        if self.config.get("autostart", False):
            self._manage_autostart(True)

        self.current_theme_name = self.config.get("theme", "dark")
        self.colors = THEMES.get(self.current_theme_name, THEMES["dark"])
        
        self.selected_screen = 0 # Pantalla seleccionada por defecto

        QGuiApplication.instance().screenAdded.connect(self._on_screens_changed)
        QGuiApplication.instance().screenRemoved.connect(self._on_screens_changed)

        self._init_tray()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(200)
        
        side_layout = QVBoxLayout(self.sidebar)
        
        self.btn_gallery = QPushButton("🗂 Galería")
        self.btn_config = QPushButton("⚙ Configuración")
        self.btn_about = QPushButton("ℹ Acerca de")
        
        side_layout.addWidget(self.btn_gallery)
        side_layout.addWidget(self.btn_config)
        side_layout.addWidget(self.btn_about)
        
        side_layout.addStretch()
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self.apply_theme(self.current_theme_name)

        self.btn_gallery.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.btn_config.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        self.btn_about.clicked.connect(lambda: self.stack.setCurrentIndex(2))

        self.battery_timer = QTimer(self)
        self.battery_timer.timeout.connect(self._check_battery)
        self.battery_timer.start(10000) # Check every 10 seconds

        self.shuffle_timer = QTimer(self)
        self.shuffle_timer.timeout.connect(self._shuffle_tick)
        self._ensure_shuffle_timer()

    def _ensure_shuffle_timer(self):
        enabled = bool(self.config.get("shuffle_enabled", False))
        interval_min = int(self.config.get("shuffle_interval_min", 10) or 10)
        interval_min = max(1, min(240, interval_min))
        if enabled:
            self.shuffle_timer.start(interval_min * 60 * 1000)
        else:
            self.shuffle_timer.stop()

    def _list_videos(self) -> list[str]:
        exts = {".mp4", ".mkv", ".mov", ".webm", ".avi"}
        try:
            return [os.path.join(self.video_dir, f) for f in os.listdir(self.video_dir) if os.path.splitext(f)[1].lower() in exts]
        except Exception:
            return []

    def _apply_wallpaper_to_screen(self, video_path: str, screen_idx: int):
        pause_on_max = self.config.get("pause_on_max", False)
        vol_i = self._get_effective_volume_for_screen(screen_idx)
        paused_i = self._get_effective_paused_for_screen(screen_idx)
        self.engine.play(video_path, screen_idx, pause_on_max, vol_i, paused_i)
        if "wallpapers" not in self.config:
            self.config["wallpapers"] = {}
        self.config["wallpapers"][str(screen_idx)] = video_path
        self._save_config()
        if hasattr(self, 'monitor_widgets'):
            self._update_monitor_button(screen_idx, video_path)

    def _apply_wallpaper_to_all(self, video_path: str):
        for i in range(self.engine.get_screen_count()):
            self._apply_wallpaper_to_screen(video_path, i)

    def _shuffle_tick(self):
        if not bool(self.config.get("shuffle_enabled", False)):
            return
        videos = [p for p in self._list_videos() if os.path.exists(p)]
        if not videos:
            return
        import random

        choice = random.choice(videos)
        if bool(self.config.get("shuffle_apply_all", True)):
            self._apply_wallpaper_to_all(choice)
        else:
            self._apply_wallpaper_to_screen(choice, int(self.selected_screen))

    def _center_window(self):
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            center = geo.center()
            frame_geo = self.frameGeometry()
            frame_geo.moveCenter(center)
            self.move(frame_geo.topLeft())

    def _get_resource_path(self, relative_path):
        if hasattr(sys, '_MEIPASS'):
            return os.path.join(sys._MEIPASS, relative_path)
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), relative_path)

    def apply_theme(self, theme_name):
        self.current_theme_name = theme_name
        self.colors = THEMES[theme_name]
        self.config["theme"] = theme_name
        self._save_config()
        
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(self.colors["window"]))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(self.colors["text"]))
        palette.setColor(QPalette.ColorRole.Base, QColor(self.colors["panel"]))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(self.colors["sidebar"]))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(self.colors["text"]))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(self.colors["window"]))
        palette.setColor(QPalette.ColorRole.Text, QColor(self.colors["text"]))
        palette.setColor(QPalette.ColorRole.Button, QColor(self.colors["panel"]))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(self.colors["text"]))
        palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        palette.setColor(QPalette.ColorRole.Link, QColor(self.colors["accent"]))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(self.colors["accent"]))
        palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
        QApplication.instance().setPalette(palette)

        self.sidebar.setStyleSheet(f"background-color: {self.colors['sidebar']}; border-right: 1px solid {self.colors['sidebar_border']};")

        btn_style = f"QPushButton {{ color: {self.colors['text']}; text-align: left; padding: 10px; border: none; font-size: 14px; }} QPushButton:hover {{ background-color: {self.colors['card_hover']}; }}"
        self.btn_gallery.setStyleSheet(btn_style)
        self.btn_config.setStyleSheet(btn_style)
        self.btn_about.setStyleSheet(btn_style)

        current_idx = self.stack.currentIndex()
        if current_idx < 0: current_idx = 0

        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()

        self._init_gallery()
        self._init_config()
        self._init_about()
        
        self.stack.setCurrentIndex(current_idx)
        
        self.restore_wallpapers()

    def _init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        icon_path = self._get_resource_path("icons/Komorebi.png")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            self.tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        
        tray_menu = QMenu()
        tray_menu.setStyleSheet("QMenu { background-color: #252525; color: white; border: 1px solid #444; } QMenu::item { padding: 5px 20px; } QMenu::item:selected { background-color: #3d5afe; }")
        
        action_open = QAction("Abrir Panel", self)
        action_open.triggered.connect(self.show)
        tray_menu.addAction(action_open)
        
        action_pause = QAction("Pausar/Reanudar Todo", self)
        action_pause.triggered.connect(self._toggle_global_pause)
        tray_menu.addAction(action_pause)
        
        tray_menu.addSeparator()
        
        action_quit = QAction("Salir Totalmente", self)
        action_quit.triggered.connect(self.quit_all)
        tray_menu.addAction(action_quit)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def closeEvent(self, event):
        if self.tray_icon.isVisible():
            QMessageBox.information(self, "Komorebi", 
                                  "La aplicación seguirá ejecutándose en la bandeja del sistema.\nPara cerrar completamente, usa la opción 'Salir' del icono.")
            self.hide()
            event.ignore()
        else:
            event.accept()

    def _check_battery(self):
        if not self.config.get("power_save", False):
            return
            
        try:
            battery = psutil.sensors_battery()
            if battery:
                plugged = battery.power_plugged
                was_battery_paused = self.config.get("battery_paused", False)
                
                if not plugged and not was_battery_paused:
                    self.config["battery_paused"] = True
                    self.engine.update_settings(self.config)
                elif plugged and was_battery_paused:
                    self.config["battery_paused"] = False
                    self.engine.update_settings(self.config)
        except:
            pass

    def _toggle_global_pause(self):
        current_pause = self.config.get("paused", False)
        self.config["paused"] = not current_pause
        self._save_config()
        self.engine.update_settings(self.config)

    def _load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {"pause_on_max": False}

    def _save_config(self):
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f)

    def _load_video_meta_cache(self) -> dict:
        try:
            os.makedirs(os.path.dirname(self._meta_cache_path), exist_ok=True)
            if os.path.exists(self._meta_cache_path):
                with open(self._meta_cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _save_video_meta_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._meta_cache_path), exist_ok=True)
            with open(self._meta_cache_path, "w", encoding="utf-8") as f:
                json.dump(self._video_meta_cache, f)
        except Exception:
            pass

    def _ffprobe_video_meta(self, path: str) -> dict | None:
        if not shutil.which("ffprobe"):
            return None
        try:
            st = os.stat(path)
            key = f"{path}|{int(st.st_mtime)}|{int(st.st_size)}"
            cached = self._video_meta_cache.get(key)
            if isinstance(cached, dict):
                return cached

            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,duration",
                "-of",
                "json",
                path,
            ]
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=2)
            j = json.loads(out)
            streams = j.get("streams") or []
            if not streams:
                return None
            s0 = streams[0]
            meta = {
                "width": int(float(s0.get("width") or 0)),
                "height": int(float(s0.get("height") or 0)),
                "duration": float(s0.get("duration") or 0.0),
            }
            self._video_meta_cache[key] = meta
            self._save_video_meta_cache()
            return meta
        except Exception:
            return None

    def _handle_card_action(self, payload):
        if not isinstance(payload, dict):
            return

        action = payload.get("action")
        path = payload.get("path")
        if not action or not path:
            return

        if action == "open_folder":
            folder = os.path.dirname(path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            return

        if action == "rename":
            base = os.path.basename(path)
            new_name, ok = QInputDialog.getText(self, "Renombrar", "Nuevo nombre:", text=base)
            if not ok:
                return
            new_name = (new_name or "").strip()
            if not new_name:
                return
            new_path = os.path.join(os.path.dirname(path), new_name)
            if os.path.exists(new_path):
                QMessageBox.warning(self, "Renombrar", "Ya existe un archivo con ese nombre.")
                return
            try:
                os.rename(path, new_path)
                self._rewrite_wallpaper_paths(path, new_path)
                self.refresh_grid()
                self.restore_wallpapers()
            except Exception as e:
                QMessageBox.warning(self, "Renombrar", f"No se pudo renombrar:\n{e}")
            return

        if action == "delete":
            resp = QMessageBox.question(self, "Eliminar", f"¿Eliminar este video?\n\n{os.path.basename(path)}")
            if resp != QMessageBox.StandardButton.Yes:
                return
            try:
                self._stop_wallpapers_using_path(path)
                os.remove(path)
                self._remove_wallpaper_references(path)
                self.refresh_grid()
            except Exception as e:
                QMessageBox.warning(self, "Eliminar", f"No se pudo eliminar:\n{e}")
            return

    def _stop_wallpapers_using_path(self, path: str) -> None:
        wallpapers = self.config.get("wallpapers", {})
        if not isinstance(wallpapers, dict):
            return
        for k, v in list(wallpapers.items()):
            if v == path:
                try:
                    self.engine.stop(int(k))
                except Exception:
                    pass

    def _remove_wallpaper_references(self, path: str) -> None:
        wallpapers = self.config.get("wallpapers", {})
        if isinstance(wallpapers, dict):
            for k, v in list(wallpapers.items()):
                if v == path:
                    del wallpapers[k]
        self._save_config()

    def _rewrite_wallpaper_paths(self, old_path: str, new_path: str) -> None:
        wallpapers = self.config.get("wallpapers", {})
        if isinstance(wallpapers, dict):
            for k, v in list(wallpapers.items()):
                if v == old_path:
                    wallpapers[k] = new_path
        self._save_config()

    def _get_monitor_settings(self, screen_idx: int) -> dict:
        ms = self.config.get("monitor_settings", {})
        if not isinstance(ms, dict):
            ms = {}
            self.config["monitor_settings"] = ms
        val = ms.get(str(screen_idx), {})
        return val if isinstance(val, dict) else {}

    def _set_monitor_settings(self, screen_idx: int, settings: dict) -> None:
        ms = self.config.get("monitor_settings", {})
        if not isinstance(ms, dict):
            ms = {}
            self.config["monitor_settings"] = ms
        ms[str(screen_idx)] = dict(settings or {})

    def _get_effective_volume_for_screen(self, screen_idx: int) -> int:
        if self.config.get("mute", False):
            return 0
        ms = self._get_monitor_settings(screen_idx)
        vol = ms.get("volume", self.config.get("volume", 50))
        try:
            vol = int(vol)
        except Exception:
            vol = int(self.config.get("volume", 50))
        return max(0, min(100, vol))

    def _get_effective_paused_for_screen(self, screen_idx: int) -> bool:
        global_paused = bool(self.config.get("paused", False)) or bool(self.config.get("battery_paused", False))
        ms = self._get_monitor_settings(screen_idx)
        if "paused" in ms:
            return bool(ms.get("paused")) or global_paused
        return global_paused

    def _get_monitor_style(self, thumb_path=None):
        image_css = ""
        if thumb_path:
            thumb_path = thumb_path.replace("\\", "/")
            image_css = f'border-image: url("{thumb_path}") 0 0 0 0 stretch stretch;'
            
        return f"""
            QPushButton {{
                background-color: {self.colors['monitor_bg']};
                border: 2px solid {self.colors['monitor_border']};
                border-radius: 8px;
                color: {self.colors['text_secondary']};
                font-weight: bold;
                font-size: 24px;
                {image_css}
            }}
            QPushButton:hover {{
                border: 2px solid {self.colors['text_secondary']};
            }}
            QPushButton:checked {{
                border: 4px solid {self.colors['monitor_checked']};
                {image_css}
            }}
        """

    def _init_gallery(self):
        page = QWidget()
        v_lay = QVBoxLayout(page)

        preview_container = QFrame()
        preview_container.setStyleSheet(f"background-color: {self.colors['panel']}; border-radius: 10px; margin-bottom: 10px; border: 1px solid {self.colors['panel_border']};")

        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(20, 20, 20, 20)
        preview_layout.setSpacing(15)
        
        lbl_monitors = QLabel("Selecciona Monitor:")
        lbl_monitors.setStyleSheet(f"color: {self.colors['text']}; font-weight: bold; font-size: 16px; background: transparent;")
        preview_layout.addWidget(lbl_monitors)
        
        self.monitors_layout = QHBoxLayout()
        self.monitors_layout.setAlignment(Qt.AlignmentFlag.AlignCenter) # Centrar monitores
        self.monitors_layout.setSpacing(20)
        
        self._refresh_monitor_buttons()

        preview_layout.addLayout(self.monitors_layout)

        self.apply_all_checkbox = QCheckBox("Aplicar a todos los monitores")
        self.apply_all_checkbox.setStyleSheet(f"color: {self.colors['text']}; font-size: 14px; background: transparent;")
        self.apply_all_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        
        chk_layout = QHBoxLayout()
        chk_layout.addStretch()
        chk_layout.addWidget(self.apply_all_checkbox)
        chk_layout.addStretch()
        preview_layout.addLayout(chk_layout)

        monitor_settings_frame = QFrame()
        monitor_settings_frame.setStyleSheet("background: transparent;")
        ms_layout = QVBoxLayout(monitor_settings_frame)
        ms_layout.setContentsMargins(0, 0, 0, 0)
        ms_layout.setSpacing(8)

        lbl_ms = QLabel("Ajustes del monitor seleccionado")
        lbl_ms.setStyleSheet(f"color: {self.colors['text_secondary']}; font-weight: bold; background: transparent;")
        ms_layout.addWidget(lbl_ms)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        lbl_v = QLabel("Volumen:")
        lbl_v.setStyleSheet(f"color: {self.colors['text_secondary']}; background: transparent;")
        self.monitor_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.monitor_vol_slider.setRange(0, 100)
        self.monitor_vol_slider.setValue(self._get_effective_volume_for_screen(self.selected_screen))
        self.monitor_vol_slider.setEnabled(not self.config.get("mute", False))
        self.monitor_vol_val = QLabel(f"{self.monitor_vol_slider.value()}%")
        self.monitor_vol_val.setStyleSheet(f"color: {self.colors['text_secondary']}; background: transparent;")
        row1.addWidget(lbl_v)
        row1.addWidget(self.monitor_vol_slider)
        row1.addWidget(self.monitor_vol_val)
        ms_layout.addLayout(row1)

        self.monitor_pause_chk = QCheckBox("Pausado (solo este monitor)")
        self.monitor_pause_chk.setStyleSheet(f"color: {self.colors['text_secondary']}; background: transparent;")
        self.monitor_pause_chk.setChecked(bool(self._get_monitor_settings(self.selected_screen).get("paused", False)))
        ms_layout.addWidget(self.monitor_pause_chk)

        def _on_monitor_volume_change(value: int):
            self.monitor_vol_val.setText(f"{value}%")
            ms = self._get_monitor_settings(self.selected_screen)
            ms["volume"] = int(value)
            self._set_monitor_settings(self.selected_screen, ms)
            self._save_config()
            self.engine.update_settings(self.config)

        def _on_monitor_pause_toggle(checked: bool):
            ms = self._get_monitor_settings(self.selected_screen)
            ms["paused"] = bool(checked)
            self._set_monitor_settings(self.selected_screen, ms)
            self._save_config()
            self.engine.update_settings(self.config)

        self.monitor_vol_slider.valueChanged.connect(_on_monitor_volume_change)
        self.monitor_pause_chk.toggled.connect(_on_monitor_pause_toggle)

        preview_layout.addWidget(monitor_settings_frame)

        v_lay.addWidget(preview_container)


        header = QHBoxLayout()
        lbl_header = QLabel("Tus Fondos Animados")
        lbl_header.setStyleSheet(f"color: {self.colors['text']}; font-weight: bold; font-size: 16px;")
        header.addWidget(lbl_header)
        header.addStretch()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar…")
        self.search_input.setStyleSheet(f"background-color: {self.colors['panel']}; color: {self.colors['text']}; border: 1px solid {self.colors['panel_border']}; padding: 6px 10px; border-radius: 6px;")
        self.search_input.textChanged.connect(self.refresh_grid)
        header.addWidget(self.search_input)

        self.format_filter = QComboBox()
        self.format_filter.addItems(["Todos", "mp4", "mkv", "mov", "webm", "avi"])
        self.format_filter.setStyleSheet(f"background-color: {self.colors['panel']}; color: {self.colors['text']}; border: 1px solid {self.colors['panel_border']}; padding: 4px 8px; border-radius: 6px;")
        self.format_filter.currentIndexChanged.connect(self.refresh_grid)
        header.addWidget(self.format_filter)

        self.res_filter = QComboBox()
        self.res_filter.addItems(["Resolución: Todas", "<=1080p", ">1080p"])
        self.res_filter.setStyleSheet(f"background-color: {self.colors['panel']}; color: {self.colors['text']}; border: 1px solid {self.colors['panel_border']}; padding: 4px 8px; border-radius: 6px;")
        self.res_filter.currentIndexChanged.connect(self.refresh_grid)
        header.addWidget(self.res_filter)

        self.dur_filter = QComboBox()
        self.dur_filter.addItems(["Duración: Todas", "<30s", "30-120s", ">120s"])
        self.dur_filter.setStyleSheet(f"background-color: {self.colors['panel']}; color: {self.colors['text']}; border: 1px solid {self.colors['panel_border']}; padding: 4px 8px; border-radius: 6px;")
        self.dur_filter.currentIndexChanged.connect(self.refresh_grid)
        header.addWidget(self.dur_filter)
        
        btn_style = f"""
            QPushButton {{
                background-color: {self.colors['panel']};
                color: {self.colors['text']};
                border: 1px solid {self.colors['panel_border']};
                padding: 6px 12px;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {self.colors['card_hover']};
            }}
        """
        
        btn_add_folder = QPushButton("📂 Importar Carpeta")
        btn_add_folder.setStyleSheet(btn_style)
        btn_add_folder.clicked.connect(self.import_folder)
        header.addWidget(btn_add_folder)

        btn_add = QPushButton("+ Importar Video")
        btn_add.setStyleSheet(btn_style)
        btn_add.clicked.connect(self.import_video)
        header.addWidget(btn_add)
        v_lay.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        scroll.setMinimumHeight(100) 
        
        self.grid_content = QWidget()
        self.grid = QGridLayout(self.grid_content)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.grid_content)
        v_lay.addWidget(scroll)
        
        self.stack.addWidget(page)
        self.video_cards = [] # Store cards for responsive layout
        self.refresh_grid()

    def _refresh_monitor_buttons(self):
        while self.monitors_layout.count():
            item = self.monitors_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        self.monitor_widgets = []
        
        for i in range(self.engine.get_screen_count()):
            monitor = QPushButton()
            monitor.setFixedSize(192, 108) # 16:9
            monitor.setCheckable(True)
            monitor.setCursor(Qt.CursorShape.PointingHandCursor)
            monitor.clicked.connect(lambda checked, idx=i: self._select_monitor(idx))
            
            monitor.setStyleSheet(self._get_monitor_style())
            monitor.setText(f"{i+1}")
            
            self.monitors_layout.addWidget(monitor)
            self.monitor_widgets.append(monitor)
            
            if i == self.selected_screen:
                monitor.setChecked(True)

        if self.selected_screen >= len(self.monitor_widgets):
            self.selected_screen = 0
            if self.monitor_widgets:
                self.monitor_widgets[0].setChecked(True)

        wallpapers = self.config.get("wallpapers", {})
        for screen_str, video_path in wallpapers.items():
            try:
                idx = int(screen_str)
                if idx < len(self.monitor_widgets):
                    self._update_monitor_button(idx, video_path)
            except:
                pass

    def _on_screens_changed(self, screen):
        """Maneja cambios en monitores (conexión/desconexión)"""
        if hasattr(self, '_restore_timer') and self._restore_timer.isActive():
            self._restore_timer.stop()
            
        self._restore_timer = QTimer()
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._delayed_restore)
        self._restore_timer.start(2000)

    def _delayed_restore(self):
        # Reinicia players para re-asociar índices tras cambios de monitores.
        self.engine.stop()

        QTimer.singleShot(500, self._execute_restore)

    def _execute_restore(self):
        self._refresh_monitor_buttons()
        self.restore_wallpapers()

    def _select_monitor(self, index):
        self.selected_screen = index
        for i, btn in enumerate(self.monitor_widgets):
            btn.setChecked(i == index)

        if hasattr(self, "monitor_vol_slider"):
            self.monitor_vol_slider.blockSignals(True)
            self.monitor_vol_slider.setValue(self._get_effective_volume_for_screen(index))
            self.monitor_vol_slider.blockSignals(False)
        if hasattr(self, "monitor_vol_val"):
            self.monitor_vol_val.setText(f"{self._get_effective_volume_for_screen(index)}%")
        if hasattr(self, "monitor_pause_chk"):
            self.monitor_pause_chk.blockSignals(True)
            self.monitor_pause_chk.setChecked(bool(self._get_monitor_settings(index).get("paused", False)))
            self.monitor_pause_chk.blockSignals(False)
        

    def _update_monitor_button(self, index, video_path):
        """Actualiza visualmente el botón del monitor"""
        if 0 <= index < len(self.monitor_widgets):
            btn = self.monitor_widgets[index]
            thumb_path = self.engine.get_thumbnail(video_path)

            btn.setIcon(QIcon())
            
            if thumb_path:
                btn.setStyleSheet(self._get_monitor_style(thumb_path))
                btn.setText("")
            else:
                btn.setStyleSheet(self._get_monitor_style())
                btn.setText(f"{index + 1}")

    def _get_effective_volume(self):
        if self.config.get("mute", False):
            return 0
        return self.config.get("volume", 50)

    def apply_wallpaper(self, video_path):
        """Aplica el wallpaper al monitor seleccionado y guarda config"""
        pause_on_max = self.config.get("pause_on_max", False)
        
        if "wallpapers" not in self.config:
            self.config["wallpapers"] = {}

        if hasattr(self, 'apply_all_checkbox') and self.apply_all_checkbox.isChecked():
            for i in range(self.engine.get_screen_count()):
                vol_i = self._get_effective_volume_for_screen(i)
                paused_i = self._get_effective_paused_for_screen(i)
                self.engine.play(video_path, i, pause_on_max, vol_i, paused_i)
                self._update_monitor_button(i, video_path)
                self.config["wallpapers"][str(i)] = video_path
        else:
            screen_idx = self.selected_screen
            vol_i = self._get_effective_volume_for_screen(screen_idx)
            paused_i = self._get_effective_paused_for_screen(screen_idx)
            self.engine.play(video_path, screen_idx, pause_on_max, vol_i, paused_i)
            self._update_monitor_button(screen_idx, video_path)
            self.config["wallpapers"][str(screen_idx)] = video_path
            
        self._save_config()
        


    def restore_wallpapers(self):
        """Restaura los wallpapers guardados"""
        wallpapers = self.config.get("wallpapers", {})
        
        screen_count = self.engine.get_screen_count()
        
        for screen_str, video_path in wallpapers.items():
            if os.path.exists(video_path):
                try:
                    idx = int(screen_str)
                    if idx < screen_count:
                        vol_i = self._get_effective_volume_for_screen(idx)
                        paused_i = self._get_effective_paused_for_screen(idx)
                        self.engine.play(video_path, idx, self.config.get("pause_on_max", False), vol_i, paused_i)
                        if hasattr(self, 'monitor_widgets'):
                            self._update_monitor_button(idx, video_path)
                except Exception as e:
                    print(f"Error restaurando wallpaper: {e}")

    def _update_preview(self, video_path):
        """Actualiza el monitor de preview superior (Legacy, ahora usa apply_wallpaper)"""
        pass

    def _init_config(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        title = QLabel("Panel de Configuración")
        title.setStyleSheet(f"font-size: 24px; font-weight: bold; margin-bottom: 15px; color: {self.colors['text']};")
        layout.addWidget(title)
        
        grp_theme = QFrame()
        grp_theme.setObjectName("ConfigFrame")
        grp_theme.setStyleSheet(f"#ConfigFrame {{ background-color: {self.colors['panel']}; border-radius: 8px; border: 1px solid {self.colors['panel_border']}; }}")
        l_theme = QVBoxLayout(grp_theme)
        l_theme.setContentsMargins(20, 20, 20, 20) # Padding real
        
        lbl_theme = QLabel("Apariencia")
        lbl_theme.setStyleSheet(f"font-weight: bold; font-size: 18px; color: {self.colors['text']}; margin-bottom: 10px; background: transparent;")
        l_theme.addWidget(lbl_theme)
        
        h_theme = QHBoxLayout()
        h_theme.setSpacing(12)
        btn_dark = QPushButton("🌙 Oscuro")
        btn_dark.setCheckable(True)
        btn_dark.setChecked(self.current_theme_name == "dark")
        btn_dark.clicked.connect(lambda: self.apply_theme("dark"))
        btn_dark.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_dark.setMinimumHeight(36)
        
        btn_light = QPushButton("☀ Claro")
        btn_light.setCheckable(True)
        btn_light.setChecked(self.current_theme_name == "light")
        btn_light.clicked.connect(lambda: self.apply_theme("light"))
        btn_light.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_light.setMinimumHeight(36)
        
        theme_btn_style = f"""
            QPushButton {{
                background-color: {self.colors['card_bg']};
                color: {self.colors['text']};
                border: 1px solid {self.colors['panel_border']};
                padding: 8px 16px;
                text-align: center;
                min-height: 34px;
                border-radius: 6px;
            }}
            QPushButton:checked {{
                background-color: {self.colors['accent']};
                color: white;
                border: 1px solid {self.colors['accent']};
            }}
        """
        btn_dark.setStyleSheet(theme_btn_style)
        btn_light.setStyleSheet(theme_btn_style)
        
        h_theme.addWidget(btn_dark, 1)
        h_theme.addWidget(btn_light, 1)
        l_theme.addLayout(h_theme)
        layout.addWidget(grp_theme)
        
        self._create_section(layout, "General", [
            ("Pausar cuando hay ventanas maximizadas", "pause_on_max", self._on_pause_toggled),
            ("Iniciar con el sistema", "autostart", self._on_autostart_toggled)
        ])

        grp_audio = QFrame()
        grp_audio.setObjectName("ConfigFrame")
        grp_audio.setStyleSheet(f"#ConfigFrame {{ background-color: {self.colors['panel']}; border-radius: 8px; border: 1px solid {self.colors['panel_border']}; }}")
        l_audio = QVBoxLayout(grp_audio)
        l_audio.setContentsMargins(20, 20, 20, 20)
        l_audio.setSpacing(10)
        
        lbl_audio = QLabel("Audio")
        lbl_audio.setStyleSheet(f"font-weight: bold; font-size: 18px; color: {self.colors['text']}; margin-bottom: 10px; background: transparent;")
        l_audio.addWidget(lbl_audio)

        self.chk_mute = QCheckBox("Silenciar Audio")
        self.chk_mute.setStyleSheet(f"font-size: 14px; spacing: 8px; color: {self.colors['text_secondary']}; background: transparent;")
        self.chk_mute.setChecked(self.config.get("mute", False))
        self.chk_mute.toggled.connect(self._on_mute_toggled)
        l_audio.addWidget(self.chk_mute)

        vol_layout = QHBoxLayout()
        lbl_vol = QLabel("Volumen:")
        lbl_vol.setStyleSheet(f"color: {self.colors['text_secondary']}; background: transparent;")
        self.slider_vol = QSlider(Qt.Orientation.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(self.config.get("volume", 50))
        self.slider_vol.setEnabled(not self.chk_mute.isChecked())
        self.slider_vol.valueChanged.connect(self._on_volume_changed)
        
        self.lbl_vol_val = QLabel(f"{self.slider_vol.value()}%")
        self.lbl_vol_val.setStyleSheet(f"color: {self.colors['text_secondary']}; width: 30px; background: transparent;")
        
        vol_layout.addWidget(lbl_vol)
        vol_layout.addWidget(self.slider_vol)
        vol_layout.addWidget(self.lbl_vol_val)
        l_audio.addLayout(vol_layout)
        
        layout.addWidget(grp_audio)

        self._create_section(layout, "Rendimiento", [
            ("Modo Ahorro de Energía (Pausar en batería)", "power_save", self._on_power_save_toggled),
            ("Limitar FPS (Experimental)", "fps_limit", self._on_fps_limit_toggled)
        ])

        grp_pl = QFrame()
        grp_pl.setObjectName("ConfigFrame")
        grp_pl.setStyleSheet(f"#ConfigFrame {{ background-color: {self.colors['panel']}; border-radius: 8px; border: 1px solid {self.colors['panel_border']}; }}")
        l_pl = QVBoxLayout(grp_pl)
        l_pl.setContentsMargins(20, 20, 20, 20)
        l_pl.setSpacing(10)

        lbl_pl = QLabel("Playlist")
        lbl_pl.setStyleSheet(f"font-weight: bold; font-size: 18px; color: {self.colors['text']}; margin-bottom: 10px; background: transparent;")
        l_pl.addWidget(lbl_pl)

        self.chk_shuffle = QCheckBox("Rotar/shuffle automáticamente")
        self.chk_shuffle.setStyleSheet(f"font-size: 14px; spacing: 8px; color: {self.colors['text_secondary']}; background: transparent;")
        self.chk_shuffle.setChecked(bool(self.config.get("shuffle_enabled", False)))
        l_pl.addWidget(self.chk_shuffle)

        row_int = QHBoxLayout()
        row_int.setSpacing(10)
        lbl_int = QLabel("Intervalo (min):")
        lbl_int.setStyleSheet(f"color: {self.colors['text_secondary']}; background: transparent;")
        self.shuffle_interval = QSlider(Qt.Orientation.Horizontal)
        self.shuffle_interval.setRange(1, 120)
        self.shuffle_interval.setValue(int(self.config.get("shuffle_interval_min", 10) or 10))
        self.shuffle_interval_val = QLabel(f"{self.shuffle_interval.value()}m")
        self.shuffle_interval_val.setStyleSheet(f"color: {self.colors['text_secondary']}; background: transparent;")
        row_int.addWidget(lbl_int)
        row_int.addWidget(self.shuffle_interval)
        row_int.addWidget(self.shuffle_interval_val)
        l_pl.addLayout(row_int)

        self.chk_shuffle_all = QCheckBox("Aplicar el mismo fondo en todos los monitores")
        self.chk_shuffle_all.setStyleSheet(f"font-size: 14px; spacing: 8px; color: {self.colors['text_secondary']}; background: transparent;")
        self.chk_shuffle_all.setChecked(bool(self.config.get("shuffle_apply_all", True)))
        l_pl.addWidget(self.chk_shuffle_all)

        def _on_shuffle_toggle(checked: bool):
            self.config["shuffle_enabled"] = bool(checked)
            self._save_config()
            self._ensure_shuffle_timer()

        def _on_shuffle_interval(value: int):
            self.config["shuffle_interval_min"] = int(value)
            self.shuffle_interval_val.setText(f"{value}m")
            self._save_config()
            self._ensure_shuffle_timer()

        def _on_shuffle_all(checked: bool):
            self.config["shuffle_apply_all"] = bool(checked)
            self._save_config()

        self.chk_shuffle.toggled.connect(_on_shuffle_toggle)
        self.shuffle_interval.valueChanged.connect(_on_shuffle_interval)
        self.chk_shuffle_all.toggled.connect(_on_shuffle_all)

        layout.addWidget(grp_pl)
        
        grp_control = QFrame()
        grp_control.setObjectName("ConfigFrame")
        grp_control.setStyleSheet(f"#ConfigFrame {{ background-color: {self.colors['panel']}; border-radius: 8px; border: 1px solid {self.colors['panel_border']}; }}")
        l_ctrl = QVBoxLayout(grp_control)
        l_ctrl.setContentsMargins(20, 20, 20, 20)
        l_ctrl.setSpacing(10)
        
        lbl_ctrl = QLabel("Sistema")
        lbl_ctrl.setStyleSheet(f"font-weight: bold; font-size: 18px; color: {self.colors['text']}; margin-bottom: 10px; background: transparent;")
        l_ctrl.addWidget(lbl_ctrl)
        
        btn_quit_all = QPushButton("❌ Apagar Todo y Salir")
        btn_quit_all.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_quit_all.setMinimumHeight(40)
        btn_quit_all.setStyleSheet(f"""
            QPushButton {{ background-color: {self.colors['danger']}; color: white; padding: 12px; border-radius: 6px; font-weight: bold; font-size: 14px; }}
            QPushButton:hover {{ background-color: {self.colors['danger_hover']}; }}
        """)
        btn_quit_all.clicked.connect(self.quit_all)
        l_ctrl.addWidget(btn_quit_all)

        btn_logs = QPushButton("📄 Ver logs del wallpaper")
        btn_logs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_logs.setMinimumHeight(38)
        btn_logs.setStyleSheet(f"QPushButton {{ background-color: {self.colors['panel']}; color: {self.colors['text']}; border: 1px solid {self.colors['panel_border']}; padding: 10px; border-radius: 6px; }} QPushButton:hover {{ background-color: {self.colors['card_hover']}; }}")
        btn_logs.clicked.connect(self._open_wallpaper_logs)
        l_ctrl.addWidget(btn_logs)

        btn_deps = QPushButton("🧪 Comprobar dependencias")
        btn_deps.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_deps.setMinimumHeight(38)
        btn_deps.setStyleSheet(f"QPushButton {{ background-color: {self.colors['panel']}; color: {self.colors['text']}; border: 1px solid {self.colors['panel_border']}; padding: 10px; border-radius: 6px; }} QPushButton:hover {{ background-color: {self.colors['card_hover']}; }}")
        btn_deps.clicked.connect(self._check_dependencies)
        l_ctrl.addWidget(btn_deps)
        
        layout.addWidget(grp_control)
        
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        scroll.setStyleSheet(f"QScrollArea {{ background: {self.colors['window']}; border: none; }}")

        self.stack.addWidget(scroll)

    def _open_wallpaper_logs(self):
        candidates = [
            "/dev/shm/komorebi_wall.log",
            "/tmp/komorebi_wall.log",
        ]
        for p in candidates:
            if os.path.exists(p):
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))
                return
        QMessageBox.information(self, "Logs", "No se encontró ningún log aún.")

    def _check_dependencies(self):
        bins = ["vlc", "ffmpeg", "xrandr", "xprop", "gsettings", "ffprobe"]
        lines = []
        for b in bins:
            lines.append(f"{b}: {'OK' if shutil.which(b) else 'FALTA'}")

        try:
            import vlc as _vlc
            lines.append("python-vlc: OK")
        except Exception as e:
            lines.append(f"python-vlc: FALTA ({type(e).__name__})")

        QMessageBox.information(self, "Dependencias", "\n".join(lines))

    def _init_about(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        lbl_title = QLabel("Komorebi")
        lbl_title.setStyleSheet(f"font-size: 32px; font-weight: bold; color: {self.colors['text']}; margin-bottom: 10px;")
        layout.addWidget(lbl_title)
        
        lbl_desc = QLabel("Un motor de fondos de pantalla animados para Linux (Wayland).\nCreado con Python y PySide6.")
        lbl_desc.setStyleSheet(f"font-size: 16px; color: {self.colors['text_secondary']}; margin-bottom: 30px;")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_desc)
        
        btn_github = QPushButton("  Ver en GitHub")
        btn_github.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_github.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.colors['panel']}; 
                color: {self.colors['text']}; 
                padding: 12px 24px; 
                border-radius: 6px; 
                font-size: 16px;
                border: 1px solid {self.colors['panel_border']};
            }}
            QPushButton:hover {{
                background-color: {self.colors['card_hover']};
            }}
        """)
        btn_github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/Evergaster/Komorebi"))) 
        layout.addWidget(btn_github)
        
        btn_issue = QPushButton("  Reportar un error")
        btn_issue.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_issue.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.colors['danger']}; 
                color: white; 
                padding: 12px 24px; 
                border-radius: 6px; 
                font-size: 16px; 
                margin-top: 10px;
            }}
            QPushButton:hover {{
                background-color: {self.colors['danger_hover']};
            }}
        """)
        btn_issue.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/Evergaster/Komorebi/issues")))
        layout.addWidget(btn_issue)
        
        self.stack.addWidget(page)

    def _create_section(self, parent_layout, title, options):
        frame = QFrame()
        frame.setObjectName("ConfigFrame")
        frame.setStyleSheet(f"#ConfigFrame {{ background-color: {self.colors['panel']}; border-radius: 8px; border: 1px solid {self.colors['panel_border']}; }}")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        
        lbl = QLabel(title)
        lbl.setStyleSheet(f"font-weight: bold; font-size: 18px; color: {self.colors['text']}; margin-bottom: 10px; background: transparent;")
        layout.addWidget(lbl)
        
        for text, key, slot in options:
            chk = QCheckBox(text)
            chk.setStyleSheet(f"font-size: 14px; spacing: 8px; color: {self.colors['text_secondary']}; background: transparent;")
            chk.setChecked(self.config.get(key, False))
            chk.toggled.connect(slot)
            layout.addWidget(chk)
            
        parent_layout.addWidget(frame)

    def _on_mute_toggled(self, checked):
        self.config["mute"] = checked
        self.slider_vol.setEnabled(not checked)
        self._save_config()
        self.engine.update_settings(self.config)

    def _on_volume_changed(self, value):
        self.config["volume"] = value
        self.lbl_vol_val.setText(f"{value}%")
        self._save_config()
        self.engine.update_settings(self.config)

    def quit_all(self):
        """Detiene todo y cierra la app"""
        self.tray_icon.hide()
        self.engine.stop()
        QApplication.quit()

    def _on_pause_toggled(self, checked):
        self.config["pause_on_max"] = checked
        self._save_config()
        self.engine.update_settings(self.config)
        
    def _on_autostart_toggled(self, checked):
        self.config["autostart"] = checked
        self._save_config()
        self._manage_autostart(checked)

    def _on_power_save_toggled(self, checked):
        self.config["power_save"] = checked
        self._save_config()
        self.engine.update_settings(self.config)

    def _on_fps_limit_toggled(self, checked):
        self.config["fps_limit"] = checked
        self._save_config()
        self.engine.update_settings(self.config)

    def _manage_autostart(self, enable):
        """Crea o elimina el archivo .desktop en ~/.config/autostart"""
        autostart_dir = os.path.expanduser("~/.config/autostart")
        desktop_file = os.path.join(autostart_dir, "komorebi.desktop")
        
        if enable:
            os.makedirs(autostart_dir, exist_ok=True)
            
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            wrapper_script = os.path.join(project_root, "run_komorebi.sh")
            icon_path = os.path.join(project_root, "icons", "Komorebi.png")
            
            if os.path.exists(wrapper_script):
                exec_cmd = f'"{wrapper_script}" --restore-only --delay 5'
            elif getattr(sys, 'frozen', False):
                exec_path = sys.executable
                exec_cmd = f'"{exec_path}" --restore-only --delay 5'
            else:
                main_script = os.path.join(project_root, "main.py")
                exec_cmd = f'"{sys.executable}" "{main_script}" --restore-only --delay 5'
            
            content = f"""[Desktop Entry]
Type=Application
Name=Komorebi
Exec={exec_cmd}
Icon={icon_path}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=Wallpaper Engine Clone
StartupNotify=false
"""
            try:
                with open(desktop_file, 'w') as f:
                    f.write(content)
                os.chmod(desktop_file, 0o755)
            except Exception as e:
                print(f"Error creando autostart: {e}")
        else:
            if os.path.exists(desktop_file):
                try:
                    os.remove(desktop_file)
                except Exception as e:
                    print(f"Error eliminando autostart: {e}")

    def resizeEvent(self, event):
        self._resize_timer.start(150) 
        super().resizeEvent(event)

    def import_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta")
        if folder_path:
            valid_extensions = {".mp4", ".webm", ".mkv", ".avi", ".mov"}
            count = 0
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    if os.path.splitext(file)[1].lower() in valid_extensions:
                        src_path = os.path.join(root, file)
                        dest_path = os.path.join(self.video_dir, file)
                        if not os.path.exists(dest_path):
                            shutil.copy(src_path, dest_path)
                            count += 1
            
            if count > 0:
                self.refresh_grid()
                QMessageBox.information(self, "Importación", f"Se importaron {count} videos.")
            else:
                QMessageBox.information(self, "Importación", "No se encontraron videos nuevos.")

    def import_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "Elegir Video", "", "Videos (*.mp4 *.mov *.mkv)")
        if path:
            shutil.copy(path, os.path.join(self.video_dir, os.path.basename(path)))
            self.refresh_grid()

    def refresh_grid(self):
        for i in reversed(range(self.grid.count())): 
            self.grid.itemAt(i).widget().setParent(None)
        self.video_cards = []

        query = ""
        if hasattr(self, "search_input") and self.search_input is not None:
            query = (self.search_input.text() or "").strip().lower()

        allowed_ext = {".mp4", ".mkv", ".mov", ".webm", ".avi"}
        fmt = "Todos"
        if hasattr(self, "format_filter") and self.format_filter is not None:
            fmt = self.format_filter.currentText()
        if fmt != "Todos":
            allowed_ext = {f".{fmt.lower()}"}

        videos = [f for f in os.listdir(self.video_dir) if os.path.splitext(f)[1].lower() in allowed_ext]
        if query:
            videos = [v for v in videos if query in v.lower()]

        res_mode = "Resolución: Todas"
        dur_mode = "Duración: Todas"
        if hasattr(self, "res_filter") and self.res_filter is not None:
            res_mode = self.res_filter.currentText()
        if hasattr(self, "dur_filter") and self.dur_filter is not None:
            dur_mode = self.dur_filter.currentText()

        if (res_mode != "Resolución: Todas") or (dur_mode != "Duración: Todas"):
            filtered = []
            for v in videos:
                full_path = os.path.join(self.video_dir, v)
                meta = self._ffprobe_video_meta(full_path)
                if meta is None:
                    filtered.append(v)
                    continue

                h = int(meta.get("height") or 0)
                d = float(meta.get("duration") or 0.0)

                ok = True
                if res_mode == "<=1080p":
                    ok = ok and (h <= 1080)
                elif res_mode == ">1080p":
                    ok = ok and (h > 1080)

                if dur_mode == "<30s":
                    ok = ok and (d > 0 and d < 30)
                elif dur_mode == "30-120s":
                    ok = ok and (d >= 30 and d <= 120)
                elif dur_mode == ">120s":
                    ok = ok and (d > 120)

                if ok:
                    filtered.append(v)
            videos = filtered

        videos.sort(key=lambda s: s.lower())
        for v in videos:
            full_path = os.path.join(self.video_dir, v)
            card = VideoCard(
                full_path,
                lambda p: self.apply_wallpaper(p),
                lambda payload: self._handle_card_action(payload),
                self.engine,
                self.thread_pool,
                self.colors,
            )
            self.video_cards.append(card)
        
        self.rearrange_grid()

    def rearrange_grid(self):
        if not hasattr(self, 'video_cards') or not self.video_cards:
            return
            
        if hasattr(self, 'grid_content') and self.grid_content.width() > 0:
            available_width = self.grid_content.width()
        else:
            available_width = self.width() - 240 
            
        card_width = 190 # 180 + spacing
        columns = max(1, available_width // card_width)
        
        while self.grid.count():
            item = self.grid.takeAt(0)

        for idx, card in enumerate(self.video_cards):
            self.grid.addWidget(card, idx // columns, idx % columns)