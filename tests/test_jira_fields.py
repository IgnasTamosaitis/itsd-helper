import unittest

from jira_client import JiraClient


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
        self.assertIn("customfield_10993", fake_session.last_params["fields"])
        self.assertIn("customfield_14076", fake_session.last_params["fields"])
        self.assertEqual(
            fake_session.last_params["jql"],
            "assignee = currentUser()",
        )


if __name__ == "__main__":
    unittest.main()
