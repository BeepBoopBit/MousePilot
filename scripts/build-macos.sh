#!/bin/sh
# Build a native app on macOS 14+. Run once per CPU architecture.
set -eu
cd "$(dirname "$0")/.."
[ "$(uname -s)" = Darwin ] || { echo 'Build on macOS'; exit 1; }
uv sync --locked --extra build
uv run --extra build pyinstaller --clean --noconfirm scripts/macos.spec
codesign --verify --deep --strict dist/MousePilot.app
uv run --extra build python scripts/collect-licenses.py
cp LICENSE THIRD_PARTY_NOTICES.md dist/
# ditto preserves framework symlinks and the app's resource signature.
archive="mousepilot-macos-$(uname -m).zip"
staging="build/macos-package"
mkdir -p "$staging"
ditto dist/MousePilot.app "$staging/MousePilot.app"
ditto dist/third-party "$staging/third-party"
cp LICENSE THIRD_PARTY_NOTICES.md "$staging/"
uv run --extra build python scripts/package-info.py --output "$staging/package-info.json"
ditto -c -k --sequesterRsrc "$staging" "dist/$archive"
(cd dist && shasum -a 256 "$archive" > SHA256SUMS)
