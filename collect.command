#!/bin/sh
# macOS: double-click to collect today's new jobs.
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || ./start.sh
.venv/bin/python -m jobscan collect
echo; read -r -p "Press Return to close." _
