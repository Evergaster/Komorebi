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

# Función para verificar la versión de Python
check_python_version() {
    local python_cmd="$1"
    local version
    version=$($python_cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)
    
    if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
        return 0
    fi
    return 1
}

# Función para encontrar Python compatible
find_python() {
    for cmd in python3.13 python3.12 python3.11 python3; do
        if command -v "$cmd" &> /dev/null; then
            if check_python_version "$cmd"; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    echo ""
    return 1
}

# Función para instalar dependencias del sistema
install_system_deps() {
    DISTRO=$(detect_distro)
    echo -e "${BLUE}Detectada distribución: $DISTRO${NC}"
    
    echo -e "${BLUE}Instalando dependencias del sistema (se requerirá contraseña de root)...${NC}"
    
    case "$DISTRO" in
        arch|manjaro|endeavouros)
            sudo pacman -S --needed python python-pip vlc base-devel \
                gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly \
                qt6-multimedia qt6-multimedia-gstreamer libxcb xcb-util-wm
            ;;
        fedora)
            sudo dnf install -y python3 python3-pip vlc python3-devel gcc \
                gstreamer1 gstreamer1-plugins-base gstreamer1-plugins-good \
                gstreamer1-plugins-bad-free gstreamer1-plugins-ugly \
                qt6-qtmultimedia libxcb xcb-util-wm
            ;;
        ubuntu|debian|pop|linuxmint|kali|zorin)
            sudo apt update
            sudo apt install -y python3 python3-pip python3-venv vlc build-essential python3-dev \
                gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
                gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
                libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
                qt6-multimedia-dev libxcb1-dev libxcb-ewmh-dev libxcb-icccm4-dev \
                libgl1-mesa-dev libegl1-mesa-dev libxkbcommon-dev
            ;;
        opensuse*|suse*)
            sudo zypper install -y python3 python3-pip vlc python3-devel gcc \
                gstreamer-plugins-base gstreamer-plugins-good gstreamer-plugins-bad \
                gstreamer-plugins-ugly qt6-multimedia-devel libxcb-devel
            ;;
        *)
            echo -e "${YELLOW}Distribución no soportada automáticamente.${NC}"
            echo -e "${YELLOW}Por favor instala manualmente: python3 (>=3.11), pip, vlc, gstreamer y plugins de Qt6${NC}"
            read -p "Presiona Enter para continuar de todos modos..."
            ;;
    esac
}

# Función para crear entorno virtual e instalar dependencias de Python
install_python_deps() {
    echo -e "${BLUE}Buscando versión de Python compatible (>=3.11)...${NC}"
    
    PYTHON_CMD=$(find_python)
    if [ -z "$PYTHON_CMD" ]; then
        echo -e "${RED}Error: No se encontró Python >= 3.11${NC}"
        echo -e "${YELLOW}Por favor instala Python 3.11 o superior y vuelve a ejecutar el instalador.${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}Usando: $PYTHON_CMD ($($PYTHON_CMD --version))${NC}"
    
    echo -e "${BLUE}Configurando entorno virtual de Python...${NC}"
    
    if [ -d "$VENV_DIR" ]; then
        echo -e "${YELLOW}Entorno virtual existente encontrado. Recreando...${NC}"
        rm -rf "$VENV_DIR"
    fi
    
    $PYTHON_CMD -m venv "$VENV_DIR"
    
    if [ ! -f "$VENV_DIR/bin/activate" ]; then
        echo -e "${RED}Error: No se pudo crear el entorno virtual.${NC}"
        exit 1
    fi
    
    source "$VENV_DIR/bin/activate"
    
    echo -e "${BLUE}Actualizando pip...${NC}"
    pip install --upgrade pip wheel setuptools
    
    echo -e "${BLUE}Instalando dependencias desde pyproject.toml...${NC}"
    
    pip install -e .
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Dependencias de Python instaladas correctamente.${NC}"
    else
        echo -e "${RED}Hubo un error instalando las dependencias de Python.${NC}"
        deactivate 2>/dev/null
        exit 1
    fi
    
    deactivate
}

# Función para crear el acceso directo .desktop
create_desktop_entry() {
    echo -e "${BLUE}Configurando acceso directo...${NC}"
    
    if [ ! -f "$ICON_PATH" ]; then
        echo -e "${YELLOW}Advertencia: No se encontró el icono en $ICON_PATH${NC}"
        ICON_PATH="video-display"
    fi
    
    if [ -f "$WRAPPER_SCRIPT" ]; then
        chmod +x "$WRAPPER_SCRIPT"
    else
        echo -e "${YELLOW}Creando script de lanzamiento...${NC}"
        cat > "$WRAPPER_SCRIPT" << 'WRAPPER_EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -d ".venv" ]; then
    PYTHON_EXEC=".venv/bin/python"
elif [ -d "venv" ]; then
    PYTHON_EXEC="venv/bin/python"
else
    PYTHON_EXEC="python3"
fi

if [ ! -x "$PYTHON_EXEC" ] && [ "$PYTHON_EXEC" != "python3" ]; then
    PYTHON_EXEC="python3"
fi

exec "$PYTHON_EXEC" main.py "$@"
WRAPPER_EOF
        chmod +x "$WRAPPER_SCRIPT"
    fi
    
    chmod +x "$PROJECT_DIR/main.py"
    
    mkdir -p "$HOME/.local/share/applications"
    
    cat > "$DESKTOP_FILE" << DESKTOPEOF
[Desktop Entry]
Name=Komorebi
Comment=Gestor de fondos de pantalla animados
Exec=$WRAPPER_SCRIPT
Icon=$ICON_PATH
Terminal=false
Type=Application
Categories=Utility;Settings;DesktopSettings;
StartupNotify=false
StartupWMClass=Komorebi
DESKTOPEOF

    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi
    
    echo -e "${GREEN}Acceso directo creado en: $DESKTOP_FILE${NC}"
}

