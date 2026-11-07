# Security policy

## Reporting a vulnerability

Use this GitHub repository's **Security → Advisories → Report a vulnerability**
flow for private reports. If that option is unavailable, open an issue titled
"Private security contact requested" containing only a request for a private
channel. Do not include exploit details or sensitive data in that issue.

A useful private report includes the affected version/commit, OS version,
configuration with credentials removed, impact, and minimal reproduction steps.
Use a test device and synthetic data. Do not send real tokens or screenshots of
private applications. Coordinated disclosure is appreciated; there is no paid
bounty or guaranteed response SLA.

## Supported versions

Security fixes target the latest version on the default branch and the latest
published release. There is no commitment to backport fixes to older beta builds.
MousePilot is in beta. It has not had an independent security audit.

## Authorized and policy-compliant use

Users are responsible for obtaining authorization and complying with applicable
laws, software licenses, service terms, platform policies, and automation
restrictions. MousePilot's technical capabilities do not grant permission to
access or automate third-party devices, accounts, applications, or services.
The project does not endorse misuse or promise that any particular automation
is permitted by the affected service. See the [responsible-use notice](docs/responsible-use.md)
and the warranty/liability provisions in the [MIT license](LICENSE).

## Trust boundaries

- The backend runs in the interactive desktop user's session and privileges.
  A valid token grants screenshots, window metadata, mouse/keyboard input, and
  pause/resume and explicit reset/takeover. A token holder can revoke another
  controller; reset pauses input and invalidates old observations. There are no read-only tokens or per-application permissions.
- The backend binds to loopback. Remote access is supported through SSH with
  normal host-key verification; direct public/LAN exposure is unsupported.
- Named profiles pin a device identity. That identity is not a substitute for
  keeping the token secret or verifying the SSH host.
- Any local process that can read the token can control the desktop. Store it
  in a user-restricted directory; Windows file ACLs must protect it. Git ignore
  rules do not provide access control.
- A single control lease prevents competing controllers, but does not isolate
  input from the physical user. A connection drop does not undo input already
  injected. Bounded operations may finish and must not be blindly repeated.
- A screenshot or window ID is a short-lived observation. The UI may move, titles
  may change, Windows may recycle handles, and another user/app can take focus.
  Do not treat a successful input call as proof of an application outcome.
- This is not a sandbox for an untrusted agent. Screen content can contain prompt
  injection; the MCP client/agent must decide what actions it is authorized to
  perform. MousePilot does not understand or enforce task-level intent.

## Data handling and emergency control

The backend has no telemetry. Request audit logs contain operation names, status,
error codes, and timestamps, not tokens, session IDs, typed text, or screenshots.
Startup diagnostics can contain local paths. Screenshots/window titles are
returned to the client, which may retain them in its own logs or conversation.
Manual captures and verification reports are written to local files.

Ctrl+Alt+Shift+F11 and the tray menu pause input and attempt to release tracked
keys/buttons. Resume must be explicit. A forced process termination cannot
guarantee cleanup. Elevated applications, secure desktops, and locked sessions
can restrict input; MousePilot does not bypass those restrictions.

Windows executables do not have a publisher signature. Mac apps use ad-hoc
signatures. They are not notarized. Tests and dependency audits do not prove
that the software has no vulnerabilities. Review the source and dependencies
before you use it on a sensitive desktop.

On macOS, keep the Application Support directory private. Enable privacy permissions
only for the intended MousePilot app. The backend never edits the privacy database.
