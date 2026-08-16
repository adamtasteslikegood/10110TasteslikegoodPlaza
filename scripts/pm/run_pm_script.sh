#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
pm_dir="$repo_root/scripts/pm"
venv_dir="$pm_dir/.venv"
venv_python="$venv_dir/bin/python"
requirements="$pm_dir/requirements.txt"
script_name="${1:-}"

if [[ -z "$script_name" ]]; then
  echo "Usage: bash scripts/pm/run_pm_script.sh <script.py> [args...]" >&2
  exit 1
fi

script_path="$pm_dir/$script_name"
if [[ ! -f "$script_path" ]]; then
  echo "PM script not found: $script_path" >&2
  exit 1
fi

deps_stamp="$venv_dir/.deps-installed"

if [[ ! -x "$venv_python" ]]; then
  echo "PM scripts venv not found. Creating $venv_dir" >&2
  if ! python3 -m venv "$venv_dir"; then
    cat >&2 <<'EOF'
Failed to create the PM scripts virtualenv. Install Python venv support, then retry.
Debian/Ubuntu example: sudo apt install python3.12-venv
EOF
    exit 1
  fi
fi

# The stamp is written only after a complete install, so a bootstrap killed
# mid-install retries here instead of leaving a venv with missing packages.
# A requirements.txt newer than the stamp also re-installs, so dependency
# updates aren't skipped.
if [[ ! -f "$deps_stamp" || "$requirements" -nt "$deps_stamp" ]]; then
  # stderr so stdout stays clean for callers that parse script output
  "$venv_python" -m pip install --upgrade pip >&2
  "$venv_python" -m pip install -r "$requirements" >&2
  touch "$deps_stamp"
fi

shift
cd "$repo_root"
exec "$venv_python" "$script_path" "$@"
