#!/bin/bash

HOOK_DIR="$(dirname "$(readlink -f "$0")")"
cat | python3 "$HOOK_DIR/lib/secret_scan.py"