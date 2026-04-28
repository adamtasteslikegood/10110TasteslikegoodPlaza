#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
daemon_dir="$repo_root/alirez-claude-skills/pm-daemon"
venv_python="$daemon_dir/.venv/bin/python"
requirements="$daemon_dir/requirements.txt"

if [[ ! -x "$venv_python" ]]; then
  echo "PM daemon venv not found. Creating $daemon_dir/.venv" >&2
  if ! python3 -m venv "$daemon_dir/.venv"; then
    cat >&2 <<'EOF'
Failed to create the PM daemon virtualenv. Install Python venv support, then retry.
Debian/Ubuntu example: sudo apt install python3.12-venv
EOF
    exit 1
  fi
  "$venv_python" -m pip install --upgrade pip >/dev/null
  "$venv_python" -m pip install -r "$requirements"
fi

cd "$repo_root"
exec "$venv_python" "$daemon_dir/pm_daemon.py" "$@"
