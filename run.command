#!/bin/bash
# Runs Cratez from source on macOS without building the app.
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run - setting up..."
  python3 -m venv .venv && .venv/bin/python -m pip install --upgrade -r requirements.txt || { read -n 1 -s -r -p "Setup failed - press any key"; exit 1; }
fi
nohup .venv/bin/python app.py >/dev/null 2>&1 &
