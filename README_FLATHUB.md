# Empaquetado para Flathub

Este directorio contiene los archivos necesarios para empaquetar **Komorebi** en Flatpak y enviarlo a Flathub.

## Prerrequisitos

1.  Instalar `flatpak` y `flatpak-builder`.
2.  Instalar `flatpak-pip-generator` (herramienta para generar manifiestos de dependencias Python).

## Pasos para construir

### 1. Preparar módulos compartidos (VLC)
Komorebi necesita VLC. Usaremos los módulos compartidos de Flathub.

```bash
git clone https://github.com/flathub/shared-modules.git
```

### 2. Generar dependencias de Python
Flatpak no permite acceso a internet durante la construcción, por lo que debemos pre-descargar o definir todas las dependencias.

```bash
# Descargar el script si no lo tienes
wget https://raw.githubusercontent.com/flatpak/flatpak-builder-tools/master/pip/flatpak-pip-generator
chmod +x flatpak-pip-generator

# Generar el manifiesto de dependencias
./flatpak-pip-generator -r requirements.txt --output python3-requirements
```
Esto generará el archivo `python3-requirements.json`.

### 3. Construir e Instalar (Prueba Local)

```bash
flatpak-builder --user --install --force-clean build-dir io.github.evergaster.Komorebi.yml
```

### 4. Ejecutar

```bash
flatpak run io.github.evergaster.Komorebi
```

## Estructura de Archivos

*   `io.github.evergaster.Komorebi.yml`: El manifiesto principal de Flatpak.
*   `io.github.evergaster.Komorebi.desktop`: Archivo de escritorio para integración con el sistema.
*   `komorebi-runner.sh`: Script de arranque que configura el entorno (PYTHONPATH, etc.).
*   `requirements.txt`: Lista de dependencias de Python directas.
