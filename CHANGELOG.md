# Changelog

## 0.1.1 — 2026-11-13

- Declare all four MCP tool annotation hints explicitly, including behavior-appropriate
  idempotency and complete control tool annotations.
- Add regression coverage for annotation completeness across all 24 tools.

## 0.1.0b0 — Unreleased

Initial public beta.

- Windows and macOS desktop control through MCP and the command line.
- Monitor selection, window discovery, window captures, image-coordinate mapping,
  crops, grids, and target previews.
- Windows accessible control discovery and revalidated native element clicks;
  visual click/type guidance when controls are unavailable.
- Mouse clicks, movement, scrolling, dragging, Unicode typing, and keyboard shortcuts.
- Windows focus activation with frame-click and keyboard fallbacks.
- Authenticated loopback connections, SSH device profiles, exclusive leases,
  explicit takeover/reset, and emergency stop controls.
- Local HTTP MCP support for image-capable browser clients, including llama.cpp WebUI.
- Windows executable and macOS app packaging, dependency notices, and checksums.
- CI checks and tag-gated beta builds from main.
- Standard development commands, package manifests, documentation checks, and a local private-file hook.
- Maintainer-led contribution and support guides without DCO checks or secret scanning.

Beta limitations: accessibility coverage varies by app. Mac control discovery is
not implemented. Broader clean-machine installation, mixed-DPI and lifecycle
coverage is still needed. macOS builds are not Developer ID signed or notarized.
