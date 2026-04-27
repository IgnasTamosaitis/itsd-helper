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
- **Suggested buddy** — automatically detected from the Jira comments (see below)
- **Onboarding checklist** — five tasks to tick off as you complete them
- **Notes** — a free-text field per person, auto-saved as you type
- **Jira comments** — all comments from the ticket, loaded automatically, so you never need to open Jira just to read what the reporter wrote

---

## Automations

### Suggested buddy detection
The app reads the ticket comments and automatically identifies who the reporter suggested as the template user (the person whose AD rights and groups the new joiner should copy). It recognises a wide range of natural phrasings, for example:

- *"please use TSELE as similar accesses"*
- *"needs Axapta rights and the person Maksim Sapoznikov"*
- *"it will be Božena Jurčik"*
- *"need rights as Eimantas Tarasevicius"*
- *"copy rights from..."*, *"same access as..."*, *"based on..."*, and more

The detected buddy is shown in a **blue info box** in the detail panel. When you open **AD Setup** for that person, the buddy field is pre-filled and the lookup runs automatically — you do not need to type anything.

If no buddy is found in the comments, an **orange hint** is shown instead, and the **Ask reporter** button becomes available.

### Ask reporter
If the reporter has not yet mentioned a buddy or specified the required access, you can send them a pre-written comment directly from the app without opening Jira. Clicking **Ask reporter** opens a preview of the message, which you can edit before sending. Once posted, the app immediately fetches the updated comments — if the reporter replies with a name, the buddy box updates on its own.

### Windows notifications
The app sends desktop notifications in two situations:

**Per-joiner reminders** — when a person's start date is within the configured number of days (default: 3), you receive a notification showing how many checklist tasks are still pending. Each person triggers at most one notification per day.

**Morning summary** — every day at 9:00 AM, if there are any joiners starting within the next 7 days, you receive a single summary notification listing all of them with their start dates and task progress.

---

## Active Directory setup wizard

The **AD Setup** button opens a step-by-step wizard for configuring the new joiner's AD account. The wizard covers:

1. **Joiner details** — name, position, company, office, manager, phone, and start date pulled directly from Jira
2. **Account search** — searches Active Directory by first and last name and automatically detects which scenario applies:
   - **New joiner** — one account was provisioned by SAP SuccessFactors (SF), ready to be moved and configured
   - **Rejoiner (dual account)** — an SF dummy account exists alongside an old disabled account; the old account is restored and the dummy is removed
   - **Rejoiner (single account)** — one disabled account with no SF duplicate; it is re-enabled and reconfigured
3. **Account selection** — pre-filled automatically; if multiple old accounts are found you can choose which one to restore
4. **Email address** — pre-generated from the person's name and company domain
5. **Template user (buddy)** — pre-filled from the detected buddy in comments; clicking *Use as template* fetches the buddy's OU and group memberships so you can copy them across
6. **Groups** — default groups for the person's location (Lithuania, Poland, or Georgia) are pre-selected; buddy groups can be added and individual groups toggled on or off
7. **Password** — default initial password with an option to generate a random one; an SMS template is shown ready to copy and send to the new joiner's phone
8. **Review and apply** — a full PowerShell script is generated based on all the above; you can review it before running, and copy either the script or the result output

AD credentials are requested at execution time and are never stored by the app.

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

All notes, checklist progress, and AD setup records are stored locally on your machine at:

```
C:\Users\<your username>\.jira-reminders\
```

Use **Back up data** regularly to keep snapshots. Backups are saved in the `backups` subfolder with a timestamp in the filename.

---

## Troubleshooting

**No tickets appear** — click *Check now* from the tray icon and wait a few seconds. If the problem persists, open Settings and use *Test Connection* to check your credentials.

**Buddy not detected** — scroll down to the Jira comments section in the detail panel and read what the reporter wrote. If the phrasing is unusual, use *Ask reporter* to post a comment requesting the information in a standard format.

**AD Setup returns errors** — ensure you are logged into a machine joined to the domain and that you enter valid domain admin credentials when prompted.

**Debug tool** — if you need to diagnose Jira connection or query issues, run `debug.py` from a terminal. It will test the connection and print a list of all matching tickets with their raw field values.
