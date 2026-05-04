# ITSD Jira Helper

A Windows desktop tool for ITSD that connects to Jira and centralises everything needed to handle both **new joiners** and **leavers** — from tracking start dates and completing the onboarding checklist, to setting up Active Directory accounts, triggering Jira automations, posting Jira comments, looking up Snipe-IT assets, and generating the printed leaver return act.

The app runs silently in the system tray and sends you Windows notifications so nothing gets missed.

---

## What the app does

### Ticket overview
The main window now has two tabs:

- **New Joiners** — onboarding tickets and AD workflow
- **Leavers** — offboarding tickets, Snipe-IT lookups, Jira automation actions, document generation, and Jira comments

The joiner list shows the person's name, their start date, how many checklist tasks have been completed, and whether their AD account has been set up. Tickets are colour-coded by urgency:

- **Red** — starts today or tomorrow
- **Green** — starts within the next 7 days
- **Grey** — already started

### Detail panel
Clicking a person opens their full detail view on the right side, showing:

- **Name and joiner type** — a clear badge indicates whether this is a **New Joiner** or a **Rejoiner**
- **Start date**, position, office, manager, and ticket status
- **AD setup summary** — if AD has been completed, a green box shows when it was done, which account was used, the result, and the target folder
- **Suggested buddy** — automatically detected from Jira comments (see below)
- **Onboarding checklist** — five tasks to tick off as you complete them
- **Notes** — a free-text field per person, auto-saved as you type
- **Jira comments** — all comments from the ticket, loaded automatically

### Leavers workspace
The **Leavers** tab adds a dedicated offboarding workflow. Selecting a leaver opens a detail view with:

- **Name, last working date, status, and company metadata**
- **Snipe-IT laptop card** — automatically looks up the leaver in Snipe-IT and shows the detected laptop model and serial number
- **Leaver notes** — separate auto-saved notes for offboarding
- **Reusable Jira comment box** — write any comment manually or post a prepared buyout template
- **Jira comments** — full ticket comment history, refreshed automatically

### Leaver actions
The leaver view includes dedicated actions for the full offboarding flow:

- **Add accountants** — triggers the Jira manual automation rule `Add accountants for deduction | LT Group 1`
- **Post buyout template** — posts a predefined Jira comment asking accountants to calculate the laptop residual value
- **Generate return act** — creates a filled `.docx` copy of the printed return form using Jira data, the current Jira assignee, and whatever equipment is available from Snipe-IT

The buyout comment can be posted **whenever needed** — it is no longer tied to the accountants automation button.

---

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
The wizard generates a **random password** automatically when it opens — you never see a hardcoded placeholder. The password field is **masked by default**; click **Show** to reveal it. Clicking **Copy** copies the password to the clipboard and **automatically clears it after 30 seconds**, so it is never left sitting in clipboard history. The same auto-clear applies to the SMS template copy and the generated PowerShell script copy.

### Company address map
For Girteka group companies (GCC, TNDM, Girteka*, ME Trailers, ClassTrucks Lithuania), the following are set automatically:

| Field | Value |
|---|---|
| Street | Laisvės pr. 36 |
| City | Vilnius |
| PostalCode | 5623 |
| Country | LT |
| Office | Vilnius |
| extensionAttribute15 | SF |

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

**Password security** — the AD Setup wizard always generates a fresh random password. The field is masked by default and clipboard contents are cleared automatically after 30 seconds.

**PowerShell execution** — generated scripts run with `-ExecutionPolicy RemoteSigned` rather than `Bypass`, respecting the domain's signing policy for any downloaded modules.

**Input validation** — email addresses and OU paths are validated before any PowerShell is generated or executed.

---

## Requirements

- Windows 10 or 11
- Python 3.11 or later — download from [python.org](https://www.python.org)
- Network access to your Jira instance
- The machine must be joined to the domain (required for AD Setup features)
- A Jira API token — generate one at **id.atlassian.com → Security → API tokens**
- A Snipe-IT API token if you want laptop lookup, buyout comment autofill, and return-act generation

---

## Installation

1. Download or copy the app folder to your machine
2. Double-click **`setup.bat`**

The setup script installs all required dependencies and adds the app to your Windows Startup folder so it launches automatically every time you log in.

To start the app immediately without rebooting, double-click **`start_reminders.vbs`**.

---

## First-time configuration

When the app starts for the first time, a settings window opens automatically. Fill in:

| Field | What to enter |
|---|---|
| Jira URL | `https://yourcompany.atlassian.net` |
| Email | Your Atlassian account email |
| API Token | The token generated from id.atlassian.com |
| Joiners JQL | The filter that returns your onboarding tickets (pre-filled with the correct query) |
| Leavers JQL | The filter that returns your leaver tickets |
| Start date field | Leave as default unless your Jira schema has changed |
| Snipe-IT URL | Your Snipe-IT base URL, for example `https://inventory.girteka.eu` |
| Snipe-IT API Token | Personal access token used for asset lookups |
| Remind N days before | How many days ahead to start sending notifications (default: 3) |
| Check every N minutes | How often the app polls Jira in the background (default: 30) |

Click **Test Connection** to verify your credentials before saving.

Your Jira API token and Snipe-IT API token are saved to **Windows Credential Manager** — they will not appear in any file on disk.

Settings can be changed at any time via the tray icon → **Settings**.

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
| **Add accountants** | Triggers the Jira manual automation used for leaver buyout flow |
| **Post buyout template** | Posts the predefined accountants comment with laptop details |
| **Generate return act** | Builds and opens the filled leaver return document |

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
| `generated_docs\` | Generated leaver return documents |

Your Jira API token and Snipe-IT token are stored separately in **Windows Credential Manager** under the name `jira-reminders`.

Use **Back up data** regularly to keep snapshots. Backups are saved in the `backups` subfolder with a timestamp in the filename.

---

## Troubleshooting

**No tickets appear** — click *Check now* from the tray icon and wait a few seconds. If the problem persists, open Settings and use *Test Connection* to check your credentials.

**Buddy not detected** — scroll down to the Jira comments section in the detail panel. If the phrasing is unusual, type the SAM account directly in the manual buddy field in the orange hint box.

**AD Setup returns errors** — ensure you are logged into a machine joined to the domain and that you enter valid domain admin credentials when prompted. The most common cause is expired credentials or not being connected to the corporate network / VPN.

**API token missing after update** — if you upgraded from a version that stored the token in `config.json`, the token is migrated to Windows Credential Manager automatically on first launch. If the connection fails after upgrading, open Settings, re-enter the token, and save.

**Return act has an empty equipment table** — the document generator only fills equipment rows that Snipe-IT reports as assigned to that user. If the document opens with a warning and no assets listed, check the employee's assigned assets directly in Snipe-IT.

**Debug tool** — if you need to diagnose Jira connection or query issues, run `debug.py` from a terminal. It will test the connection and print a list of all matching tickets with their raw field values.
