"""
AD automation helpers - Girteka new joiner / rejoiner onboarding.

Accounts are always auto-provisioned by SAP SuccessFactors into the SF OU.
We never create accounts from scratch; we move, enable, and configure them.

Scenarios detected by searching AD by first+last name:
  new_joiner      - one account, located in SF_OU  (just provisioned)
  rejoiner_dual   - two accounts: one in SF_OU (dummy) + one old disabled account
  rejoiner_single - one account, NOT in SF_OU, disabled  (edge case)
  unknown         - unexpected state, needs manual review
"""
import re
import secrets
import string
import subprocess

SF_OU_FRAGMENT = "Active_Users_from_SF"   # substring present in the SF provisioning OU

# ── Helpers ───────────────────────────────────────────────────────────────────

_TRANSLIT = str.maketrans("ąčęėįšųūžĄČĘĖĮŠŲŪŽ", "aceeisuuzACEEISUUZ")

def _ascii(name: str) -> str:
    return name.translate(_TRANSLIT)

def _e(s: str) -> str:
    """Escape single quotes for PowerShell single-quoted strings."""
    return str(s).replace("'", "''")


def _manager_lookup_lines(manager: str) -> list[str]:
    if not manager:
        return []
    return [
        "$mgrDn = $null",
        f"$mgrMatches = @(Get-ADUser -Filter {{DisplayName -eq '{manager}'}} -Properties DistinguishedName)",
        "if ($mgrMatches.Count -eq 1) {",
        "    $mgrDn = $mgrMatches[0].DistinguishedName",
        "} elseif ($mgrMatches.Count -eq 0) {",
        f"    Write-Warning 'Manager not found: {manager}'",
        "} else {",
        f"    Write-Warning 'Multiple managers found for: {manager}. Manager was not set.'",
        "}",
        "",
    ]


def _proxy_address_lines(sam: str, email: str) -> list[str]:
    return [
        "# Set primary SMTP proxy address",
        f"$smtpAddress = 'SMTP:{_e(email)}'",
        f"$currentProxies = (Get-ADUser -Identity '{sam}' -Properties proxyAddresses).proxyAddresses",
        "if (@($currentProxies) -notcontains $smtpAddress) {",
        f"    Set-ADUser -Identity '{sam}' -Add @{{proxyAddresses=$smtpAddress}}",
        '    Write-Host "OK  proxyAddresses set"',
        "} else {",
        '    Write-Host "OK  proxyAddresses already present"',
        "}",
        "",
    ]


def _set_user_attribute_lines(sam: str, email: str, title: str,
                              office: str, manager: str) -> list[str]:
    L = [
        "# Update organisation attributes",
        "$setParams = @{",
        f"    EmailAddress = '{_e(email)}'",
    ]
    if title:
        L.append(f"    Title = '{title}'")
    if office:
        L.append(f"    Office = '{office}'")
    L.append("}")
    if manager:
        L.append("if ($mgrDn) { $setParams['Manager'] = $mgrDn }")
    L += [
        f"Set-ADUser -Identity '{sam}' @setParams",
        'Write-Host "OK  Attributes updated"',
    ]
    return L

# ── Location / domain detection ───────────────────────────────────────────────

def detect_location(office: str, company: str = "") -> str:
    text = (office + " " + company).lower()
    if any(k in text for k in ["poland", "warszawa", "warsaw", "krakow", "wroclaw"]):
        return "poland"
    if any(k in text for k in ["georgia", "gbs", "tbilisi", "kutaisi"]):
        return "georgia"
    return "lithuania"

_DOMAIN_MAP = [
    ("everwest",    "everwest.net"),
    ("willgrow",    "willgrow.com"),
    ("sirin",       "sirin.eu"),
    ("tndm",        "tndmtrucking.com"),
    ("classtrucks", "classtrucks.com"),
    ("girteka",     "girteka.eu"),
]

def detect_domain(company: str) -> str:
    for keyword, domain in _DOMAIN_MAP:
        if keyword in company.lower():
            return domain
    return "girteka.eu"

