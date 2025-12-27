import os
import shutil
import sys
import json
import time
import psutil # Para batería
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QScrollArea, QGridLayout, 
                             QLabel, QFrame, QStackedWidget, QMessageBox, QCheckBox, 
                             QApplication, QSlider, QProgressBar, QSystemTrayIcon, QMenu, QStyle, QSizePolicy)
from PySide6.QtCore import Qt, QUrl, QSize, QThread, Signal, QObject, QThreadPool, QRunnable, Slot, QTimer
from PySide6.QtGui import QPixmap, QImage, QGuiApplication, QAction, QDesktopServices, QIcon, QPalette, QColor
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from src.engine import WallpaperEngine

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
        # Esto llamará a get_thumbnail que genera si no existe
        thumb_path = self.engine.get_thumbnail(self.video_path)
        self.signaller.finished.emit(thumb_path if thumb_path else "")

class Signaller(QObject):
    finished = Signal(str)

class VideoCard(QFrame):
    def __init__(self, file_path, on_click, on_select, engine, thread_pool, colors):
        super().__init__()
        self.path = file_path
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
        
        # Thumbnail/Preview
        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(166, 100) # Reducido de 200x120
        self.thumbnail.setStyleSheet(f"background-color: {self.colors['monitor_bg']}; border-radius: 8px; border: none;")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Cargar thumbnail
        self._load_thumbnail()
            
        layout.addWidget(self.thumbnail)
        
        # Nombre del archivo
        name = os.path.basename(file_path)
        lbl = QLabel(name[:22] + "..." if len(name) > 22 else name)
        lbl.setStyleSheet(f"color: {self.colors['text']}; font-weight: bold; border: none; font-size: 11px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        
        # Botón aplicar
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
        # Verificar si existe sin generar
        thumb_path = self.engine.get_thumbnail_path(self.path)
        if thumb_path and os.path.exists(thumb_path):
            self._set_pixmap(thumb_path)
        else:
            # Placeholder y generar en background
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
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_select(self.path)
        super().mousePressEvent(event)
    
    def _safe_apply(self, callback):
        """Aplica wallpaper con manejo de errores"""
        try:
            callback(self.path)
        except RuntimeError as e:
            # Error de compatibilidad (GNOME Wayland)
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
            # Evitar duplicados de nombre (simple)
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
        
        # Forzar estilo Fusion para evitar conflictos de color con temas del sistema
        QApplication.setStyle("Fusion")
        
        self.setWindowTitle("Komorebi")
        self.resize(1100, 750) # Aumentado para mejor visualización
        self.setMinimumSize(900, 650)
        self._center_window()
        
        # Timer para optimizar redimensionado (debounce)
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self.rearrange_grid)
        
        # Set Window Icon
        icon_path = self._get_resource_path("icons/Komorebi.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.thread_pool = QThreadPool()
        
        # Intentar inicializar el engine con manejo de errores
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
        
        self.video_dir = os.path.expanduser("~/Videos/Komorebi")
        os.makedirs(self.video_dir, exist_ok=True)
        
        self.config_file = os.path.expanduser("~/.config/komorebi/config.json")
        self.config = self._load_config()
        
        # Asegurar que el autostart esté sincronizado con la configuración
        if self.config.get("autostart", False):
            self._manage_autostart(True)
        
        # Tema
        self.current_theme_name = self.config.get("theme", "dark")
        self.colors = THEMES.get(self.current_theme_name, THEMES["dark"])
        
        self.selected_screen = 0 # Pantalla seleccionada por defecto

        # Monitor changes
        QGuiApplication.instance().screenAdded.connect(self._on_screens_changed)
        QGuiApplication.instance().screenRemoved.connect(self._on_screens_changed)

        self._init_tray()

        # Main Layout
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Sidebar
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

        # Content Stack
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # Aplicar tema inicial (esto generará las páginas)
        self.apply_theme(self.current_theme_name)

        self.btn_gallery.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.btn_config.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        self.btn_about.clicked.connect(lambda: self.stack.setCurrentIndex(2))

        # Battery Monitor
        self.battery_timer = QTimer(self)
        self.battery_timer.timeout.connect(self._check_battery)
        self.battery_timer.start(10000) # Check every 10 seconds

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
        # Modo desarrollo: subir un nivel desde src/ para encontrar icons/
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), relative_path)

    def apply_theme(self, theme_name):
        self.current_theme_name = theme_name
        self.colors = THEMES[theme_name]
        self.config["theme"] = theme_name
        self._save_config()
        
        # Configurar paleta Qt
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
        
        # Actualizar estilos de componentes principales
        self.sidebar.setStyleSheet(f"background-color: {self.colors['sidebar']}; border-right: 1px solid {self.colors['sidebar_border']};")
             
        # Actualizar botones del sidebar
        btn_style = f"QPushButton {{ color: {self.colors['text']}; text-align: left; padding: 10px; border: none; font-size: 14px; }} QPushButton:hover {{ background-color: {self.colors['card_hover']}; }}"
        self.btn_gallery.setStyleSheet(btn_style)
        self.btn_config.setStyleSheet(btn_style)
        self.btn_about.setStyleSheet(btn_style)

        # Guardar índice actual
        current_idx = self.stack.currentIndex()
        if current_idx < 0: current_idx = 0

        # Limpiar stack
        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()
            
        # Regenerar UI
        self._init_gallery()
        self._init_config()
        self._init_about()
        
        self.stack.setCurrentIndex(current_idx)
        
        # Restaurar imágenes de monitores
        self.restore_wallpapers()

    def _init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        icon_path = self._get_resource_path("icons/Komorebi.ico")
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
                    # Unplugged, pause it
                    self.config["battery_paused"] = True
                    self.engine.update_settings(self.config)
                elif plugged and was_battery_paused:
                    # Plugged back in, unpause
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
        
        # --- Preview Area ---
        preview_container = QFrame()
        # Eliminamos altura fija para que se adapte al contenido
        preview_container.setStyleSheet(f"background-color: {self.colors['panel']}; border-radius: 10px; margin-bottom: 10px; border: 1px solid {self.colors['panel_border']};")
        
        # Usamos QVBoxLayout directamente para el contenedor
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

        # Checkbox para aplicar a todos
        self.apply_all_checkbox = QCheckBox("Aplicar a todos los monitores")
        self.apply_all_checkbox.setStyleSheet(f"color: {self.colors['text']}; font-size: 14px; background: transparent;")
        self.apply_all_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        
        chk_layout = QHBoxLayout()
        chk_layout.addStretch()
        chk_layout.addWidget(self.apply_all_checkbox)
        chk_layout.addStretch()
        preview_layout.addLayout(chk_layout)

        v_lay.addWidget(preview_container)
        # --------------------

        header = QHBoxLayout()
        lbl_header = QLabel("Tus Fondos Animados")
        lbl_header.setStyleSheet(f"color: {self.colors['text']}; font-weight: bold; font-size: 16px;")
        header.addWidget(lbl_header)
        header.addStretch()
        
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
        # Expanding permite crecer para llenar espacio, pero MinimumHeight evita que colapse a 0
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
        # Limpiar layout existente
        while self.monitors_layout.count():
            item = self.monitors_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        
        self.monitor_widgets = []
        
        # Recrear botones
        for i in range(self.engine.get_screen_count()):
            monitor = QPushButton()
            monitor.setFixedSize(192, 108) # 16:9
            monitor.setCheckable(True)
            monitor.setCursor(Qt.CursorShape.PointingHandCursor)
            monitor.clicked.connect(lambda checked, idx=i: self._select_monitor(idx))
            
            # Estilo base
            monitor.setStyleSheet(self._get_monitor_style())
            monitor.setText(f"{i+1}")
            
            self.monitors_layout.addWidget(monitor)
            self.monitor_widgets.append(monitor)
            
            # Restaurar selección
            if i == self.selected_screen:
                monitor.setChecked(True)
        
        # Si la pantalla seleccionada ya no existe, seleccionar la 0
        if self.selected_screen >= len(self.monitor_widgets):
            self.selected_screen = 0
            if self.monitor_widgets:
                self.monitor_widgets[0].setChecked(True)
                
        # Restaurar visualización de wallpapers activos en los botones
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
        # Debounce para evitar múltiples llamadas rápidas y esperar a que el OS estabilice
        if hasattr(self, '_restore_timer') and self._restore_timer.isActive():
            self._restore_timer.stop()
            
        self._restore_timer = QTimer()
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._delayed_restore)
        self._restore_timer.start(2000)

    def _delayed_restore(self):
        # Detener todos los reproductores actuales para evitar conflictos de índices
        # y asegurar que se re-asocien correctamente a las nuevas pantallas.
        self.engine.stop()
        
        # Pequeña pausa para asegurar que los procesos mueran y los archivos PID se limpien
        QTimer.singleShot(500, self._execute_restore)

    def _execute_restore(self):
        self._refresh_monitor_buttons()
        self.restore_wallpapers()

    def _select_monitor(self, index):
        self.selected_screen = index
        # Actualizar estado visual de los botones
        for i, btn in enumerate(self.monitor_widgets):
            btn.setChecked(i == index)
        
        # self.preview_title.setText(f"Monitor {index + 1} Seleccionado")
        # self.preview_desc.setText("Ahora selecciona un fondo para aplicar a este monitor.")

    def _update_monitor_button(self, index, video_path):
        """Actualiza visualmente el botón del monitor"""
        if 0 <= index < len(self.monitor_widgets):
            btn = self.monitor_widgets[index]
            thumb_path = self.engine.get_thumbnail(video_path)
            
            # Limpiar icono por si acaso
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
        volume = self._get_effective_volume()
        paused = self.config.get("paused", False) or self.config.get("battery_paused", False)
        pause_on_max = self.config.get("pause_on_max", False)
        
        if "wallpapers" not in self.config:
            self.config["wallpapers"] = {}

        if hasattr(self, 'apply_all_checkbox') and self.apply_all_checkbox.isChecked():
            # Aplicar a todos los monitores
            for i in range(self.engine.get_screen_count()):
                self.engine.play(video_path, i, pause_on_max, volume, paused)
                self._update_monitor_button(i, video_path)
                self.config["wallpapers"][str(i)] = video_path
        else:
            # Aplicar solo al seleccionado
            screen_idx = self.selected_screen
            self.engine.play(video_path, screen_idx, pause_on_max, volume, paused)
            self._update_monitor_button(screen_idx, video_path)
            self.config["wallpapers"][str(screen_idx)] = video_path
            
        self._save_config()
        
        # self.preview_title.setText(f"Monitor {screen_idx + 1}: {os.path.basename(video_path)}")

    def restore_wallpapers(self):
        """Restaura los wallpapers guardados"""
        wallpapers = self.config.get("wallpapers", {})
        volume = self._get_effective_volume()
        paused = self.config.get("paused", False) or self.config.get("battery_paused", False)
        
        screen_count = self.engine.get_screen_count()
        
        for screen_str, video_path in wallpapers.items():
            if os.path.exists(video_path):
                try:
                    idx = int(screen_str)
                    # Solo intentar reproducir si la pantalla existe
                    if idx < screen_count:
                        self.engine.play(video_path, idx, self.config.get("pause_on_max", False), volume, paused)
                        # Actualizar UI si estamos en modo gráfico completo
                        if hasattr(self, 'monitor_widgets'):
                            self._update_monitor_button(idx, video_path)
                except Exception as e:
                    print(f"Error restaurando wallpaper: {e}")

    def _update_preview(self, video_path):
        """Actualiza el monitor de preview superior (Legacy, ahora usa apply_wallpaper)"""
        # Este método era llamado por VideoCard, ahora VideoCard llamará a apply_wallpaper
        pass

    def _init_config(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        title = QLabel("Panel de Configuración")
        title.setStyleSheet(f"font-size: 24px; font-weight: bold; margin-bottom: 15px; color: {self.colors['text']};")
        layout.addWidget(title)
        
        # --- Tema ---
        grp_theme = QFrame()
        grp_theme.setObjectName("ConfigFrame")
        # Quitamos padding del CSS y lo manejamos en el layout
        grp_theme.setStyleSheet(f"#ConfigFrame {{ background-color: {self.colors['panel']}; border-radius: 8px; border: 1px solid {self.colors['panel_border']}; }}")
        l_theme = QVBoxLayout(grp_theme)
        l_theme.setContentsMargins(20, 20, 20, 20) # Padding real
        
        lbl_theme = QLabel("Apariencia")
        lbl_theme.setStyleSheet(f"font-weight: bold; font-size: 18px; color: {self.colors['text']}; margin-bottom: 10px; background: transparent;")
        l_theme.addWidget(lbl_theme)
        
        h_theme = QHBoxLayout()
        btn_dark = QPushButton("🌙 Oscuro")
        btn_dark.setCheckable(True)
        btn_dark.setChecked(self.current_theme_name == "dark")
        btn_dark.clicked.connect(lambda: self.apply_theme("dark"))
        
        btn_light = QPushButton("☀ Claro")
        btn_light.setCheckable(True)
        btn_light.setChecked(self.current_theme_name == "light")
        btn_light.clicked.connect(lambda: self.apply_theme("light"))
        
        # Estilo botones tema
        theme_btn_style = f"""
            QPushButton {{
                background-color: {self.colors['card_bg']};
                color: {self.colors['text']};
                border: 1px solid {self.colors['panel_border']};
                padding: 8px 16px;
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
        
        h_theme.addWidget(btn_dark)
        h_theme.addWidget(btn_light)
        h_theme.addStretch()
        l_theme.addLayout(h_theme)
        layout.addWidget(grp_theme)
        
        # --- General ---
        self._create_section(layout, "General", [
            ("Pausar cuando hay ventanas maximizadas", "pause_on_max", self._on_pause_toggled),
            ("Iniciar con el sistema", "autostart", self._on_autostart_toggled)
        ])

        # --- Audio ---
        grp_audio = QFrame()
        grp_audio.setObjectName("ConfigFrame")
        grp_audio.setStyleSheet(f"#ConfigFrame {{ background-color: {self.colors['panel']}; border-radius: 8px; border: 1px solid {self.colors['panel_border']}; }}")
        l_audio = QVBoxLayout(grp_audio)
        l_audio.setContentsMargins(20, 20, 20, 20)
        
        lbl_audio = QLabel("Audio")
        lbl_audio.setStyleSheet(f"font-weight: bold; font-size: 18px; color: {self.colors['text']}; margin-bottom: 10px; background: transparent;")
        l_audio.addWidget(lbl_audio)

        # Mute
        self.chk_mute = QCheckBox("Silenciar Audio")
        self.chk_mute.setStyleSheet(f"font-size: 14px; spacing: 8px; color: {self.colors['text_secondary']}; background: transparent;")
        self.chk_mute.setChecked(self.config.get("mute", False))
        self.chk_mute.toggled.connect(self._on_mute_toggled)
        l_audio.addWidget(self.chk_mute)

        # Volume Slider
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

        # --- Rendimiento ---
        self._create_section(layout, "Rendimiento", [
            ("Modo Ahorro de Energía (Pausar en batería)", "power_save", self._on_power_save_toggled),
            ("Limitar FPS (Experimental)", "fps_limit", self._on_fps_limit_toggled)
        ])
        
        # --- Control ---
        grp_control = QFrame()
        grp_control.setObjectName("ConfigFrame")
        grp_control.setStyleSheet(f"#ConfigFrame {{ background-color: {self.colors['panel']}; border-radius: 8px; border: 1px solid {self.colors['panel_border']}; }}")
        l_ctrl = QVBoxLayout(grp_control)
        l_ctrl.setContentsMargins(20, 20, 20, 20)
        
        lbl_ctrl = QLabel("Sistema")
        lbl_ctrl.setStyleSheet(f"font-weight: bold; font-size: 18px; color: {self.colors['text']}; margin-bottom: 10px; background: transparent;")
        l_ctrl.addWidget(lbl_ctrl)
        
        btn_quit_all = QPushButton("❌ Apagar Todo y Salir")
        btn_quit_all.setStyleSheet(f"""
            QPushButton {{ background-color: {self.colors['danger']}; color: white; padding: 12px; border-radius: 6px; font-weight: bold; font-size: 14px; }}
            QPushButton:hover {{ background-color: {self.colors['danger_hover']}; }}
        """)
        btn_quit_all.clicked.connect(self.quit_all)
        l_ctrl.addWidget(btn_quit_all)
        
        layout.addWidget(grp_control)
        
        layout.addStretch()
        self.stack.addWidget(page)

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
        btn_github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/evergaster/komorebi"))) 
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
        btn_issue.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/evergaster/komorebi/issues")))
        layout.addWidget(btn_issue)
        
        self.stack.addWidget(page)

    def _create_section(self, parent_layout, title, options):
        frame = QFrame()
        frame.setObjectName("ConfigFrame")
        frame.setStyleSheet(f"#ConfigFrame {{ background-color: {self.colors['panel']}; border-radius: 8px; border: 1px solid {self.colors['panel_border']}; }}")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 20, 20, 20)
        
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
        # Debounce o update inmediato? Inmediato está bien si no es muy costoso.
        # Para evitar spam de reinicios, idealmente usaríamos un timer, pero por ahora directo.
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
            
            # Determine path to main.py reliably
            if getattr(sys, 'frozen', False):
                # If packaged (e.g. PyInstaller)
                exec_path = sys.executable
                exec_cmd = f'"{exec_path}" --restore-only --delay 5'
            else:
                # If running from source
                # Assuming gui.py is in src/ and main.py is in root
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                main_script = os.path.join(project_root, "main.py")
                exec_cmd = f'"{sys.executable}" "{main_script}" --restore-only --delay 5'
            
            content = f"""[Desktop Entry]
Type=Application
Name=Komorebi
Exec={exec_cmd}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Comment=Wallpaper Engine Clone
"""
            try:
                with open(desktop_file, 'w') as f:
                    f.write(content)
            except Exception as e:
                print(f"Error creando autostart: {e}")
        else:
            if os.path.exists(desktop_file):
                try:
                    os.remove(desktop_file)
                except Exception as e:
                    print(f"Error eliminando autostart: {e}")

    def resizeEvent(self, event):
        # Usar timer para no recalcular en cada pixel de movimiento
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
        # Limpiar grid y lista
        for i in reversed(range(self.grid.count())): 
            self.grid.itemAt(i).widget().setParent(None)
        self.video_cards = []
        
        # Cargar
        videos = [f for f in os.listdir(self.video_dir) if f.endswith(('.mp4', '.mkv', '.mov'))]
        for v in videos:
            full_path = os.path.join(self.video_dir, v)
            card = VideoCard(
                full_path, 
                lambda p: self.apply_wallpaper(p),
                lambda p: None, 
                self.engine,
                self.thread_pool,
                self.colors
            )
            self.video_cards.append(card)
        
        self.rearrange_grid()

    def rearrange_grid(self):
        if not hasattr(self, 'video_cards') or not self.video_cards:
            return
            
        # Calcular columnas disponibles usando el ancho del área de contenido
        # Si el scroll no está visible aún, usamos un estimado basado en la ventana
        if hasattr(self, 'grid_content') and self.grid_content.width() > 0:
            available_width = self.grid_content.width()
        else:
            available_width = self.width() - 240 
            
        card_width = 190 # 180 + spacing
        columns = max(1, available_width // card_width)
        
        # Remover items del layout pero no borrarlos (setParent(None) los quita del layout)
        # Nota: setParent(None) en realidad puede destruir el widget si no tiene otra referencia.
        # Pero los tenemos en self.video_cards, así que está bien.
        # Sin embargo, QGridLayout::addWidget reparents them back.
        # Una forma más segura de limpiar el layout sin borrar widgets es takeAt.
        
        while self.grid.count():
            item = self.grid.takeAt(0)
            # No borramos el widget, solo lo sacamos del layout
            
        # Re-agregar
        for idx, card in enumerate(self.video_cards):
            self.grid.addWidget(card, idx // columns, idx % columns)