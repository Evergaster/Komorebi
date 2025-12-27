#!/bin/bash

# Obtener el directorio donde está el script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Detectar entorno virtual
if [ -d ".venv" ]; then
    PYTHON_EXEC=".venv/bin/python"
elif [ -d "venv" ]; then
    PYTHON_EXEC="venv/bin/python"
else
    PYTHON_EXEC="python3"
fi

# Verificar si el ejecutable de Python existe
if [ ! -x "$PYTHON_EXEC" ] && [ "$PYTHON_EXEC" != "python3" ]; then
    echo "Error: No se encontró el intérprete de Python en $PYTHON_EXEC"
    echo "Intentando con python3 del sistema..."
    PYTHON_EXEC="python3"
fi

# Ejecutar la aplicación
exec "$PYTHON_EXEC" main.py "$@"
