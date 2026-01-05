#!/bin/bash

set -e  

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

BASE_DIR="$HOME/.local/share/komorebi"
VENV_DIR="$BASE_DIR/.venv"
DESKTOP_FILE="$HOME/.local/share/applications/komorebi.desktop"
USER_ICON_DIR="$HOME/.local/share/icons"
WRAPPER_SCRIPT="$BASE_DIR/run_komorebi.sh"

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

deploy_files() {
    echo -e "${BLUE}Moviendo archivos a la ruta permanente: $BASE_DIR${NC}"

    pkill -f "komorebi" || true
    
    mkdir -p "$BASE_DIR"
    cp -r ./* "$BASE_DIR/"
    
    mkdir -p "$USER_ICON_DIR"
    if [ -f "$BASE_DIR/icons/Komorebi.png" ]; then
        cp "$BASE_DIR/icons/Komorebi.png" "$USER_ICON_DIR/komorebi.png"
    fi
}

install_python_deps() {
    echo -e "${BLUE}Configurando entorno virtual en la ruta permanente...${NC}"
    
    cd "$BASE_DIR"

    python3 -m venv --system-site-packages "$VENV_DIR"
    
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip wheel
    echo -e "${BLUE}Instalando dependencias de Python...${NC}"

    pip install PySide6 python-vlc python-xlib psutil setproctitle
    
    if [ -f "pyproject.toml" ]; then
        pip install -e .
    fi
    deactivate
}

create_desktop_entry() {
    echo -e "${BLUE}Configurando acceso directo y lanzador...${NC}"

    cat > "$WRAPPER_SCRIPT" << EOF
#!/bin/bash
DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
source "\$DIR/.venv/bin/activate"
export QT_QPA_PLATFORM=xcb
exec python "\$DIR/main.py" "\$@"
EOF
    chmod +x "$WRAPPER_SCRIPT"

    mkdir -p "$HOME/.local/share/applications"
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=Komorebi
Comment=Wallpapers Animados
Exec="$WRAPPER_SCRIPT"
Icon=$USER_ICON_DIR/komorebi.png
Terminal=false
Type=Application
Categories=Utility;Settings;
StartupNotify=true
StartupWMClass=komorebi
EOF

    chmod +x "$DESKTOP_FILE"

    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$HOME/.local/share/applications"
    fi

    touch "$HOME/.local/share/applications"
}

uninstall() {
    echo -e "${YELLOW}Eliminando Komorebi de la ruta permanente...${NC}"
    pkill -f "komorebi" || true
    rm -rf "$BASE_DIR"
    rm -f "$DESKTOP_FILE"
    rm -f "$USER_ICON_DIR/komorebi.png"
    echo -e "${GREEN}✓ Desinstalación completa.${NC}"
}

install() {
    check_wayland
    install_system_deps
    deploy_files
    install_python_deps
    create_desktop_entry
    
    echo -e "\n${GREEN}¡INSTALACIÓN COMPLETADA!${NC}"
    echo -e "Los archivos se han movido a: ${BLUE}$BASE_DIR${NC}"
    echo -e "${YELLOW}Ya puedes borrar la carpeta del git clone.${NC}"
    echo -e "Busca 'Komorebi' en tu menú de aplicaciones."
}
clear
echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}    Instalador Komorebi (Permanente)     ${NC}"
echo -e "${BLUE}=========================================${NC}"
echo "1) Instalar"
echo "2) Desinstalar"
echo "3) Salir"
echo -e "${BLUE}=========================================${NC}"
read -p "Selecciona una opción: " opt

case $opt in
    1) install ;;
    2) uninstall ;;
    3) exit 0 ;;
    *) echo "Opción inválida." ;;
esac