# Función para verificar la instalación
verify_installation() {
    echo -e "${BLUE}Verificando instalación...${NC}"
    
    local errors=0
    
    if [ ! -f "$VENV_DIR/bin/python" ]; then
        echo -e "${RED}✗ Entorno virtual no encontrado${NC}"
        errors=$((errors + 1))
    else
        echo -e "${GREEN}✓ Entorno virtual OK${NC}"
    fi
    
    if "$VENV_DIR/bin/python" -c "import PySide6" 2>/dev/null; then
        echo -e "${GREEN}✓ PySide6 OK${NC}"
    else
        echo -e "${RED}✗ PySide6 no instalado correctamente${NC}"
        errors=$((errors + 1))
    fi
    
    if [ -f "$DESKTOP_FILE" ]; then
        echo -e "${GREEN}✓ Acceso directo OK${NC}"
    else
        echo -e "${RED}✗ Acceso directo no creado${NC}"
        errors=$((errors + 1))
    fi
    
    if [ -x "$WRAPPER_SCRIPT" ]; then
        echo -e "${GREEN}✓ Script de lanzamiento OK${NC}"
    else
        echo -e "${RED}✗ Script de lanzamiento no ejecutable${NC}"
        errors=$((errors + 1))
    fi
    
    return $errors
}

# Función principal de instalación
install() {
    echo -e "${GREEN}=== Iniciando Instalación de Komorebi ===${NC}"
    echo ""
    
    install_system_deps
    echo ""
    
    install_python_deps
    echo ""
    
    create_desktop_entry
    echo ""
    
    verify_installation
    local result=$?
    
    echo ""
    if [ $result -eq 0 ]; then
        echo -e "${GREEN}¡Instalación completada con éxito!${NC}"
        echo -e "Puedes iniciar la aplicación:"
        echo -e "  - Buscando 'Komorebi' en tu menú de aplicaciones"
        echo -e "  - Ejecutando: ${BLUE}$WRAPPER_SCRIPT${NC}"
    else
        echo -e "${YELLOW}Instalación completada con advertencias.${NC}"
        echo -e "Revisa los errores anteriores."
    fi
}

# Función de desinstalación
uninstall() {
    echo -e "${YELLOW}=== Desinstalando Komorebi ===${NC}"
    
    pkill -f "komorebi" 2>/dev/null || true
    pkill -f "main.py" 2>/dev/null || true
    
    if [ -d "$VENV_DIR" ]; then
        echo -e "Eliminando entorno virtual..."
        rm -rf "$VENV_DIR"
    fi
    
    if [ -f "$DESKTOP_FILE" ]; then
        echo -e "Eliminando acceso directo..."
        rm "$DESKTOP_FILE"
    fi
    
    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi
    
    echo -e "${GREEN}Desinstalación completada.${NC}"
}

# Función para reinstalar
reinstall() {
    echo -e "${YELLOW}=== Reinstalando Komorebi ===${NC}"
    set +e
    uninstall
    set -e
    echo ""
    install
}

# Menú principal
show_menu() {
    clear
    echo -e "${BLUE}=========================================${NC}"
    echo -e "${BLUE}    Instalador de Komorebi Wallpaper     ${NC}"
    echo -e "${BLUE}=========================================${NC}"
    echo "1) Instalar"
    echo "2) Reinstalar"
    echo "3) Desinstalar"
    echo "4) Verificar instalación"
    echo "5) Salir"
    echo -e "${BLUE}=========================================${NC}"
    read -p "Selecciona una opción [1-5]: " option

    case $option in
        1)
            install
            ;;
        2)
            reinstall
            ;;
        3)
            uninstall
            ;;
        4)
            verify_installation
            ;;
        5)
            echo "Saliendo..."
            exit 0
            ;;
        *)
            echo -e "${RED}Opción inválida.${NC}"
            sleep 1
            show_menu
            ;;
    esac
    
    echo ""
    read -p "Presiona Enter para continuar..."
    show_menu
}

# Permitir ejecución directa con argumentos
case "${1:-}" in
    --install|-i)
        install
        ;;
    --uninstall|-u)
        uninstall
        ;;
    --reinstall|-r)
        reinstall
        ;;
    --verify|-v)
        verify_installation
        ;;
    --help|-h)
        echo "Uso: $0 [opción]"
        echo ""
        echo "Opciones:"
        echo "  --install, -i     Instalar Komorebi"
        echo "  --uninstall, -u   Desinstalar Komorebi"
        echo "  --reinstall, -r   Reinstalar Komorebi"
        echo "  --verify, -v      Verificar instalación"
        echo "  --help, -h        Mostrar esta ayuda"
        echo ""
        echo "Sin argumentos se muestra el menú interactivo."
        ;;
    *)
        show_menu
        ;;
esac
