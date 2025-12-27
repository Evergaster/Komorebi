#!/bin/bash

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
EXEC_PATH="$VENV_DIR/bin/python $PROJECT_DIR/main.py"

# Función para detectar la distribución
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    else
        echo "unknown"
    fi
}

# Función para instalar dependencias del sistema
install_system_deps() {
    DISTRO=$(detect_distro)
    echo -e "${BLUE}Detectada distribución: $DISTRO${NC}"
    
    echo -e "${BLUE}Instalando dependencias del sistema (se requerirá contraseña de root)...${NC}"
    
    case "$DISTRO" in
        arch|manjaro|endeavouros)
            sudo pacman -S --needed python python-pip vlc base-devel
            ;;
        fedora)
            sudo dnf install python3 python3-pip vlc python3-devel gcc
            ;;
        ubuntu|debian|pop|linuxmint|kali)
            sudo apt update
            sudo apt install -y python3 python3-pip python3-venv vlc build-essential python3-dev
            ;;
        *)
            echo -e "${RED}Distribución no soportada automáticamente. Por favor instala python3, pip y vlc manualmente.${NC}"
            read -p "Presiona Enter para continuar de todos modos..."
            ;;
    esac
}

# Función para crear entorno virtual e instalar dependencias de Python
install_python_deps() {
    echo -e "${BLUE}Configurando entorno virtual de Python...${NC}"
    
    if [ ! -d "$VENV_DIR" ]; then
        python3 -m venv "$VENV_DIR"
    fi
    
    source "$VENV_DIR/bin/activate"
    
    echo -e "${BLUE}Instalando dependencias desde pyproject.toml...${NC}"
    pip install --upgrade pip
    # Instalar el paquete actual y sus dependencias
    pip install .
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Dependencias de Python instaladas correctamente.${NC}"
    else
        echo -e "${RED}Hubo un error instalando las dependencias de Python.${NC}"
        exit 1
    fi
}

# Función para crear el acceso directo .desktop
create_desktop_entry() {
    echo -e "${BLUE}Configurando acceso directo...${NC}"
    
    # Asegurar que el script de lanzamiento tenga permisos de ejecución
    WRAPPER_SCRIPT="$PROJECT_DIR/run_komorebi.sh"
    if [ -f "$WRAPPER_SCRIPT" ]; then
        chmod +x "$WRAPPER_SCRIPT"
    else
        echo -e "${RED}Error: No se encontró $WRAPPER_SCRIPT${NC}"
        exit 1
    fi
    
    mkdir -p "$HOME/.local/share/applications"
    
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=Komorebi
Comment=Gestor de fondos de pantalla animados
Exec="$WRAPPER_SCRIPT"
Icon=$ICON_PATH
Terminal=false
Type=Application
Categories=Utility;Settings;DesktopSettings;
StartupNotify=false
StartupWMClass=Komorebi
EOF

    chmod +x "$DESKTOP_FILE"
    
    # Intentar actualizar la base de datos de escritorio
    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$HOME/.local/share/applications"
    fi
    
    echo -e "${GREEN}Acceso directo creado en: $DESKTOP_FILE${NC}"
}

# Función principal de instalación
install() {
    echo -e "${GREEN}=== Iniciando Instalación de Komorebi ===${NC}"
    install_system_deps
    install_python_deps
    create_desktop_entry
    
    echo -e "\n${GREEN}¡Instalación completada con éxito!${NC}"
    echo -e "Puedes iniciar la aplicación buscando 'Komorebi' en tu menú de aplicaciones."
}

# Función de desinstalación
uninstall() {
    echo -e "${YELLOW}=== Desinstalando Komorebi ===${NC}"
    
    if [ -d "$VENV_DIR" ]; then
        echo -e "Eliminando entorno virtual..."
        rm -rf "$VENV_DIR"
    fi
    
    if [ -f "$DESKTOP_FILE" ]; then
        echo -e "Eliminando acceso directo..."
        rm "$DESKTOP_FILE"
    fi
    
    echo -e "${GREEN}Desinstalación completada.${NC}"
}

# Menú principal
show_menu() {
    clear
    echo -e "${BLUE}=========================================${NC}"
    echo -e "${BLUE}    Instalador de Komorebi Wallpaper     ${NC}"
    echo -e "${BLUE}=========================================${NC}"
    echo "1) Instalar"
    echo "2) Desinstalar"
    echo "3) Salir"
    echo -e "${BLUE}=========================================${NC}"
    read -p "Selecciona una opción [1-3]: " option

    case $option in
        1)
            install
            ;;
        2)
            uninstall
            ;;
        3)
            echo "Saliendo..."
            exit 0
            ;;
        *)
            echo -e "${RED}Opción inválida.${NC}"
            sleep 1
            show_menu
            ;;
    esac
}

# Ejecutar menú
show_menu
