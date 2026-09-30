#!/bin/bash
# Double-click this file in Finder to launch Cue.
# Activates the project's virtualenv and runs cue.py with it.
cd "$(dirname "$0")"

if [ ! -f ".venv/bin/activate" ]; then
    echo "No virtualenv found at .venv -- set one up first:"
    echo "  python3.11 -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install -r requirements.txt"
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
fi

source .venv/bin/activate
python cue.py

read -n 1 -s -r -p "Press any key to close..."
