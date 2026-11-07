# Develop MousePilot

Use the standard commands from the repository root.
Python 3.11 or newer is required.
Install uv before you prepare the development environment.
Git is required for repository checks.

## Standard commands

On Linux or macOS, run `./dev.sh COMMAND`.
On Windows, run `.\dev.ps1 COMMAND` in PowerShell.
Both wrappers use `scripts/dev.py`.
You can also run `python scripts/dev.py COMMAND` with Python 3.11 or newer.

| Command | Result |
| --- | --- |
| `help` | Show commands without installing tools. |
| `doctor` | Check local requirements without downloads or repairs. |
| `develop` | Prepare the local environment from `uv.lock`. |
| `check` | Check code format, lint, documentation, and staged files. |
| `test` | Run automated tests without desktop input. |
| `build --release` | Build the Python wheel and source archive. |
| `package` | Build packages, a manifest, and checksums in `dist/`. |
| `package --python-only` | Build only Python packages on any host. |
| `verify --artifact PATH` | Check an artifact against the adjacent package manifest. |

Run `doctor` first.
Run `develop` if the local environment is missing.
Run `check` and `test` before you prepare a PR.
These commands do not start a device backend or register a login task.
Use [testing](testing.md) for live desktop tests.

`package` also runs the current native package script on Windows or macOS.
Linux builds only the Python packages.
A local package operation does not publish a release.
The manifest and hashes detect changed files. They do not prove publisher identity.
Keep the manifest from a trusted source with the artifact.

`install`, `reinstall`, `uninstall`, and `publish` are recognized but unsupported.
They return a nonzero result with a guide link.
Use [configuration](configuration.md) for device setup.
Use [releasing](releasing.md) for publication steps.

## Documentation checks

Run this check after you change a guide:

```sh
python scripts/checks/check-docs.py --root .
```

Run the checker tests with this command:

```sh
python tests/tooling/checks/docs_test.py
```

The normal `test` command also runs these tests.
Use short sentences and active voice.
Keep technical names and commands exact.
Review command examples separately. The Markdown checker does not execute them.

## Local commit hook

Install the private-file check in each clone:

```sh
python scripts/install-hooks.py
```

The installer preserves an existing hook that it does not own.
If another hook manager is present, add `python scripts/check-public-files.py`
to that manager instead.
The hook checks Git's staged files. CI runs the same check.