def build_email(first: str, last: str, domain: str) -> str:
    f = _ascii(first).lower().strip()
    l = _ascii(last).lower().strip()
    if domain == "tndmtrucking.com":
        return f"{f[0].upper()}{l.capitalize()}@{domain}"
    return f"{f}.{l}@{domain}"

# ── Default AD groups ─────────────────────────────────────────────────────────

DEFAULT_GROUPS: dict[str, list[str]] = {
    "lithuania": ["AX30", "AX30_LT", "VPN Work From Home", "M365_E3", "MFA Users", "WFG All"],
    "poland":    ["AX30", "AX30_LT", "M365_E3", "MFA Users", "VPN Work From Home",
                  "WFG All", "PL Baze", "PrintSrv PL"],
    "georgia":   ["AX30", "AX30_LT", "M365_E3", "MFA Users", "VPN Work From Home",
                  "WFG All", "DL_GBS_office"],
}

# ── Password generation ───────────────────────────────────────────────────────

def generate_password(length: int = 14) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%"
    while True:
        pwd = "".join(secrets.choice(chars) for _ in range(length))
        if (any(c.isupper() for c in pwd) and any(c.islower() for c in pwd) and
                any(c.isdigit() for c in pwd) and any(c in "!@#$%" for c in pwd)):
            return pwd

# ── PowerShell runner ─────────────────────────────────────────────────────────

def run_ps(script: str, timeout: int = 90) -> tuple[str, str, int]:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )
    return r.stdout.strip(), r.stderr.strip(), r.returncode


def sam_exists(sam: str) -> bool:
    """Returns True if the SAM account exists in Active Directory."""
    _, _, code = run_ps(
        f"Import-Module ActiveDirectory -ErrorAction Stop; "
        f"Get-ADUser -Identity '{_e(sam)}' -ErrorAction Stop | Out-Null",
        timeout=10,
    )
    return code == 0

# ── AD queries ────────────────────────────────────────────────────────────────

def find_user_accounts(first: str, last: str) -> list[dict]:
    """
    Search AD by first+last name. Returns all matching accounts with metadata.
    Each dict has: username, enabled, title, dn, ou, is_sf, employee_id
    """
    out, err, code = run_ps(f"""
Import-Module ActiveDirectory -ErrorAction Stop
$users = Get-ADUser -Filter {{GivenName -eq '{_e(first)}' -and Surname -eq '{_e(last)}'}} `
    -Properties SamAccountName, Enabled, Title, DistinguishedName, EmployeeID
foreach ($u in $users) {{
    $emp = if ($u.EmployeeID) {{ $u.EmployeeID }} else {{ '' }}
    "$($u.SamAccountName)|$($u.Enabled)|$($u.Title)|$($u.DistinguishedName)|$emp"
}}
""")
    if code != 0 or not out:
        return []
    results = []
    for line in out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|", 4)
        if len(parts) < 4:
            continue
        dn = parts[3].strip()
        results.append({
            "username":    parts[0].strip(),
            "enabled":     parts[1].strip() == "True",
            "title":       parts[2].strip(),
            "dn":          dn,
            "ou":          re.sub(r"^CN=[^,]+,", "", dn),
            "is_sf":       SF_OU_FRAGMENT in dn,
            "employee_id": parts[4].strip() if len(parts) > 4 else "",
        })
    return results


def classify_scenario(accounts: list[dict]) -> str:
    """
    new_joiner      - single account in SF OU
    rejoiner_dual   - SF account + separate old account
    rejoiner_single - single disabled account NOT in SF OU
    unknown         - anything else
    """
    if not accounts:
        return "unknown"
    sf  = [a for a in accounts if a["is_sf"]]
    old = [a for a in accounts if not a["is_sf"]]
    if len(accounts) == 1 and sf:
        return "new_joiner"
    if sf and old:
        return "rejoiner_dual"
    if len(accounts) == 1 and not accounts[0]["enabled"]:
        return "rejoiner_single"
    return "unknown"


