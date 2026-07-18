#!/bin/bash
# Launch the Claude Code progress sidebar (native macOS floating panel).
# MUST use the system python3 (/usr/bin/python3) — it ships with PyObjC/AppKit.
# Usage: ./run.sh            -> track newest session anywhere
#        ./run.sh /some/path -> only track sessions under that path
cd "$(dirname "$0")"
exec /usr/bin/python3 progress_sidebar.py ${1:+--cwd "$1"}
