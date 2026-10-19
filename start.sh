#!/bin/sh
# Opens the welcome page. First run also installs what jobscan needs (a minute or two).
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 isn't installed. Get it from https://www.python.org/downloads/ and run this again."
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting jobscan up..."
  python3 -m venv .venv && .venv/bin/python -m pip install --quiet --upgrade pip \
    && .venv/bin/python -m pip install --quiet -r requirements.txt || { echo "Setup failed - see the message above."; exit 1; }
fi
.venv/bin/python -m jobscan.onboard
