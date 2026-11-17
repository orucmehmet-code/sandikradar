#!/usr/bin/env bash
# SandikRadar yerel kopru
cd "$(dirname "$0")/.." || exit 1
exec python3 local-server/bridge.py
