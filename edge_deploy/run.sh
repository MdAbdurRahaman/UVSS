#!/usr/bin/env bash
# Start the UVSS edge service. Arguments are passed through.
cd "$(dirname "$0")"

PYEXE=python3
[ -x ./.venv/bin/python ] && PYEXE=./.venv/bin/python

exec "$PYEXE" server.py "$@"
