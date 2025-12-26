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

1.  **Clonar el repositorio**:
    ```bash
    git clone https://github.com/evergaster/komorebi.git
    cd komorebi
    ```

2.  **Crear un entorno virtual (Recomendado)**:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Instalar dependencias de Python**:
    ```bash
    pip install PySide6 python-vlc psutil
    ```

4.  **Instalar dependencias del sistema (Debian/Ubuntu)**:
    ```bash
        sudo apt install ffmpeg vlc x11-utils x11-xserver-utils \
            libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-randr0 \
            libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 libxrender1
    ```

> Nota: el paquete `.deb` declara dependencias adicionales típicas de Qt (`xcb`, OpenGL, DBus) y recomienda plugins de VLC; si instalas desde fuentes, podrías necesitarlas según tu distro.

## 🧱 Construcción del paquete .deb

Este repositorio incluye un script que genera un binario con PyInstaller y lo empaqueta como `.deb`.

1. **Dependencias de build (Debian/Ubuntu)**:
    ```bash
    sudo apt install dpkg-dev fakeroot ffmpeg
    ```
    - `ImageMagick` es opcional (si no está, se usa `ffmpeg` para generar el icono PNG).

2. **Dependencias Python de build**:
    ```bash
    pip install pyinstaller
    ```

3. **Construir**:
    ```bash
    ./build_deb.sh
    ```

El resultado será un archivo del estilo: `komorebi_1.1.0_<arquitectura>.deb`.

### Si al instalar el .deb no abre

- Ejecuta desde terminal `/usr/bin/komorebi` para ver errores.
- Si falla al arrancar, revisa el log: `/tmp/komorebi_startup_error.log`.

## 🎮 Uso

Para iniciar la aplicación:

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
