#!/bin/bash
# Double-click this file in Finder to launch Cue. The server runs
# detached in the background (see cue.py), so once it's up this window
# closes itself -- no terminal needs to stay open.
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
STATUS=$?

if [ $STATUS -ne 0 ]; then
    read -n 1 -s -r -p "Something went wrong -- press any key to close..."
    exit $STATUS
fi

# Close this Terminal window automatically -- the server keeps running
# detached, so there's nothing left for the terminal to do. Matches by
# this exact tty so it only ever closes its own window, never another
# Terminal window the user has open.
osascript <<APPLESCRIPT 2>/dev/null
tell application "Terminal"
    repeat with w in windows
        repeat with t in tabs of w
            if tty of t is "$(tty)" then
                close w
                return
            end if
        end repeat
    end repeat
end tell
APPLESCRIPT
