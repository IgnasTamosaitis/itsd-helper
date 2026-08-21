import unittest

from jira_client import JiraClient, resolve_mover_buddy


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.last_params = {}

    def get(self, _url, params=None, timeout=None):
        self.last_params = params or {}
        return _FakeResponse(self.payload)


class JiraLocationFieldTests(unittest.TestCase):
    def test_readonly_company_is_used_when_primary_company_is_none(self):
        payload = {
            "issues": [
                {
                    "id": "1",
                    "key": "PNC-TEST",
                    "fields": {
                        "summary": "Test",
                        "status": {"name": "Pending"},
                        "reporter": None,
                        "customfield_10109": "Test",
                        "customfield_10111": "Person",
                        "customfield_10977": "Tester",
                        "customfield_10983": "Poznan Campus",
                        "customfield_10978": "Test Manager",
                        "customfield_14703": None,
                        "customfield_10113": "",
                        "customfield_10976": "None",
                        "customfield_10993": "Girpoltrans sp. z o.o.",
                        "customfield_14076": "Poland",
                        "customfield_11436": None,
                        "customfield_11171": "x17330",
                        "customfield_10980": "2099-01-01",
                    },
                }
            ]
        }
        client = JiraClient("https://example.atlassian.net", "test@example.com", "token")
        fake_session = _FakeSession(payload)
        client.session = fake_session

        tickets = client.get_new_joiner_tickets("assignee = currentUser()")

        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0]["company_name"], "Girpoltrans sp. z o.o.")
        self.assertEqual(tickets[0]["office"], "Poznan Campus")
        self.assertEqual(tickets[0]["country"], "Poland")
        self.assertEqual(tickets[0]["person_id_external"], "x17330")
        self.assertIn("customfield_10993", fake_session.last_params["fields"])
        self.assertIn("customfield_14076", fake_session.last_params["fields"])
        self.assertIn("customfield_11171", fake_session.last_params["fields"])
        self.assertEqual(
            fake_session.last_params["jql"],
            "assignee = currentUser()",
        )


class MoverJiraFieldTests(unittest.TestCase):
    @staticmethod
    def _user(account_id, name):
        return {"accountId": account_id, "displayName": name}

    def test_mover_fields_and_different_axapta_user_are_parsed(self):
        payload = {"issues": [{
            "id": "99",
            "key": "PNC-24493",
            "fields": {
                "summary": "Employee moving form",
                "status": {"name": "Open"},
                "reporter": self._user("reporter", "Reporter Person"),
                "customfield_11213": self._user("employee", "Moving Person"),
                "customfield_10192": "2099-08-10",
                "customfield_10996": "Old title",
                "customfield_11167": "New title",
                "customfield_10992": "Old department",
                "customfield_10993": "Girteka Logistics UAB",
                "customfield_10057": self._user("manager", "New Manager"),
                "customfield_10191": {"value": "Girteka Park"},
                "customfield_10145": "-",
                "customfield_10894": self._user("buddy", "AD Buddy"),
                "customfield_10900": self._user("ax", "Axapta Buddy"),
                "customfield_10899": [{"value": "Yes"}],
                "customfield_14076": "Lithuania",
            },
        }]}
        client = JiraClient("https://example.atlassian.net", "test@example.com", "token")
        fake_session = _FakeSession(payload)
        client.session = fake_session

        movers = client.get_mover_tickets("assignee = currentUser()")

        self.assertEqual(len(movers), 1)
        mover = movers[0]
        self.assertEqual(mover["name"], "Moving Person")
        self.assertEqual(mover["new_position"], "New title")
        self.assertEqual(mover["manager"], "New Manager")
        self.assertEqual(mover["office"], "Girteka Park")
        self.assertEqual(mover["ad_buddy"]["name"], "AD Buddy")
        self.assertIn("Axapta Buddy", mover["axapta_notice"])
        self.assertIn("customfield_10894", fake_session.last_params["fields"])

    def test_buddy_axapta_precedence_combinations(self):
        buddy = {"name": "Buddy", "jira_account_id": "one"}
        same_ax = {"name": "Buddy Renamed", "jira_account_id": "one"}
        other_ax = {"name": "AX Buddy", "jira_account_id": "two"}

        same = resolve_mover_buddy(buddy, same_ax)
        self.assertTrue(same["confirmed_by_both"])
        self.assertFalse(same["axapta_notice"])
        self.assertEqual(same["ad_buddy"]["source"], "buddy_and_axapta_fields")

        different = resolve_mover_buddy(buddy, other_ax)
        self.assertEqual(different["ad_buddy"]["name"], "Buddy")
        self.assertIn("AX Buddy", different["axapta_notice"])

        ax_only = resolve_mover_buddy(None, other_ax)
        self.assertEqual(ax_only["ad_buddy"]["name"], "AX Buddy")
        self.assertEqual(ax_only["ad_buddy"]["source"], "axapta_fallback")

        self.assertIsNone(resolve_mover_buddy(None, None)["ad_buddy"])


if __name__ == "__main__":
    unittest.main()
