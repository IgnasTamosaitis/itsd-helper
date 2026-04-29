# Release Notes

---

## v1.1 — Hardened & Complete: New Joiner Onboarding

This release completes the New Joiner onboarding workflow and hardens the application for production use in a corporate environment. All known security gaps have been addressed and UI responsiveness has been significantly improved.

---

### Security

**Credential protection**
The Jira API token is no longer stored in `config.json`. It is now saved in **Windows Credential Manager** and never written to disk in plaintext. Existing installations migrate automatically on first launch — no manual steps required.

**File permissions**
`config.json` and `tasks.json` are now restricted to the current Windows user only using `icacls /inheritance:r` the first time each file is written.

**Password handling in AD Setup**
- The wizard now opens with a **freshly generated random password** — the old hardcoded placeholder `Initial123` has been removed.
- The password field is **masked by default**. A **Show / Hide** toggle reveals it when needed.
- Copying the password, the SMS template, or the generated PowerShell script now **automatically clears the clipboard after 30 seconds**, so sensitive content does not persist in clipboard history.

**PowerShell execution policy**
Generated scripts now run with `-ExecutionPolicy RemoteSigned` instead of `-ExecutionPolicy Bypass`, respecting the domain's module signing policy.

**Input validation**
The AD Setup wizard now validates the email address format and the target OU Distinguished Name before generating or running any script. Invalid input produces a clear error message rather than a broken PowerShell script.

**Audit log**
Every AD setup run is now recorded to `~/.jira-reminders/ad_audit.log` with a full timestamp, ticket details, account, email, target OU, run status, and complete PowerShell output. The log is append-only.

---

### Performance

**Instant ticket navigation**
Switching between tickets is now immediate. Two separate root causes had been blocking the UI thread on every ticket click:

1. Buddy resolution (which runs PowerShell to look up AD accounts) was executing synchronously on the main thread when comments were already cached. It now always runs in a background thread.
2. The new file-permission hardening (`icacls`) was running synchronously on every disk write, including every notes auto-save. It now runs in a background daemon thread and only once per file path.

---

### Dependencies

`keyring>=24.0` added — provides the Windows Credential Manager integration. Installed automatically by `setup.bat`.

---

## v1.0.1

- Improved launch flow and AD loading UX
- Buddy chooser now keeps older buddy mentions visible alongside the latest
- Always prefers the latest buddy comment for the primary suggestion
- Jira comments refresh in the background even when a cached copy is available
- Fixed buddy rescanning and Lithuanian name handling (ą, č, ę, ė, etc.)
- Support for multiple buddy candidates from Jira comments
- Disabled buddy detection and follow-up flow

## v1.0

Initial release. Full New Joiner and Rejoiner onboarding workflow:

- System tray app with Jira polling and Windows notifications
- Onboarding checklist, notes, and AD setup summary per ticket
- Buddy detection from Jira comments with AD resolution
- Ask reporter flow with ADF mention support
- AD Setup wizard: scenario detection (new joiner / rejoiner dual / rejoiner single), OU move, group assignment, email and attribute configuration, password reset, post-run verification, stale group cleanup
- Morning summary notifications
- Local JSON storage with backup support
