#!/usr/bin/env bash
# Run contract test suites across every oak module.
set -euo pipefail

cd "$(dirname "$0")/.."

for pkg in packages/oak-*; do
    if [ -d "$pkg/src" ]; then
        echo "=== contract: $(basename "$pkg") ==="
        (cd "$pkg" && pytest -m contract -q) || exit 1
    fi
done
