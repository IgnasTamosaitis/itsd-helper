# ITSD Jira Helper

A Windows desktop tool for ITSD that connects to Jira and centralises everything needed to onboard a new employee — from tracking start dates and completing the onboarding checklist, to setting up their Active Directory account and coordinating with the ticket reporter.

The app runs silently in the system tray and sends you Windows notifications so nothing gets missed.

---

## What the app does

### Ticket overview
The app monitors your Jira queue for onboarding tickets and displays all upcoming joiners in a single list. Each entry shows the person's name, their start date, how many checklist tasks have been completed, and whether their AD account has been set up. Tickets are colour-coded by urgency:

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

### Post-run verification
After the script runs, the app automatically fetches the account from AD and appends a full attribute summary to the output — Enabled, Title, Description, Department, Company, Office, EmailAddress, Manager, all extensionAttributes, targetAddress, and proxyAddresses — so you can confirm everything is correct without opening ADUC.

### proxyAddresses handling
- Primary `SMTP:Name.Surname@girteka.eu` is set or confirmed
- If a `SMTP:Name.Surname@girteka.lt` entry exists with uppercase prefix, it is automatically converted to lowercase `smtp:` (secondary) so the `.eu` address remains the sole primary

---

## Requirements

- Windows 10 or 11
- Python 3.11 or later — download from [python.org](https://www.python.org)
- Network access to your Jira instance
- The machine must be joined to the domain (required for AD Setup features)
- A Jira API token — generate one at **id.atlassian.com → Security → API tokens**

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
| JQL Query | The filter that returns your onboarding tickets (pre-filled with the correct query) |
| Start date field | Leave as default unless your Jira schema has changed |
| Remind N days before | How many days ahead to start sending notifications (default: 3) |
| Check every N minutes | How often the app polls Jira in the background (default: 30) |

Click **Test Connection** to verify your credentials before saving.

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

### Data storage

All notes, checklist progress, AD setup records, and manual buddy entries are stored locally on your machine at:

```
C:\Users\<your username>\.jira-reminders\
```

Use **Back up data** regularly to keep snapshots. Backups are saved in the `backups` subfolder with a timestamp in the filename.

---

## Troubleshooting

**No tickets appear** — click *Check now* from the tray icon and wait a few seconds. If the problem persists, open Settings and use *Test Connection* to check your credentials.

**Buddy not detected** — scroll down to the Jira comments section in the detail panel. If the phrasing is unusual, type the SAM account directly in the manual buddy field in the orange hint box.

**AD Setup returns errors** — ensure you are logged into a machine joined to the domain and that you enter valid domain admin credentials when prompted. The most common cause is expired credentials or not being connected to the corporate network / VPN.

**Debug tool** — if you need to diagnose Jira connection or query issues, run `debug.py` from a terminal. It will test the connection and print a list of all matching tickets with their raw field values.
