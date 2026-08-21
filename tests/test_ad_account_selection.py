import unittest
from unittest.mock import patch

from ad_automation import (
    find_user_account_by_username,
    select_new_joiner_account,
)


class NewJoinerAccountSelectionTests(unittest.TestCase):
    def test_sf_account_keeps_priority(self):
        accounts = [
            {"username": "x10000", "is_sf": True},
            {"username": "x17330", "is_sf": False},
        ]

        selected = select_new_joiner_account(accounts, "x17330")

        self.assertEqual(selected["username"], "x10000")

    def test_exact_jira_username_selects_manual_account_without_sf_account(self):
        accounts = [{"username": "X17330", "is_sf": False}]

        selected = select_new_joiner_account(accounts, "x17330")

        self.assertEqual(selected["username"], "X17330")

    def test_nonmatching_jira_username_does_not_select_an_account(self):
        accounts = [{"username": "x99999", "is_sf": False}]

        self.assertEqual(select_new_joiner_account(accounts, "x17330"), {})

    @patch("ad_automation.run_ps")
    def test_exact_username_lookup_returns_validated_ad_account(self, mock_run_ps):
        mock_run_ps.return_value = (
            "x17330|True|Talent Partner|CN=Aiste,OU=Users,DC=example,DC=com|17330",
            "",
            0,
        )

        account = find_user_account_by_username("x17330")

        self.assertEqual(account["username"], "x17330")
        self.assertFalse(account["is_sf"])
        script = mock_run_ps.call_args.args[0]
        self.assertIn("SamAccountName -eq 'x17330'", script)


if __name__ == "__main__":
    unittest.main()
