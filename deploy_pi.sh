#!/bin/bash
# Deploy changed instrument_cluster source files to the Pi as bytecode-only (.pyc).
#
# Usage:
#   ./deploy_pi.sh [file ...]
#
# Each [file] is a path relative to src/instrument_cluster, e.g.:
#   ./deploy_pi.sh ui/widgets/current_lap_time_widget.py ui/views/dashboard_view.py
#
# Non-.py files (the bundled db/*.json) are copied verbatim — the package is
# bytecode-only, but its data files are still data files.

set -euo pipefail

if [[ $# -eq 0 ]]; then
  cat >&2 <<EOF
Usage: ./deploy_pi.sh <file> [file ...]

Deploy instrument_cluster source files to the Pi as bytecode-only (.pyc).
Each <file> is a path relative to src/instrument_cluster, e.g.:

  ./deploy_pi.sh ui/widgets/current_lap_time_widget.py ui/views/dashboard_view.py

Environment:
  PI_HOST  Pi ssh target (default: root@instrument-cluster.local)
  PYTHON   Python 3.12 interpreter used to compile (default: .venv/bin/python)
EOF
  exit 1
fi

# The Pi's DHCP address changes with every image flash — the mDNS name is
# the stable way to reach it.
PI_HOST="${PI_HOST:-root@instrument-cluster.local}"
PI_INSTALL_ROOT="/usr/lib/python3.12/site-packages/instrument_cluster"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$REPO_ROOT/src/instrument_cluster"

# The .pyc must be compiled by Python 3.12 to match the Pi's interpreter —
# anything else fails on the Pi at import time with "bad magic number".
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' 2>/dev/null; then
  echo "error: $PYTHON is not Python 3.12 (the Pi runs 3.12); set PYTHON=<3.12 interpreter>" >&2
  exit 1
fi

FILES=("$@")

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

echo "Making rootfs writable..."
ssh "$PI_HOST" "mount -o remount,rw /"

for rel_path in "${FILES[@]}"; do
  src_file="$SRC_ROOT/$rel_path"
  if [[ ! -f "$src_file" ]]; then
    echo "error: $src_file does not exist" >&2
    exit 1
  fi

  rel_dir="$(dirname "$rel_path")"
  remote_dir="$PI_INSTALL_ROOT/$rel_dir"
  ssh "$PI_HOST" "mkdir -p '$remote_dir'"

  if [[ "$rel_path" != *.py ]]; then
    # Data file (db/*.json): nothing to compile, ship it as it is.
    echo "Copying $rel_path -> $PI_HOST:$remote_dir/"
    scp "$src_file" "$PI_HOST:$remote_dir/"
    continue
  fi

  base_name="$(basename "$rel_path" .py)"
  out_dir="$TMPDIR/$rel_dir"
  mkdir -p "$out_dir"
  out_file="$out_dir/${base_name}.pyc"

  echo "Compiling $rel_path"
  "$PYTHON" -c "import py_compile; py_compile.compile('$src_file', cfile='$out_file', doraise=True)"

  echo "Copying ${base_name}.pyc -> $PI_HOST:$remote_dir/"
  scp "$out_file" "$PI_HOST:$remote_dir/${base_name}.pyc"
done

# The remount,ro must happen while the service is stopped — a running cluster
# pins the rootfs writable via a shared-writable mmap of mesa's shader cache.
echo "Restoring read-only rootfs and restarting instrument-cluster..."
ssh "$PI_HOST" "systemctl stop instrument-cluster; sync; mount -o remount,ro /; systemctl start instrument-cluster; sleep 2; systemctl is-active instrument-cluster"
