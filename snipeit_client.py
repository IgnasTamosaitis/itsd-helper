"""
Snipe-IT inventory client.
Used to look up assets assigned to a leaver.
"""
import unicodedata

import requests

# Keywords used to identify a laptop asset by category or model name
_LAPTOP_CATEGORY_KW = {"laptop", "notebook", "kompiuter", "nešiojam", "computer", "portable"}

# Keywords used to identify a SIM card asset
_SIM_CATEGORY_KW = {"sim", "sim card", "simcard", "gsm", "mobile sim"}


def is_sim_asset(asset: dict) -> bool:
    """Return True if the asset looks like a SIM card based on its category name."""
    cat = (asset.get("category") or {}).get("name", "").lower()
    return any(k in cat for k in _SIM_CATEGORY_KW)


def is_laptop_asset(asset: dict) -> bool:
    """Return True if the asset looks like a laptop/computer."""
    cat   = (asset.get("category") or {}).get("name", "").lower()
    model = (asset.get("model")    or {}).get("name", "").lower()
    return (
        any(k in cat   for k in _LAPTOP_CATEGORY_KW) or
        any(k in model for k in _LAPTOP_MODEL_KW)
    )
_LAPTOP_MODEL_KW = {
    "probook", "elitebook", "zbook", "dragonfly",
    "thinkpad", "thinkbook", "ideapad",
    "latitude", "precision", "inspiron", "xps",
    "macbook", "vivobook", "zenbook", "aspire", "swift",
    "chromebook", "surface",
}


