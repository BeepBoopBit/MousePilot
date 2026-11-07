# Third-party notices

The MIT license applies to MousePilot's own code. Dependencies retain their
copyrights and licenses; the project license does not relicense them.

The Windows build script creates `dist/third-party/` with installed dependency
license/notice files, the Python runtime license, a build-environment inventory,
and the hash-verified upstream pystray source matching `uv.lock`, pinned in
`scripts/third-party-sources.json`. The inventory
can include build tools that are not inside the executable. Distribute the
complete Windows ZIP with its notices rather than only the `.exe`.

Notable dependencies include the MCP Python SDK, Pillow, Pydantic, pystray, and
their transitive dependencies. Inspect the generated inventory for exact versions
and metadata. Metadata and automated collection do not replace review of the
actual license texts, particularly when changing dependencies or packaging.

## pystray

pystray 0.19.5 is LGPLv3. It is used without modifications and remains separately
licensed. Its version-matched upstream source archive accompanies the Windows ZIP. You may modify
or replace it under its own license. To rebuild MousePilot with a modified copy:

1. Obtain the MousePilot source matching the executable's version and install uv.
2. Extract and modify the accompanying pystray source archive as desired.
3. On Windows, run the following from the MousePilot source directory:

```powershell
uv sync --locked --extra build
uv pip install --reinstall C:\path\to\modified\pystray
uv run --no-sync python -m PyInstaller --clean --noconfirm --onefile --name mousepilot-server --hidden-import pystray._win32 --add-data "src/mousepilot/uia.ps1;mousepilot" scripts/server-entry.py
```

The resulting executable is in `dist/`. `--no-sync` preserves the modified
installation while rebuilding. When redistributing a modified dependency,
preserve its notices and fulfill that dependency's source/license requirements.

## Python and PyInstaller

The runtime retains Python's license and bundled component notices. PyInstaller
has its own licenses and a bootloader exception that permits distributing
bundled applications under their chosen licenses, subject to their dependencies.
See the [PyInstaller license](https://pyinstaller.org/en/stable/license.html).

## Documentation check tools

The source archive includes a documentation checker and its tests from the
Aixand documentation template. These files use Apache-2.0.
See the [source notice](third_party/docs-checks/NOTICE) and
[license text](third_party/docs-checks/LICENSE).
The Python wheel and native applications do not include these development tools.


## macOS app

The macOS build uses PyObjC's Cocoa, Quartz, ApplicationServices, and
ScreenCaptureKit bridges (MIT), with native AppKit menu controls instead of
pystray. `scripts/build-macos.sh` collects the installed license notices and
Python runtime license into the ZIP. Build separately on the intended Mac
architecture; no macOS system frameworks are redistributed by MousePilot.
