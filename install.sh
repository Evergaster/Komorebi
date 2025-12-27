#!/bin/bash

set -e  # Salir si hay errores

# Colores para el output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Directorios del proyecto
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
ICON_PATH="$PROJECT_DIR/icons/Komorebi.png"
DESKTOP_FILE="$HOME/.local/share/applications/komorebi.desktop"
WRAPPER_SCRIPT="$PROJECT_DIR/run_komorebi.sh"

# Función para detectar la distribución
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    else
        echo "unknown"
    fi
}

# Verificar sesión Wayland
check_wayland() {
    if [ "$XDG_SESSION_TYPE" != "wayland" ]; then
        echo -e "${YELLOW}ADVERTENCIA: Se ha detectado una sesión $XDG_SESSION_TYPE.${NC}"
        echo -e "${YELLOW}Komorebi está diseñado principalmente para Wayland.${NC}"
        read -p "¿Deseas continuar? [s/N]: " confirm
        [[ ! $confirm =~ ^[sS]$ ]] && exit 1
    fi
}

# Instalación de dependencias del sistema (Incluye FFmpeg y Gio)
install_system_deps() {
    DISTRO=$(detect_distro)
    echo -e "${BLUE}Detectada distribución: $DISTRO${NC}"
    echo -e "${BLUE}Instalando dependencias de sistema (requiere sudo)...${NC}"
    
    case "$DISTRO" in
        arch|manjaro|endeavouros)
            sudo pacman -S --needed python python-pip vlc ffmpeg python-gobject \
                base-devel libxcb xcb-util-wm
            ;;
        fedora)
            sudo dnf install -y python3 python3-pip vlc ffmpeg python3-gobject \
                python3-devel gcc libxcb xcb-util-wm
            ;;
        ubuntu|debian|pop|linuxmint|kali|zorin)
            sudo apt update
            sudo apt install -y python3 python3-pip python3-venv vlc ffmpeg \
                libglib2.0-dev python3-gi python3-gi-cairo build-essential \
                python3-dev libxcb1-dev libxcb-ewmh-dev
            ;;
        *)
            echo -e "${RED}Distribución no reconocida. Asegúrate de tener: vlc, ffmpeg y python-gi.${NC}"
            read -p "Presiona Enter para intentar continuar..."
            ;;
    esac
}

# Configuración de Python y VENV (Con acceso a librerías de sistema para Gio)
install_python_deps() {
    echo -e "${BLUE}Configurando entorno virtual...${NC}"
    
    # Eliminamos venv viejo si existe para evitar conflictos
    [ -d "$VENV_DIR" ] && rm -rf "$VENV_DIR"
    
    # --system-site-packages es CRÍTICO para que el venv vea el 'gi' (Gio) del sistema
    python3 -m venv --system-site-packages "$VENV_DIR"
    
    source "$VENV_DIR/bin/activate"
    
    echo -e "${BLUE}Instalando dependencias de Python...${NC}"
    pip install --upgrade pip wheel
    pip install PySide6 python-vlc psutil
    
    # Instalar el proyecto en modo editable si existe el config
    if [ -f "pyproject.toml" ] || [ -f "setup.py" ]; then
        pip install -e .
    fi
    
    deactivate
}

# Creación del lanzador y el icono (Rutas Absolutas)
create_desktop_entry() {
    echo -e "${BLUE}Configurando acceso directo...${NC}"
    
    # 1. Asegurar que el wrapper script tenga permisos de ejecución
    if [ -f "$WRAPPER_SCRIPT" ]; then
        chmod +x "$WRAPPER_SCRIPT"
        echo -e "${GREEN}✓ Script de ejecución configurado.${NC}"
    else
        echo -e "${RED}Error: No se encontró $WRAPPER_SCRIPT${NC}"
        exit 1
    fi

    # 2. Validar icono
    if [ ! -f "$ICON_PATH" ]; then
        echo -e "${YELLOW}Aviso: No se encontró el icono en $ICON_PATH. Usando genérico.${NC}"
        FINAL_ICON="video-display"
    else
        FINAL_ICON="$ICON_PATH"
    fi

    # 3. Crear el archivo .desktop
    mkdir -p "$HOME/.local/share/applications"
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=Komorebi
Comment=Wallpapers Animados
Exec=$WRAPPER_SCRIPT
Icon=$FINAL_ICON
Terminal=false
Type=Application
Categories=Utility;Settings;
StartupNotify=true
StartupWMClass=Komorebi
EOF
    chmod +x "$DESKTOP_FILE"

    # 4. Actualizar base de datos de escritorio (Para que aparezca el icono)
    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$HOME/.local/share/applications"
    fi
    echo -e "${GREEN}✓ Acceso directo creado en el menú de aplicaciones.${NC}"
}

# Limpieza total
uninstall() {
    echo -e "${YELLOW}Desinstalando Komorebi...${NC}"
    pkill -f "komorebi" || true
    rm -rf "$VENV_DIR"
    rm -f "$DESKTOP_FILE"
    rm -f "$WRAPPER_SCRIPT"
    rm -rf "/dev/shm/komorebi-sync"
    rm -f "/dev/shm/komorebi_wall.log"
    rm -f "/tmp/komorebi.lock"
    echo -e "${GREEN}✓ Desinstalación completa.${NC}"
}

install() {
    check_wayland
    install_system_deps
    install_python_deps
    create_desktop_entry
    echo -e "\n${GREEN}¡INSTALACIÓN EXITOSA!${NC}"
    echo -e "Ya puedes buscar ${BLUE}Komorebi${NC} en tu menú de aplicaciones."
}

# Menú interactivo
clear
echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}    Instalador Komorebi (Optimizado)     ${NC}"
echo -e "${BLUE}=========================================${NC}"
echo "1) Instalar / Reparar"
echo "2) Desinstalar"
echo "3) Salir"
echo -e "${BLUE}=========================================${NC}"
read -p "Selecciona una opción [1-3]: " opt

case $opt in
    1) install ;;
    2) uninstall ;;
    3) exit 0 ;;
    *) echo "Opción inválida" ;;
esac