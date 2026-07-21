"""
Snipe-IT inventory client.
Used to look up assigned assets for onboarding checks.
"""
import unicodedata

import requests


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
