#!/bin/bash
# Run the same editable Python modules as the Windows launcher.
cd -- "$(dirname "$0")" || exit 1
if [ ! -x ".venv/bin/python" ]; then
    printf '%s\n' 'One-time setup is required. Follow the macOS steps in README.md.'
    printf '%s\n' 'Install Python with Tk, create .venv, then install requirements.txt.'
    read -r -p 'Press Return to close. ' reply
    exit 1
fi
".venv/bin/python" -B sensor_logger.py "$@"
result=$?
if [ "$result" -ne 0 ]; then
    printf '\n%s\n' 'The logger could not finish. Read the error above and the README.'
    read -r -p 'Press Return to close. ' reply
fi
exit "$result"
