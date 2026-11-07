# Preparing a public release

## Repository settings

Before publishing the repository, review the staged files and archives. Never
include private device profiles, tokens, machine IDs, personal captures, local
MCP config, test output, or generated binaries in source history. `.gitignore`
helps prevent accidents but does not remove a secret already committed.

After creating the GitHub repository:

- Enable private vulnerability reporting under Security and verify the route in SECURITY.md.
- Provide a reachable private conduct/contact channel on the maintainer's profile.
- Protect the default branch, require CI, and review Dependabot updates.
- Add the real repository URL to package metadata if desired.

## Candidate checks

1. Keep the version in `pyproject.toml` and `src/mousepilot/protocol.py` aligned.
2. Update CHANGELOG.md with the changes and known limits.
3. Run the standard `check`, `test`, and `package` commands in the [development guide](development.md). Run the dependency audit.
4. Run `uv run python scripts/check-public-files.py` against staged files.
5. Inspect wheel and source-distribution contents for private/generated data.
6. Build the Windows ZIP with `scripts/build-windows.ps1` on a Windows runner.
7. Review notices, inventory, source archives, checksums, and dependency licenses.
8. Test the executable on a clean Windows machine and run appropriate native tests.
9. Preserve limitations in release notes; do not claim untested lifecycle/DPI support.

## Tagged build automation

Tests, quality checks, and dependency audits run for pull requests targeting
`main`, pushes to `main`, and version-tag pushes. Release packages are built
**only** for a pushed `vMAJOR.MINOR.PATCH` or `vMAJOR.MINOR.PATCHbN` tag whose commit is in `main`'s history.
The tag must match both `pyproject.toml` and the backend's `VERSION` constant.
A tag on an unmerged feature branch is rejected. Ordinary branch pushes, pull
requests, and manual CI runs do not build release packages.

After committing the version and changelog on `main` and completing review:

```sh
git switch main
git pull --ff-only
git push origin main
git tag -a v0.1.0b0 -m "MousePilot v0.1.0b0"
git push origin v0.1.0b0
```

The initial beta uses package version `0.1.0b0` and Git tag `v0.1.0b0`.
Use the actual next release version. Both pushes can also be sent together with
`git push origin main v0.1.0b0`. Branch and tag filters are separate GitHub events;
the release gate explicitly checks main-branch ancestry rather than assuming a
tag filter also enforces a branch condition.

After all checks pass, download the Python wheel/source archive and the Windows
ZIP (executable, dependency notices/source, and checksums) from the tag workflow's
Actions artifacts. Each host also supplies `release-manifest.json` and `SHA256SUMS`.
Use the standard `verify --artifact PATH` command with the adjacent manifest.
The manifest checks file identity and hashes. It is not a signature.
Keep each host's files in a separate directory. They are retained for 14 days. The workflow does not create a
GitHub Release or publish to PyPI; publication remains manual.

Signing and external distribution are separate release decisions. No signing key
is stored in this repository. Protect version tags with repository rules so only
release maintainers can create or change them.

The pystray dependency is LGPLv3; distribute its collected source/notices with
the Windows ZIP and keep the rebuild instructions in THIRD_PARTY_NOTICES.md.
The MIT license applies to MousePilot, not to third-party dependencies.

## macOS package

The tag workflow also builds a native app ZIP on `macos-latest`. Run
`scripts/build-macos.sh` on a Mac to reproduce it. ZIPs include MousePilot.app,
Python/dependency notices, and checksums. PyObjC is separately licensed; pystray
is not used by the macOS menu. Hosted builds target their runner architecture;
build on each architecture before advertising Intel and Apple Silicon binaries.
Ad-hoc signing verifies resource integrity locally but is not notarization or a
Developer ID identity. Test privacy prompts and clean-machine installation before
publishing the app to general users.
