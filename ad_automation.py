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
        "$mgrEmail = $null",
        "try {",
        f"    $mgrMatches = @(Get-ADUser -Filter {{DisplayName -eq '{manager}'}} -Properties DistinguishedName, EmailAddress)",
        "    if ($mgrMatches.Count -eq 1) {",
        "        $mgrDn    = $mgrMatches[0].DistinguishedName",
        "        $mgrEmail = $mgrMatches[0].EmailAddress",
        "    } elseif ($mgrMatches.Count -eq 0) {",
        f"        Write-Warning 'Manager not found: {manager}'",
        "    } else {",
        f"        Write-Warning 'Multiple managers found for: {manager}. Manager was not set.'",
        "    }",
        "} catch {",
        f"    Write-Warning 'Manager lookup failed for: {manager} — $_. Manager will not be set.'",
        "}",
        "",
    ]


def _proxy_address_lines(sam: str, email: str) -> list[str]:
    return [
        "# Set primary SMTP proxy address",
        f"$smtpAddress = 'SMTP:{_e(email)}'",
        f"$currentProxies = @(Get-ADUser -Identity '{sam}' -Properties proxyAddresses).proxyAddresses",
        "if ($currentProxies -notcontains $smtpAddress) {",
        f"    Set-ADUser -Identity '{sam}' -Add @{{proxyAddresses=$smtpAddress}}",
        '    Write-Host "OK  proxyAddresses set"',
        "} else {",
        '    Write-Host "OK  proxyAddresses already present"',
        "}",
        "",
        "# Ensure girteka.lt proxy address is lowercase smtp (secondary only)",
        "$ltUpper = $currentProxies | Where-Object { $_ -cmatch '^SMTP:.+@girteka\\.lt$' }",
        "foreach ($addr in $ltUpper) {",
        f"    $lower = 'smtp:' + $addr.Substring(5)",
        f"    Set-ADUser -Identity '{sam}' -Remove @{{proxyAddresses=$addr}}",
        f"    Set-ADUser -Identity '{sam}' -Add @{{proxyAddresses=$lower}}",
        '    Write-Host "OK  Lowercased $addr -> $lower"',
        "}",
        "",
        "# Set targetAddress to match primary SMTP",
        f"Set-ADUser -Identity '{sam}' -Replace @{{targetAddress='{_e(email)}'}}",
        'Write-Host "OK  targetAddress set"',
        "",
    ]


