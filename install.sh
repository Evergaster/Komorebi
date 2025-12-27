#!/bin/bash

set -e  # Salir inmediatamente si un comando falla

# Colores para el output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Directorios y rutas
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
ICON_PATH="$PROJECT_DIR/icons/Komorebi.png"
DESKTOP_FILE="$HOME/.local/share/applications/komorebi.desktop"
WRAPPER_SCRIPT="$PROJECT_DIR/run_komorebi.sh"
USER_ICON_DIR="$HOME/.local/share/icons"

detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    else
        echo "unknown"
    fi
}

check_wayland() {
    if [ "$XDG_SESSION_TYPE" != "wayland" ]; then
        echo -e "${YELLOW}ADVERTENCIA: No estás en una sesión Wayland.${NC}"
        read -p "¿Deseas continuar con la instalación? [s/N]: " confirm
        [[ ! $confirm =~ ^[sS]$ ]] && exit 1
    fi
}

install_system_deps() {
    DISTRO=$(detect_distro)
    echo -e "${BLUE}Instalando dependencias de sistema para $DISTRO...${NC}"
    
    case "$DISTRO" in
        arch|manjaro|endeavouros)
            sudo pacman -S --needed python python-pip vlc ffmpeg python-gobject base-devel
            ;;
        fedora)
            sudo dnf install -y python3 python3-pip vlc ffmpeg python3-gobject python3-devel gcc
            ;;
        ubuntu|debian|pop|linuxmint|zorin)
            sudo apt update
            sudo apt install -y python3 python3-pip python3-venv vlc ffmpeg \
                libglib2.0-dev python3-gi python3-gi-cairo build-essential python3-dev
            ;;
        *)
            echo -e "${RED}Distribución no soportada automáticamente. Instala vlc, ffmpeg y python-gi manualmente.${NC}"
            ;;
    esac
}

install_python_deps() {
    echo -e "${BLUE}Configurando entorno virtual (con acceso a paquetes de sistema)...${NC}"
    
    [ -d "$VENV_DIR" ] && rm -rf "$VENV_DIR"
    
    # --system-site-packages permite usar el 'gi' (Gio) instalado por sudo apt/pacman
    python3 -m venv --system-site-packages "$VENV_DIR"
    
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip wheel
    echo -e "${BLUE}Instalando dependencias de Python en el venv...${NC}"
    pip install PySide6 python-vlc python-xlib psutil
    
    if [ -f "pyproject.toml" ]; then
        pip install -e .
    fi
    deactivate
}

create_desktop_entry() {
    echo -e "${BLUE}Configurando icono y acceso directo...${NC}"
    
    # 1. Asegurar permisos del wrapper
    chmod +x "$WRAPPER_SCRIPT"

    # 2. Registrar icono en el sistema del usuario para máxima compatibilidad
    mkdir -p "$USER_ICON_DIR"
    if [ -f "$ICON_PATH" ]; then
        cp "$ICON_PATH" "$USER_ICON_DIR/komorebi.png"
        FINAL_ICON="$USER_ICON_DIR/komorebi.png"
    else
        echo -e "${YELLOW}Icono no encontrado en $ICON_PATH, usando genérico.${NC}"
        FINAL_ICON="video-display"
    fi

    # 3. Crear el archivo .desktop con rutas absolutas citadas
    mkdir -p "$HOME/.local/share/applications"
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=Komorebi
Comment=Wallpapers Animados para Linux
Exec="$WRAPPER_SCRIPT"
Icon=$FINAL_ICON
Terminal=false
Type=Application
Categories=Utility;Settings;DesktopSettings;
StartupNotify=true
StartupWMClass=komorebi
EOF

    chmod +x "$DESKTOP_FILE"

    # 4. Refrescar base de datos de GNOME
    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$HOME/.local/share/applications"
    fi
    
    # Forzar actualización de caché de iconos
    touch "$HOME/.local/share/applications"
    
    echo -e "${GREEN}✓ Acceso directo creado en: $DESKTOP_FILE${NC}"
}

uninstall() {
    echo -e "${YELLOW}Desinstalando Komorebi...${NC}"
    pkill -f "komorebi" || true
    rm -rf "$VENV_DIR"
    rm -f "$DESKTOP_FILE"
    rm -f "$USER_ICON_DIR/komorebi.png"
    echo -e "${GREEN}✓ Desinstalación completa.${NC}"
}

# Ejecución principal
clear
echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}    Instalador Komorebi Wallpaper        ${NC}"
echo -e "${BLUE}=========================================${NC}"
echo "1) Instalar"
echo "2) Desinstalar"
echo "3) Salir"
echo -e "${BLUE}=========================================${NC}"
read -p "Selecciona una opción: " opt

case $opt in
    1)
        check_wayland
        install_system_deps
        install_python_deps
        create_desktop_entry
        echo -e "\n${GREEN}¡INSTALACIÓN COMPLETADA!${NC}"
        echo -e "Busca 'Komorebi' en tu menú de aplicaciones."
        ;;
    2)
        uninstall
        ;;
    3)
        exit 0
        ;;
    *)
        echo "Opción inválida."
        ;;
esac