class SnipeITClient:
    def __init__(self, url: str, token: str):
        self.base = url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def test_connection(self) -> str:
        """Returns the logged-in user's name, or raises on failure."""
        r = self.session.get(f"{self.base}/api/v1/users/me", timeout=10)
        r.raise_for_status()
        u = r.json()
        return f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or "OK"

    @staticmethod
    def _fold(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text or "")
        return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold().strip()

    def find_user(self, first_name: str, last_name: str) -> dict | None:
        """
        Search Snipe-IT for a user by full name.
        Returns the best-matching user dict or None.
        """
        full_name = f"{first_name} {last_name}".strip()
        queries = []
        for query in (full_name, last_name.strip(), first_name.strip()):
            if query and query not in queries:
                queries.append(query)

        matches: list[dict] = []
        seen_ids: set[int] = set()
        for query in queries:
            r = self.session.get(
                f"{self.base}/api/v1/users",
                params={"search": query, "limit": 20, "sort": "name", "order": "asc"},
                timeout=15,
            )
            r.raise_for_status()
            for user in r.json().get("rows", []):
                user_id = user.get("id")
                if user_id in seen_ids:
                    continue
                seen_ids.add(user_id)
                matches.append(user)

        if not matches:
            return None

        wanted_full = self._fold(full_name)
        wanted_first = self._fold(first_name)
        wanted_last = self._fold(last_name)

        def _score(user: dict) -> tuple[int, int]:
            first = self._fold(user.get("first_name", ""))
            last = self._fold(user.get("last_name", ""))
            full = self._fold(f"{user.get('first_name', '')} {user.get('last_name', '')}")
            score = 0
            if full == wanted_full and wanted_full:
                score += 100
            if last == wanted_last and wanted_last:
                score += 30
            if first == wanted_first and wanted_first:
                score += 20
            if wanted_first and first.startswith(wanted_first[:4]):
                score += 5
            if wanted_last and last.startswith(wanted_last[:4]):
                score += 5
            return (score, -int(user.get("id", 0)))

        matches.sort(key=_score, reverse=True)
        return matches[0]

    def find_exact_user(self, first_name: str, last_name: str) -> dict | None:
        """Return a Snipe-IT user only when first and last name both match exactly."""
        wanted_first = self._fold(first_name)
        wanted_last = self._fold(last_name)
        if not wanted_first or not wanted_last:
            return None
        user = self.find_user(first_name, last_name)
        if not user:
            return None
        first = self._fold(user.get("first_name", ""))
        last = self._fold(user.get("last_name", ""))
        if first == wanted_first and last == wanted_last:
            return user
        return None

    def get_user_details(self, user_id: int) -> dict:
        r = self.session.get(f"{self.base}/api/v1/users/{user_id}", timeout=15)
        r.raise_for_status()
        return r.json()

    def get_user_assets(self, user_id: int) -> list[dict]:
        """Return hardware assets assigned to a user according to Snipe-IT."""
        r = self.session.get(f"{self.base}/api/v1/users/{user_id}/assets", timeout=15)
        r.raise_for_status()
        return r.json().get("rows", [])

    def _find_exact_named_row(self, endpoint: str, name: str) -> dict:
        """Return the Snipe-IT row with an exact name match."""
        wanted = self._fold(name)
        r = self.session.get(
            f"{self.base}/api/v1/{endpoint}",
            params={"search": name, "limit": 100, "sort": "name", "order": "asc"},
            timeout=15,
        )
        r.raise_for_status()
        rows = r.json().get("rows", [])
        for row in rows:
            if self._fold(row.get("name", "")) == wanted:
                return row
        available = ", ".join(row.get("name", "") for row in rows[:10] if row.get("name"))
        raise ValueError(
            f"Snipe-IT {endpoint} entry not found: {name}"
            + (f". Search returned: {available}" if available else "")
        )

    def _get_checkin_status_id(self) -> int:
        """Return the exact 'Storage' status label ID."""
        return int(self._find_exact_named_row("statuslabels", "Storage")["id"])

    _DEFAULT_CHECKIN_LOCATION = "Girteka Park (Laisves 36)"

    def _get_checkin_location_id(self, location_name: str = "") -> int:
        """Return the location ID for the given Snipe-IT location name."""
        return int(self._find_exact_named_row(
            "locations", location_name or self._DEFAULT_CHECKIN_LOCATION
        )["id"])

    def checkin_asset(self, asset_id: int, status_id: int, location_id: int) -> dict:
        """Check a single hardware asset back into Snipe-IT."""
        r = self.session.post(
            f"{self.base}/api/v1/hardware/{asset_id}/checkin",
            json={"status_id": status_id, "location_id": location_id},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        if str(data.get("status", "")).casefold() == "error":
            raise ValueError(data.get("messages") or f"Asset {asset_id} check-in failed.")
        return data

    def delete_asset(self, asset_id: int) -> None:
        """Permanently delete a hardware asset from Snipe-IT."""
        r = self.session.delete(f"{self.base}/api/v1/hardware/{asset_id}", timeout=20)
        r.raise_for_status()
        data = r.json()
        if str(data.get("status", "")).casefold() == "error":
            raise ValueError(data.get("messages") or f"Asset {asset_id} delete failed.")

    def _get_archive_status_id(self) -> int:
        """Return the exact 'Archived' status label ID."""
        return int(self._find_exact_named_row("statuslabels", "Archived")["id"])

    def archive_asset(self, asset_id: int) -> None:
        """Set a hardware asset's status to Archived in Snipe-IT."""
        archive_status_id = self._get_archive_status_id()
        r = self.session.patch(
            f"{self.base}/api/v1/hardware/{asset_id}",
            json={"status_id": archive_status_id},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        if str(data.get("status", "")).casefold() == "error":
            raise ValueError(data.get("messages") or f"Asset {asset_id} archive failed.")

    def checkin_all_user_assets(self, first_name: str, last_name: str,
                                location_name: str = "") -> dict:
        """Find a user, check in all hardware assets, and delete any SIM assets."""
        user = self.find_user(first_name, last_name)
        if not user:
            raise ValueError(f"Snipe-IT user not found: {first_name} {last_name}".strip())

        assets = self.get_user_assets(user["id"])
        if not assets:
            return {"user": user, "checked_in": [], "deleted": [], "count": 0}

        status_id = self._get_checkin_status_id()
        location_id = self._get_checkin_location_id(location_name)
        checked_in, deleted = [], []
        for asset in assets:
            asset_id = asset.get("id")
            if not asset_id:
                continue
            self.checkin_asset(int(asset_id), status_id, location_id)
            checked_in.append(asset)
            if is_sim_asset(asset):
                self.delete_asset(int(asset_id))
                deleted.append(asset)
        return {"user": user, "checked_in": checked_in, "deleted": deleted, "count": len(checked_in)}

    def get_laptop(self, user_id: int) -> dict | None:
        """
        Returns {model, serial, asset_tag, category} for the laptop assigned to
        the given user, or None if no laptop-like asset is found.
        Assets are scored: category keyword match (+10) + model keyword match (+5).
        """
        assets = self.get_user_assets(user_id)

        def _score(a: dict) -> int:
            cat   = (a.get("category") or {}).get("name", "").lower()
            model = (a.get("model")    or {}).get("name", "").lower()
            score = 0
            if any(k in cat   for k in _LAPTOP_CATEGORY_KW): score += 10
            if any(k in model for k in _LAPTOP_MODEL_KW):    score += 5
            return score

        ranked = sorted(assets, key=_score, reverse=True)
        if not ranked or _score(ranked[0]) == 0:
            return None

        best = ranked[0]
        return {
            "model":     (best.get("model")    or {}).get("name", ""),
            "serial":    best.get("serial", ""),
            "asset_tag": best.get("asset_tag", ""),
            "category":  (best.get("category") or {}).get("name", ""),
        }
