#!/usr/bin/env bash
# Planted: unquoted variable for ShellCheck SC2086 (W6)
set -euo pipefail
TARGET=$1
echo deploying to $TARGET