def get_buddy_info(sam: str) -> tuple[str, list[str], str]:
    """Returns (ou, [group_names], error). On success error is empty string."""
    out, err, code = run_ps(f"""
Import-Module ActiveDirectory -ErrorAction Stop
$u = Get-ADUser -Identity '{_e(sam)}' -Properties MemberOf, DistinguishedName -ErrorAction Stop
$ou = $u.DistinguishedName -replace '^CN=[^,]+,', ''
"OU:$ou"
foreach ($g in $u.MemberOf) {{ "GRP:$((Get-ADGroup $g).Name)" }}
""")
    if code != 0:
        return "", [], (err or "User not found")
    ou, groups = "", []
    for line in out.splitlines():
        if line.startswith("OU:"):
            ou = line[3:].strip()
        elif line.startswith("GRP:"):
            g = line[4:].strip()
            if "/O=" not in g:   # skip legacy Exchange distribution list entries
                groups.append(g)
    return ou, sorted(groups), ""

# ── Script builders ───────────────────────────────────────────────────────────

def build_new_joiner_script(ticket: dict, sf_account: dict, target_ou: str,
                             email: str, password: str, groups: list[str]) -> str:
    """
    New joiner: one SF-provisioned account.
    Steps: move to buddy OU -> add groups -> set proxyAddresses -> update org attributes.
    """
    username = _e(sf_account["username"])
    manager  = _e(ticket.get("manager", ""))
    title    = _e(ticket.get("position", ""))
    office   = _e(ticket.get("office", ""))

    L = [
        "$cred = Get-Credential -Message 'Enter your AD admin credentials'",
        "$PSDefaultParameterValues = @{'*-AD*:Credential' = $cred}",
        "",
        '$ErrorActionPreference = "Stop"',
        "Import-Module ActiveDirectory -ErrorAction Stop",
        f'Write-Host "Processing NEW JOINER: {sf_account["username"]}"',
        "",
    ]

    L += _manager_lookup_lines(manager)

    L += [
        "# Move account from SF OU to correct OU",
        f"$userDN = (Get-ADUser -Identity '{username}' -Properties DistinguishedName).DistinguishedName",
        f"Move-ADObject -Identity $userDN -TargetPath '{_e(target_ou)}'",
        'Write-Host "OK  Account moved to correct OU"',
        "",
        "# Add to AD groups (failures logged but non-fatal)",
    ]
    for g in groups:
        L.append(
            f"try {{ Add-ADGroupMember -Identity '{_e(g)}' -Members '{username}' }} "
            f"catch {{ Write-Warning \"Group '{_e(g)}': $_\" }}"
        )
    L += ['Write-Host "OK  Groups assigned"', ""]

    L += _proxy_address_lines(username, email)
    L += _set_user_attribute_lines(username, email, title, office, manager)
    return "\n".join(L)


