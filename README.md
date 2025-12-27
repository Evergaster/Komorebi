# Komorebi 🍃

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?style=for-the-badge&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Linux%20(Wayland)-green.svg?style=for-the-badge&logo=linux&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)

**Komorebi** es un gestor de fondos de pantalla animados para Linux, diseñado específicamente para entornos **Wayland** (principalmente GNOME). Permite establecer videos como fondo de escritorio de manera eficiente, elegante y con un bajo consumo de recursos.

El nombre *Komorebi* (木漏れ日) es una palabra japonesa que describe la luz del sol que se filtra a través de las hojas de los árboles.

## ✨ Características Principales

*   🎥 **Soporte de Video**: Reproduce archivos MP4, MKV, MOV, WEBM y más como fondo de pantalla.
*   🖥️ **Multi-Monitor Avanzado**: 
    *   Configura un fondo diferente y único para cada pantalla conectada.
    *   **Soporte Hot-Plug**: Detecta automáticamente la conexión y desconexión de monitores, manteniendo la estabilidad de los fondos en las pantallas restantes sin interrupciones.
*   ⚡ **Rendimiento y Eficiencia**:
    *   **Pausa Inteligente**: Pausa automática cuando hay ventanas maximizadas para no consumir recursos innecesarios.
    *   **Modo Ahorro de Energía**: Detecta si estás usando batería (en portátiles) y pausa los fondos automáticamente.
    *   **Límite de FPS**: Opción experimental para limitar la tasa de cuadros y reducir el uso de CPU/GPU.
*   📂 **Gestión de Biblioteca**: 
    *   Importa videos individuales o carpetas completas.
    *   Los videos se organizan automáticamente en `~/Videos/Komorebi`.
    *   Generación automática de miniaturas (thumbnails).
*   🎛️ **Control Total**:
    *   **System Tray**: La aplicación se ejecuta en segundo plano con un icono en la bandeja del sistema.
    *   **Audio**: Control de volumen independiente y opción de silenciar.
    *   **Interfaz Moderna**: GUI oscura y minimalista basada en PySide6.

## 🚀 Requisitos

*   **Sistema Operativo**: Linux.
*   **Sesión Gráfica**: Wayland (Probado y optimizado para GNOME Shell).
*   **Python**: 3.10 o superior.
*   **Dependencias del Sistema**:
    *   `ffmpeg` (miniaturas / thumbnails).
    *   `vlc` (reproducción en el servicio de fondo vía libVLC).
    *   `x11-utils` y `x11-xserver-utils` (usa `xprop`/`xrandr` en Wayland + XWayland).
    *   **Qt en modo XCB (XWayland)**: en algunas distros se requieren libs adicionales para el plugin `xcb`.

## 📦 Instalación

La forma más sencilla de instalar Komorebi es utilizando el script de instalación automatizado incluido.

1.  **Clonar el repositorio**:
    ```bash
    git clone https://github.com/evergaster/komorebi.git
    cd komorebi
    ```

2.  **Ejecutar el instalador**:
    ```bash
    chmod +x install.sh
    ./install.sh
    ```
    
    El script te guiará a través de un menú simple donde podrás elegir instalar o desinstalar la aplicación. Se encargará automáticamente de:
    *   Instalar dependencias del sistema (VLC, Python, etc.) para **Arch, Fedora, Debian y Ubuntu**.
    *   Crear un entorno virtual de Python aislado.
    *   Instalar las librerías necesarias.
    *   Crear el acceso directo en el menú de aplicaciones ("Komorebi Wallpaper").

### Instalación Manual

Si prefieres instalarlo manualmente o usas una distribución no soportada por el script:

1.  **Instalar dependencias del sistema**:
    *   **Debian/Ubuntu**: `sudo apt install python3 python3-pip python3-venv vlc ffmpeg`
    *   **Fedora**: `sudo dnf install python3 python3-pip vlc ffmpeg`
    *   **Arch**: `sudo pacman -S python python-pip vlc ffmpeg`

2.  **Configurar entorno Python**:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Ejecutar**:
    ```bash
    python3 main.py
    ```

## 🎮 Uso

Para iniciar la aplicación, simplemente busca **"Komorebi"** en tu menú de aplicaciones (si usaste el instalador) o ejecuta `python3 main.py` desde la terminal.

```bash
python main.py
```

1.  **Añadir Fondos**:
    *   Usa el botón **"+ Importar Video"** para añadir un archivo suelto.
    *   Usa **"📂 Importar Carpeta"** para escanear y añadir múltiples videos a la vez.
2.  **Aplicar Fondo**:
    *   Selecciona el monitor deseado en la parte superior (1, 2, etc.).
    *   Haz clic en el botón **"Aplicar"** de la tarjeta del video que quieras usar.
3.  **Configuración**:
    *   Ve a la pestaña **"⚙ Configuración"** para activar el inicio automático, el modo de ahorro de energía o ajustar el volumen.

> **Nota**: Al cerrar la ventana principal, Komorebi seguirá ejecutándose en la bandeja del sistema. Para cerrarlo totalmente, haz clic derecho en el icono de la bandeja y selecciona "Salir Totalmente".

## 🛠️ Tecnologías

Este proyecto ha sido construido utilizando:

*   **[Python](https://www.python.org/)**: Lógica principal.
*   **[PySide6 (Qt for Python)](https://doc.qt.io/qtforpython/)**: Interfaz gráfica y motor multimedia.
*   **[FFmpeg](https://ffmpeg.org/)**: Procesamiento de video para miniaturas.
*   **[psutil](https://github.com/giampaolo/psutil)**: Monitorización del estado de la batería.

## 🤝 Contribuir

¡Las contribuciones son bienvenidas! Si tienes ideas para mejorar Komorebi:

1.  Haz un Fork del repositorio.
2.  Crea una rama para tu característica (`git checkout -b feature/AmazingFeature`).
3.  Haz Commit de tus cambios (`git commit -m 'Add some AmazingFeature'`).
4.  Haz Push a la rama (`git push origin feature/AmazingFeature`).
5.  Abre un Pull Request.

Si encuentras algún error, por favor repórtalo en la sección de [Issues](https://github.com/evergaster/komorebi/issues).

---
Hecho con ❤️ por [Evergaster](https://github.com/evergaster).
