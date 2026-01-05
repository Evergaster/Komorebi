#!/bin/bash

# Obtener el directorio real donde está el script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Detectar ejecutable de Python en el entorno virtual
if [ -d "$SCRIPT_DIR/.venv" ]; then
    PYTHON_EXEC="$SCRIPT_DIR/.venv/bin/python"
elif [ -d "$SCRIPT_DIR/venv" ]; then
    PYTHON_EXEC="$SCRIPT_DIR/venv/bin/python"
else
    PYTHON_EXEC="python3"
fi

# Variable de entorno para asegurar compatibilidad con la ventana de fondo
export QT_QPA_PLATFORM=xcb

# Ejecutar la aplicación usando el intérprete del venv
exec "$PYTHON_EXEC" "$SCRIPT_DIR/main.py" "$@"