# Build on macOS: uv run --extra build pyinstaller --noconfirm scripts/macos.spec
from pathlib import Path
import tomllib
import re
root = Path(SPECPATH).parent
version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
# Apple bundle version fields use the numeric release; retain the full Python beta version separately.
bundle_version = re.match(r"\d+\.\d+\.\d+", version).group()
analysis = Analysis([str(root / 'scripts/macos-entry.py')], pathex=[str(root / 'src')],
                    hiddenimports=['mousepilot.macos', 'mousepilot.macos_ui'], excludes=['pystray'])
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='MousePilot',
          console=False, codesign_identity=None)
collection = COLLECT(exe, analysis.binaries, analysis.datas, name='MousePilot')
app = BUNDLE(collection, name='MousePilot.app', bundle_identifier='io.mousepilot.server',
             info_plist={'CFBundleShortVersionString': bundle_version, 'CFBundleVersion': bundle_version, 'MousePilotVersion': version, 'LSUIElement': True, 'LSMinimumSystemVersion': '14.0',
                         'NSHighResolutionCapable': True,
                         'NSAccessibilityUsageDescription': 'MousePilot controls desktop windows and input at your request.',
                         'NSInputMonitoringUsageDescription': 'MousePilot listens for its emergency stop shortcut.',
                         'NSScreenCaptureUsageDescription': 'MousePilot captures screenshots for your connected agent.'})
