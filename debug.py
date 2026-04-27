"""
Run this from the command line to diagnose connection/JQL issues:
  python debug.py
"""
import json
from pathlib import Path
from storage import load_config

cfg = load_config()
if not cfg:
    print("ERROR: No config found. Run app.py first and save settings.")
    input()
    raise SystemExit

import requests

session = requests.Session()
session.auth = (cfg["email"], cfg["api_token"])
session.headers.update({"Accept": "application/json"})
base = cfg["jira_url"].rstrip("/")

print("=== 1. Testing connection ===")
r = session.get(f"{base}/rest/api/3/myself", timeout=10)
print(f"Status: {r.status_code}")
if r.ok:
    me = r.json()
    print(f"Logged in as: {me.get('displayName')}  ({me.get('emailAddress')})")
else:
    print(f"FAILED: {r.text[:300]}")
    input("Press Enter to exit.")
    raise SystemExit

print()
print("=== 2. Running JQL query ===")
jql = cfg.get("jql", "")
date_field = cfg.get("date_field", "customfield_10980")
print(f"JQL: {jql}")
r2 = session.get(
    f"{base}/rest/api/3/search/jql",
    params={"jql": jql, "maxResults": 10, "fields": f"summary,status,{date_field},customfield_10109,customfield_10111"},
    timeout=15,
)
print(f"Status: {r2.status_code}")
if r2.ok:
    data = r2.json()
    total = data.get("total", 0)
    issues = data.get("issues", [])
    print(f"Total matching: {total}   (returned: {len(issues)})")
    for iss in issues:
        f = iss["fields"]
        name = f"{f.get('customfield_10109') or ''} {f.get('customfield_10111') or ''}".strip() or f.get("summary")
        sd   = f.get(date_field, "no date")
        st   = (f.get("status") or {}).get("name", "?")
        print(f"  {iss['key']}  {name}  start={sd}  status={st}")
    print()
    print("=== 3. All onboarding tickets (no status filter) + exact status names ===")
    jql2 = 'assignee = currentUser() AND issuetype = "SF: Employee onboarding" ORDER BY created DESC'
    r3 = session.get(f"{base}/rest/api/3/search/jql",
                     params={"jql": jql2, "maxResults": 20, "fields": f"summary,status,{date_field}"},
                     timeout=15)
    if r3.ok:
        d2 = r3.json()
        print(f"Total: {d2.get('total', 0)} ticket(s)")
        for iss in d2.get("issues", []):
            f = iss["fields"]
            status = (f.get("status") or {}).get("name", "?")
            sd = f.get(date_field, "-")
            print(f"  {iss['key']}  status='{status}'  start={sd}  {f.get('summary','')[:50]}")
    else:
        print(f"FAILED: {r3.text[:200]}")
else:
    print(f"FAILED: {r2.text[:500]}")

print()
input("Press Enter to exit.")
