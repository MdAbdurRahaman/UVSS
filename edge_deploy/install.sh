#!/usr/bin/env bash
# Install the UVSS edge service dependencies.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

echo "Installing dependencies..."
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt

echo
echo "For NVIDIA GPU inference:"
echo "    ./.venv/bin/python -m pip uninstall -y onnxruntime"
echo "    ./.venv/bin/python -m pip install onnxruntime-gpu"
echo
echo "Done. Start the service with:  ./run.sh"