def _set_user_attribute_lines(sam: str, email: str, title: str,
                              office: str, manager: str,
                              company: str = "", address: dict = None,
                              department: str = "") -> list[str]:
    addr = address or {}
    effective_office = addr.get("office") or office
    L = [
        "# Update organisation attributes",
        "$setParams = @{",
        f"    EmailAddress = '{_e(email)}'",
    ]
    if title:
        L.append(f"    Title = '{title}'")
        L.append(f"    Description = '{title}'")
    if effective_office:
        L.append(f"    Office = '{_e(effective_office)}'")
    if department:
        L.append(f"    Department = '{_e(department)}'")
    if company:
        L.append(f"    Company = '{_e(company)}'")
    if addr.get("street"):
        L.append(f"    StreetAddress = '{_e(addr['street'])}'")
    if addr.get("city"):
        L.append(f"    City = '{_e(addr['city'])}'")
    if addr.get("zip"):
        L.append(f"    PostalCode = '{_e(addr['zip'])}'")
    if addr.get("country"):
        L.append(f"    Country = '{_e(addr['country'])}'")
    L.append("}")
    if manager:
        L.append("if ($mgrDn) { $setParams['Manager'] = $mgrDn }")
    L += [
        f"Set-ADUser -Identity '{sam}' @setParams",
        'Write-Host "OK  Attributes updated"',
        "if ($mgrEmail) {",
        f"    Set-ADUser -Identity '{sam}' -Replace @{{extensionAttribute10=$mgrEmail}}",
        '    Write-Host "OK  extensionAttribute10 set to $mgrEmail"',
        "} else {",
        '    Write-Warning "extensionAttribute10 not set — manager email not found"',
        "}",
    ]
    ext15 = addr.get("ext15", "") if addr else ""
    if ext15:
        L += [
            f"Set-ADUser -Identity '{sam}' -Replace @{{extensionAttribute15='{_e(ext15)}'}}",
            f'Write-Host "OK  extensionAttribute15 set to {ext15}"',
        ]
    else:
        L += [
            f"Set-ADUser -Identity '{sam}' -Clear extensionAttribute15",
            'Write-Host "OK  extensionAttribute15 cleared"',
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

_LAISVES_ADDRESS = {
    "street":  "Laisvės pr. 36",
    "city":    "Vilnius",
    "zip":     "5623",
    "country": "LT",
    "office":  "Vilnius",
    "ext15":   "SF",
}

_LAISVES_KEYWORDS = [
    "gcc", "tndm", "girteka", "me trailer", "classtrucks",
]

def detect_company_address(company: str) -> dict:
    c = company.lower()
    if any(k in c for k in _LAISVES_KEYWORDS):
        return _LAISVES_ADDRESS
    return {}

def build_email(first: str, last: str, domain: str) -> str:
    f = _ascii(first).strip()
    l = _ascii(last).strip()
    if domain == "tndmtrucking.com":
        return f"{f[0].upper()}{l.capitalize()}@{domain}"
    return f"{f.capitalize()}.{l.capitalize()}@{domain}"

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


def get_buddy_info(sam: str) -> tuple[str, list[str], str, str, dict]:
    """Returns (ou, [group_names], error, department, ext_attrs). On success error is empty string."""
    out, err, code = run_ps(f"""
Import-Module ActiveDirectory -ErrorAction Stop
$u = Get-ADUser -Identity '{_e(sam)}' -Properties MemberOf, DistinguishedName, Department, `
    extensionAttribute5, extensionAttribute14, extensionAttribute15 -ErrorAction Stop
$ou = $u.DistinguishedName -replace '^CN=[^,]+,', ''
"OU:$ou"
"DEPT:$(if ($u.Department) {{ $u.Department }} else {{ '' }})"
"EA5:$(if ($u.extensionAttribute5) {{ $u.extensionAttribute5 }} else {{ '' }})"
"EA14:$(if ($u.extensionAttribute14) {{ $u.extensionAttribute14 }} else {{ '' }})"
"EA15:$(if ($u.extensionAttribute15) {{ $u.extensionAttribute15 }} else {{ '' }})"
foreach ($g in $u.MemberOf) {{ "GRP:$((Get-ADGroup $g).Name)" }}
""")
    if code != 0:
        return "", [], (err or "User not found"), "", {}
    ou, groups, department = "", [], ""
    ext_attrs: dict[str, str] = {"extensionAttribute5": "", "extensionAttribute14": "", "extensionAttribute15": ""}
    for line in out.splitlines():
        if line.startswith("OU:"):
            ou = line[3:].strip()
        elif line.startswith("DEPT:"):
            department = line[5:].strip()
        elif line.startswith("EA5:"):
            ext_attrs["extensionAttribute5"] = line[4:].strip()
        elif line.startswith("EA14:"):
            ext_attrs["extensionAttribute14"] = line[5:].strip()
        elif line.startswith("EA15:"):
            ext_attrs["extensionAttribute15"] = line[5:].strip()
        elif line.startswith("GRP:"):
            g = line[4:].strip()
            if "/O=" not in g:
                groups.append(g)
    return ou, sorted(groups), "", department, ext_attrs

def build_ext_attr_lines(sam: str, ext_attrs: dict) -> list[str]:
    """Generates Set-ADUser -Replace for selected extensionAttributes."""
    if not ext_attrs:
        return []
    pairs = "; ".join(f"{k}='{_e(v)}'" for k, v in ext_attrs.items() if v)
    if not pairs:
        return []
    return [
        "# Set extended attributes from buddy",
        f"Set-ADUser -Identity '{sam}' -Replace @{{{pairs}}}",
        'Write-Host "OK  Extended attributes set"',
        "",
    ]

# ── Script builders ───────────────────────────────────────────────────────────

def build_new_joiner_script(ticket: dict, sf_account: dict, target_ou: str,
                             email: str, password: str, groups: list[str],
                             department: str = "", ext_attrs: dict = None) -> str:
    """
    New joiner: one SF-provisioned account.
    Steps: move to buddy OU -> add groups -> set proxyAddresses -> update org attributes.
    """
    username = _e(sf_account["username"])
    manager  = _e(ticket.get("manager", ""))
    title    = _e(ticket.get("position", ""))
    office   = _e(ticket.get("office", ""))
    company  = ticket.get("company_name", "")
    address  = detect_company_address(company)

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
    L += _set_user_attribute_lines(username, email, title, office, manager, _e(company), address, department)
    L += build_ext_attr_lines(username, ext_attrs or {})
    return "\n".join(L)


def build_rejoiner_dual_script(ticket: dict, sf_account: dict, old_account: dict,
                                target_ou: str, email: str, password: str,
                                groups: list[str], department: str = "",
                                ext_attrs: dict = None) -> str:
    """
    Rejoiner with two accounts: copy employeeID from SF -> old, restore old, delete SF dummy.
    """
    sf_sam  = _e(sf_account["username"])
    old_sam = _e(old_account["username"])
    manager = _e(ticket.get("manager", ""))
    title   = _e(ticket.get("position", ""))
    office  = _e(ticket.get("office", ""))
    company = ticket.get("company_name", "")
    address = detect_company_address(company)

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
    L += _set_user_attribute_lines(old_sam, email, title, office, manager, _e(company), address, department)
    L += build_ext_attr_lines(old_sam, ext_attrs or {})
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
                                  email: str, password: str, groups: list[str],
                                  department: str = "", ext_attrs: dict = None) -> str:
    """
    Rejoiner with only one disabled account (no SF duplicate).
    Steps: move -> enable -> clear hide flag -> groups -> attributes -> password.
    """
    sam     = _e(account["username"])
    manager = _e(ticket.get("manager", ""))
    title   = _e(ticket.get("position", ""))
    office  = _e(ticket.get("office", ""))
    company = ticket.get("company_name", "")
    address = detect_company_address(company)

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
    L += _set_user_attribute_lines(sam, email, title, office, manager, _e(company), address, department)
    L += build_ext_attr_lines(sam, ext_attrs or {})
    L += [""]

    L += [
        f"Set-ADAccountPassword -Identity '{sam}' -Reset `",
        f"    -NewPassword (ConvertTo-SecureString '{_e(password)}' -AsPlainText -Force)",
        f"Set-ADUser -Identity '{sam}' -ChangePasswordAtLogon $false",
        'Write-Host "OK  Password reset"',
    ]
    return "\n".join(L)
