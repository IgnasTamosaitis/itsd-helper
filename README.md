# ITSD Jira Helper

A Windows desktop tool for ITSD that connects to Jira and centralises everything needed to handle **new joiners** — from tracking start dates and completing the onboarding checklist, to setting up Active Directory accounts, posting Jira comments, and checking assigned Snipe-IT assets.

The app runs silently in the system tray and sends you Windows notifications so nothing gets missed.

> **Current release: v1.5.2**<br>
> [Download the Windows installer](https://github.com/IgnasTamosaitis/Jira-onboarding-helper/releases/download/v1.5.2/Jira-Reminders-1.5.2.msi)
> · [View the release](https://github.com/IgnasTamosaitis/Jira-onboarding-helper/releases/tag/v1.5.2)
> · [Open the team setup KB](docs/Jira-Reminders-KB.md)

---

## What the app does

### Ticket overview
The main window has separate **New joiners** and **Movers** tabs for upcoming
onboarding and employee-position-change tickets.

The joiner list shows the person's name, their start date, how many checklist tasks have been completed, and whether their AD account has been set up. Tickets are colour-coded by urgency:

- **Red** — starts today or tomorrow
- **Green** — starts within the next 7 days
- **Grey** — already started

### Employee movers

The Movers tab reads assigned Jira issues of type **Employee moving**. It shows
the effective date, current and new title, new company and manager, AD buddy,
and any separate Axapta-rights template.

The dedicated **Prepare AD move** workflow:

- resolves the mover, buddy, and Jira manager as separate enabled AD accounts;
- pauses for an explicit username selection when any lookup finds multiple
  enabled accounts, showing each account's title and OU for comparison;
- uses Buddy as the AD template, falling back to Axapta rights only when Buddy
  is empty;
- shows an Axapta follow-up warning when Buddy and Axapta rights differ;
- previews the exact group additions/removals, OU move, and attribute changes;
- makes Title and Description match the Jira new title;
- copies Department and OU from the buddy;
- sets Company and Manager from Jira and derives the address from the existing
  company/location map;
- verifies the final OU, direct groups, manager, organisation fields, and
  address before recording the move as complete.

Approval-only and redundant buddy groups remain blocked. A manager mismatch,
disabled account, unknown address, or AD change after preview blocks execution
until it is reviewed. Ambiguous enabled accounts require an explicit selection.
The workflow does not reset passwords, change email addresses, or perform
Axapta work.
Jira ticket status changes remain manual.

Permission-controlled memberships found in the audit history—including
`Disable_USB`, `VPN_IT_integracijos`, and `GrayList_WillGrow Users`—are displayed
as manual follow-up and are not copied automatically. If another group operation
is denied, the workflow continues with the remaining changes, verifies what was
applied, and reports the unresolved group without marking the AD move complete.

### Detail panel
Clicking a person opens their full detail view on the right side, showing:

- **Name and joiner type** — a clear badge indicates whether this is a **New Joiner** or a **Rejoiner**
- **Start date**, position, office, manager, and ticket status
- **AD setup summary** — if AD has been completed, a green box shows when it was done, which account was used, the result, and the target folder
- **Suggested buddy** — automatically detected from Jira comments (see below)
- **Onboarding checklist** — five tasks to tick off as you complete them
- **Notes** — a free-text field per person, auto-saved as you type
- **Jira comments** — all comments from the ticket, loaded automatically

## Automations

### Suggested buddy detection
The app reads ticket comments and automatically identifies who the reporter suggested as the template user. It recognises a wide range of phrasings, for example:

- *"please use NSURN as similar accesses"*
- *"needs the person Name Surname"*
- *"it will be Name Surname"*
- *"need rights as Name Surname"*
- *"Person who is working in the similar job role – Name Surname"*
- *"copy rights from..."*, *"same access as..."*, *"based on..."*, and more

When a full name is found, the app searches AD and resolves it to a SAM account automatically. The detected buddy is shown in a **blue info box**. When you open AD Setup, the buddy field is pre-filled and the lookup runs automatically.

If no buddy is found in the comments, an **orange hint** appears instead with a text field where you can type the buddy's SAM account manually. Manual buddy entries are **saved and restored** between sessions — they will not be overridden by comment scanning.

### Ask reporter
If the reporter has not mentioned a buddy or specified the required access, you can send them a pre-written comment directly from the app without opening Jira. Once posted, the app fetches updated comments — if the reporter replies with a name, the buddy box updates automatically.

### Windows notifications
The app sends desktop notifications in two situations:

**Per-joiner reminders** — when a person's start date is within the configured number of days (default: 3), you receive a notification showing how many checklist tasks are still pending. Each person triggers at most one notification per day.

**Morning summary** — every day at 9:00 AM, if there are any joiners starting within the next 7 days, you receive a single summary notification listing all of them.

---

## Active Directory setup wizard

The **AD Setup** button opens a step-by-step wizard for configuring the new joiner's AD account.

### Scenario detection
The wizard searches AD by first and last name and automatically detects one of three scenarios:

| Scenario | What it means | What the script does |
|---|---|---|
| **New joiner** | One SF-provisioned account in the SF OU | Moves to correct OU, sets email and location fields, adds groups, resets password |
| **Rejoiner (dual)** | SF dummy + old disabled account | Reads all employment data from SF dummy, restores old account, deletes dummy |
| **Rejoiner (single)** | One disabled account, no SF dummy | Re-enables old account, sets all attributes from Jira ticket and buddy |

> **Note:** For rejoiner (single), a yellow warning banner is shown reminding you to verify the Jira ticket data — position, company, and manager — before applying, since no SF dummy exists to pull from.

### What the script sets automatically

**New joiner** — SF already provisions Title, Description, Department, Company, Office, Manager, EmployeeID, extensionAttribute5, and extensionAttribute15. The script only fills what SF leaves blank:
- Email address and proxyAddresses
- `targetAddress` (set to match primary email)
- City, PostalCode, Country (from company address map)
- `extensionAttribute10` (manager's email, read from the SF account's Manager DN)
- `extensionAttribute14` (copied from buddy)
- Password reset

**Rejoiner (dual)** — reads Title, Description, Department, Company, Manager, and extensionAttribute5 directly from the SF dummy account (authoritative HR data). Also sets:
- All location fields from address map
- Email, proxyAddresses, targetAddress
- `extensionAttribute10` (manager email from SF dummy's Manager DN)
- `extensionAttribute14` (from buddy)
- `extensionAttribute15` (auto-set from company)
- Enables account, clears `msExchHideFromAddressLists`, moves OU, adds groups, resets password, deletes SF dummy

**Rejoiner (single)** — same as dual but sources employment data from the Jira ticket and buddy instead of an SF dummy.

### Password handling
The wizard uses the standard onboarding password and masks it by default; click **Show** to reveal it. Clicking **Copy** copies the password to the clipboard and **automatically clears it after 30 seconds**. The same auto-clear applies to the generated PowerShell script copy. The SMS handoff template contains the username only.

### Location detection and address map
The employee's Jira **Office Location** is the primary location signal. The
company is used as a fallback. Matching ignores capitalization, punctuation,
legal suffix formatting, and Lithuanian/Polish diacritics.

| Jira location | AD location handling |
|---|---|
| **Girteka Park / Vilnius** | Laisvės pr. 36, Vilnius, LT; Office `Vilnius`; extensionAttribute15 `SF` |
| **Siauliai Campus / Šiauliai** | Pročiūnų g. 16, LT-77103 Šiauliai; Office `Siauliai Campus`; extensionAttribute15 `SF` |
| **Tbilisi / GBS** | Full Chavchavadze Avenue 37L campus address, 0162 Tbilisi, GE; Office `Tbilisi`; extensionAttribute15 `SF` |
| **Poznańska 4, Sady / Girpoltrans** | Poznańska 4, Sady, PL; Office `Poznan` |
| **Other recognised Polish companies** | Applies Poland defaults and the Jira office, but preserves authoritative SuccessFactors street/city/postal data until that company's campus address is confirmed |

Recognised Šiauliai companies include Mireli, Trasis, Girmeta, Termolita,
Girtrans, KLP Transport, Premium Trans, and TermoTrans. Recognised Polish
companies include Girpoltrans, TransEu Poland, Eupoltrans, Scanpoltrans,
Polservice, GoTrans, ME Trailers Poland, and ClassTrucks Poland. Vilnius legal
entities include Trucks Merchant, Willgrow, GCC, TNDM Trucking, Girteka Nordic,
Girteka Transport, Girteka, Girteka Group, Girteka Logistics, ME Trailers, and
Girteka Cargo.

If the recognised Office Location and company point to different sites, the AD
wizard displays a warning and uses Office Location for the proposed changes.

### Template user (buddy)
Clicking **Use as template** fetches the buddy's OU, groups, Department, and extended attributes (`extensionAttribute5`, `extensionAttribute14`). Each extended attribute is shown with a **checkbox** so you can decide per-attribute whether to copy it. `extensionAttribute5` is only shown for **rejoiner (single)** — for new joiners and rejoiner (dual) it is already set correctly by SF or the SF dummy.

### Stale group cleanup
For rejoiner scenarios, after fetching the buddy, a **Stale groups** panel appears showing groups the old account has that the buddy does not. These are pre-unticked — you select which ones to remove and click **Remove selected from old account**. The app asks for confirmation before making any changes.

### Input validation
Before generating or running any script, the wizard validates:
- **Email address** — must match a valid format (`name@domain.tld`)
- **Target OU** — must begin with a valid Distinguished Name component (`OU=`, `CN=`, or `DC=`)

If either check fails, a clear error message is shown before any changes are attempted.

### Post-run verification
After the script runs, the app automatically fetches the account from AD and appends a full attribute summary to the output — Enabled, Title, Description, Department, Company, Office, EmailAddress, Manager, all extensionAttributes, targetAddress, and proxyAddresses — so you can confirm everything is correct without opening ADUC.

### Audit log
Every time the wizard applies changes, a timestamped record is appended to:

```
C:\Users\<your username>\.jira-reminders\ad_audit.log
```

Each entry records the ticket key, person's name, scenario, account, email, target OU, run status, and the full PowerShell output. The log is append-only and never overwritten automatically.

### proxyAddresses handling
- Primary `SMTP:Name.Surname@girteka.eu` is set or confirmed
- If a `SMTP:Name.Surname@girteka.lt` entry exists with uppercase prefix, it is automatically converted to lowercase `smtp:` (secondary) so the `.eu` address remains the sole primary

---

## Security

Credentials and sensitive data are handled carefully throughout the app.

**API token storage** — your Jira API token is stored in **Windows Credential Manager**, not in the config file. It is never written to disk in plaintext. Existing installations are migrated automatically on first launch.

**File permissions** — `config.json` and `tasks.json` are restricted to your Windows user account only (`icacls /inheritance:r`) the first time each file is written.

**Password security** — the standard onboarding password is masked by default and sensitive clipboard contents are cleared automatically after 30 seconds.

**PowerShell execution** — generated scripts run with `-ExecutionPolicy RemoteSigned` rather than `Bypass`, respecting the domain's signing policy for any downloaded modules.

**Input validation** — email addresses and OU paths are validated before any PowerShell is generated or executed.

---

## Requirements

- Windows 10 or 11
- Network access to your Jira instance
- The machine must be joined to the domain (required for AD Setup features)
- A Jira API token — generate one at **id.atlassian.com → Security → API tokens**
- A Snipe-IT API token if you want assigned-asset visibility in the joiner detail panel

Python and all other application dependencies are included in the Windows
installer. Colleagues do not need to install Python, clone the repository, or
run any scripts.

---

## Installation

1. Download [**`Jira-Reminders-1.5.2.msi`**](https://github.com/IgnasTamosaitis/Jira-onboarding-helper/releases/download/v1.5.2/Jira-Reminders-1.5.2.msi)
2. Double-click the MSI and complete the short Windows Installer flow
3. Jira Reminders opens automatically at the first-time setup screen

The MSI installs for the current Windows user, so administrator rights are not
normally required. It creates:

- a Desktop shortcut
- a Start menu shortcut
- a Windows Startup shortcut, so the app launches whenever that user signs in

The current installer is not Authenticode-signed, so Windows may display
**Unknown publisher**. Only continue when the file was downloaded from the
official release link above. If company policy blocks the installation, contact
the application owner instead of bypassing the policy.

For colleague-facing instructions, troubleshooting, supported locations, and
security guidance, use the complete [Jira Reminders team KB](docs/Jira-Reminders-KB.md).
A [Word version](docs/Jira-Reminders-KB.docx) is also included for direct import
into Confluence.

---

## First-time configuration

When the app starts for the first time, a welcome screen opens automatically.
The normal setup asks for:

| Field | What to enter |
|---|---|
| Atlassian email | Your Girteka Atlassian account email; the app tries to pre-fill it from Windows |
| Jira API token | A classic/unscoped token from the linked Atlassian token page |
| Snipe-IT API token | Optional; required only for assigned-asset visibility |
| Notification timing | How many days before a start date reminders begin |

Click **Test Jira connection** to verify the email and Jira token, then click
**Save & start**.

The Girteka Jira URL, Snipe-IT URL, start-date Jira field, polling interval, and
assigned-ticket JQL are pre-filled. They are available under **Advanced
settings** if troubleshooting is required. The default Jira query remains:

```text
assignee = currentUser() AND issuetype = "SF: Employee onboarding" AND status in (Open, "In Progress", Pending)
```

Your Jira API token and Snipe-IT API token are saved to **Windows Credential Manager** — they will not appear in any file on disk.

Settings can be changed at any time via the tray icon → **Settings**.

To remove the app, use the tray icon → **Uninstall**, or Windows Settings →
**Apps → Installed apps → Jira Reminders**. Personal settings and checklist
history are retained to support reinstallation.

### Source setup for developers

`setup.bat` and `start_reminders.vbs` remain available for source development
and troubleshooting. They are no longer part of the colleague installation
process.

---

## Daily use

The app runs in the **system tray** (bottom-right corner of your taskbar). Right-click the tray icon to access:

- **Show tickets** — opens the main window
- **Check now** — immediately polls Jira for updates
- **Settings** — change credentials or configuration
- **Quit** — close the app

### Main window buttons

| Button | What it does |
|---|---|
| **Refresh** | Manually re-fetches all tickets from Jira |
| **AD Setup** | Opens the AD setup wizard for the selected person |
| **Ask reporter** | Posts a comment to the Jira ticket asking for buddy and access info |
| **Back up data** | Saves a timestamped backup of all notes and checklist progress |
| **Open in Jira** | Opens the selected ticket in your browser |

### Data storage

All notes, checklist progress, AD setup records, and manual buddy entries are stored locally on your machine at:

```
C:\Users\<your username>\.jira-reminders\
```

| File | Contents |
|---|---|
| `config.json` | App settings (Jira URL, email, JQL — **not** the API token) |
| `tasks.json` | Checklist state, notes, buddy assignments, AD setup records |
| `ad_audit.log` | Append-only log of every AD setup run |
| `backups\` | Timestamped backups created by **Back up data** |

Your Jira API token and Snipe-IT token are stored separately in **Windows Credential Manager** under the name `jira-reminders`.

Use **Back up data** regularly to keep snapshots. Backups are saved in the `backups` subfolder with a timestamp in the filename.

---

## Troubleshooting

**No tickets appear** — click *Check now* from the tray icon and wait a few seconds. If the problem persists, open Settings and use *Test Connection* to check your credentials.

**Buddy not detected** — scroll down to the Jira comments section in the detail panel. If the phrasing is unusual, type the SAM account directly in the manual buddy field in the orange hint box.

**AD Setup returns errors** — ensure you are logged into a machine joined to the domain and that you enter valid domain admin credentials when prompted. The most common cause is expired credentials or not being connected to the corporate network / VPN.

**API token missing after update** — if you upgraded from a version that stored the token in `config.json`, the token is migrated to Windows Credential Manager automatically on first launch. If the connection fails after upgrading, open Settings, re-enter the token, and save.

**Debug tool** — if you need to diagnose Jira connection or query issues, run `debug.py` from a terminal. It will test the connection and print a list of all matching tickets with their raw field values.
