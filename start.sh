#!/bin/bash
# Start the RealSense Person Follow Demo
# Requires sudo for USB access on macOS

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIBREALSENSE_PATH="${LIBREALSENSE_PATH:-$HOME/Projects/librealsense/build/Release}"

# Use the realsense conda environment (Python 3.9 with all dependencies)
CONDA_PYTHON="${CONDA_PYTHON:-$HOME/miniconda3/envs/realsense/bin/python}"

if [ ! -d "$LIBREALSENSE_PATH" ]; then
    echo "Error: librealsense not found at $LIBREALSENSE_PATH"
    echo "Set LIBREALSENSE_PATH to your librealsense/build/Release directory"
    exit 1
fi

if [ ! -f "$CONDA_PYTHON" ]; then
    echo "Error: Python not found at $CONDA_PYTHON"
    echo "Set CONDA_PYTHON to your conda python path"
    exit 1
fi

echo "Using librealsense from: $LIBREALSENSE_PATH"
echo "Using Python from: $CONDA_PYTHON"
echo ""

cd "$SCRIPT_DIR"
# Use sudo with env to properly pass PYTHONPATH
sudo env PYTHONPATH="$LIBREALSENSE_PATH" "$CONDA_PYTHON" run.py "$@"