def build_rejoiner_dual_script(ticket: dict, sf_account: dict, old_account: dict,
                                target_ou: str, email: str, password: str,
                                groups: list[str]) -> str:
    """
    Rejoiner with two accounts: copy employeeID from SF -> old, restore old, delete SF dummy.
    """
    sf_sam  = _e(sf_account["username"])
    old_sam = _e(old_account["username"])
    manager = _e(ticket.get("manager", ""))
    title   = _e(ticket.get("position", ""))
    office  = _e(ticket.get("office", ""))

    L = [
        "$cred = Get-Credential -Message 'Enter your AD admin credentials'",
        "$PSDefaultParameterValues = @{'*-AD*:Credential' = $cred}",
        "",
        '$ErrorActionPreference = "Stop"',
        "Import-Module ActiveDirectory -ErrorAction Stop",
        f'Write-Host "Processing REJOINER (dual account): restoring {old_account["username"]}"',
        "",
    ]

    L += _manager_lookup_lines(manager)

    L += [
        "# Copy employeeID from SF dummy account to old account",
        f"$sfEmpID = (Get-ADUser -Identity '{sf_sam}' -Properties EmployeeID).EmployeeID",
        f'Write-Host "EmployeeID from SF account: $sfEmpID"',
        f"Set-ADUser -Identity '{old_sam}' -EmployeeID $sfEmpID",
        'Write-Host "OK  EmployeeID copied"',
        "",
        "# Move old account to correct OU",
        f"$oldDN = (Get-ADUser -Identity '{old_sam}' -Properties DistinguishedName).DistinguishedName",
        f"Move-ADObject -Identity $oldDN -TargetPath '{_e(target_ou)}'",
        'Write-Host "OK  Account moved to correct OU"',
        "",
        "# Enable old account",
        f"Enable-ADAccount -Identity '{old_sam}'",
        'Write-Host "OK  Account enabled"',
        "",
        "# Clear msExchHideFromAddressLists",
        f"Set-ADUser -Identity '{old_sam}' -Clear msExchHideFromAddressLists",
        'Write-Host "OK  msExchHideFromAddressLists cleared"',
        "",
        "# Add to AD groups",
    ]
    for g in groups:
        L.append(
            f"try {{ Add-ADGroupMember -Identity '{_e(g)}' -Members '{old_sam}' }} "
            f"catch {{ Write-Warning \"Group '{_e(g)}': $_\" }}"
        )
    L += ['Write-Host "OK  Groups assigned"', ""]

    L += _proxy_address_lines(old_sam, email)
    L += _set_user_attribute_lines(old_sam, email, title, office, manager)
    L += [""]

    L += [
        "# Reset password on restored account",
        f"Set-ADAccountPassword -Identity '{old_sam}' -Reset `",
        f"    -NewPassword (ConvertTo-SecureString '{_e(password)}' -AsPlainText -Force)",
        f"Set-ADUser -Identity '{old_sam}' -ChangePasswordAtLogon $false",
        'Write-Host "OK  Password reset"',
        "",
        "# !! DELETE SF DUMMY ACCOUNT - verify above output before this runs !!",
        f"Remove-ADUser -Identity '{sf_sam}' -Confirm:$false",
        'Write-Host "OK  SF dummy account deleted"',
    ]
    return "\n".join(L)


def build_rejoiner_single_script(ticket: dict, account: dict, target_ou: str,
                                  email: str, password: str, groups: list[str]) -> str:
    """
    Rejoiner with only one disabled account (no SF duplicate).
    Steps: move -> enable -> clear hide flag -> groups -> attributes -> password.
    """
    sam     = _e(account["username"])
    manager = _e(ticket.get("manager", ""))
    title   = _e(ticket.get("position", ""))
    office  = _e(ticket.get("office", ""))

    L = [
        "$cred = Get-Credential -Message 'Enter your AD admin credentials'",
        "$PSDefaultParameterValues = @{'*-AD*:Credential' = $cred}",
        "",
        '$ErrorActionPreference = "Stop"',
        "Import-Module ActiveDirectory -ErrorAction Stop",
        f'Write-Host "Processing REJOINER (single account): {account["username"]}"',
        "",
    ]

    L += _manager_lookup_lines(manager)

    L += [
        f"$acctDN = (Get-ADUser -Identity '{sam}' -Properties DistinguishedName).DistinguishedName",
        f"Move-ADObject -Identity $acctDN -TargetPath '{_e(target_ou)}'",
        'Write-Host "OK  Moved to correct OU"',
        f"Enable-ADAccount -Identity '{sam}'",
        'Write-Host "OK  Account enabled"',
        f"Set-ADUser -Identity '{sam}' -Clear msExchHideFromAddressLists",
        'Write-Host "OK  msExchHideFromAddressLists cleared"',
        "",
        "# Add to AD groups",
    ]
    for g in groups:
        L.append(
            f"try {{ Add-ADGroupMember -Identity '{_e(g)}' -Members '{sam}' }} "
            f"catch {{ Write-Warning \"Group '{_e(g)}': $_\" }}"
        )
    L += ['Write-Host "OK  Groups assigned"', ""]

    L += _proxy_address_lines(sam, email)
    L += _set_user_attribute_lines(sam, email, title, office, manager)
    L += [""]

    L += [
        f"Set-ADAccountPassword -Identity '{sam}' -Reset `",
        f"    -NewPassword (ConvertTo-SecureString '{_e(password)}' -AsPlainText -Force)",
        f"Set-ADUser -Identity '{sam}' -ChangePasswordAtLogon $false",
        'Write-Host "OK  Password reset"',
    ]
    return "\n".join(L)
