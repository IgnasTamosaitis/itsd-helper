import unittest
from unittest.mock import Mock, patch

import requests

import updater


class InstalledUpdaterTests(unittest.TestCase):
    def _latest_response(self, tag="v1.3.1"):
        response = Mock()
        response.raise_for_status.return_value = None
        response.headers = {
            "Location": (
                "https://github.com/IgnasTamosaitis/Jira-onboarding-helper/"
                f"releases/tag/{tag}"
            )
        }
        return response

    def test_installed_build_selects_msi_release_asset(self):
        with (
            patch.object(updater, "IS_FROZEN", True),
            patch.object(updater, "current_version", return_value="1.3.0"),
            patch.object(
                updater.requests,
                "get",
                return_value=self._latest_response(),
            ),
        ):
            release = updater.check_for_update()

        self.assertEqual(release["installer_name"], "Jira-Reminders-1.3.1.msi")
        self.assertEqual(
            release["installer_url"],
            "https://github.com/IgnasTamosaitis/Jira-onboarding-helper/"
            "releases/download/v1.3.1/Jira-Reminders-1.3.1.msi",
        )
        self.assertNotIn("zipball_url", release)

    def test_current_installed_build_is_up_to_date(self):
        with (
            patch.object(updater, "IS_FROZEN", True),
            patch.object(updater, "current_version", return_value="1.3.1"),
            patch.object(
                updater.requests,
                "get",
                return_value=self._latest_response(),
            ),
        ):
            self.assertIsNone(updater.check_for_update())

    def test_source_build_keeps_zip_update_path(self):
        with (
            patch.object(updater, "IS_FROZEN", False),
            patch.object(updater, "current_version", return_value="1.3.0"),
            patch.object(
                updater.requests,
                "get",
                return_value=self._latest_response(),
            ),
        ):
            release = updater.check_for_update()

        self.assertEqual(
            release["zipball_url"],
            "https://github.com/IgnasTamosaitis/Jira-onboarding-helper/"
            "archive/refs/tags/v1.3.1.zip",
        )
        self.assertNotIn("installer_url", release)

    def test_network_failure_is_not_reported_as_up_to_date(self):
        with patch.object(
            updater.requests,
            "get",
            side_effect=requests.ConnectionError("offline"),
        ):
            with self.assertRaisesRegex(updater.UpdateCheckError, "could not be reached"):
                updater.check_for_update()

    def test_unexpected_redirect_is_not_reported_as_up_to_date(self):
        response = self._latest_response()
        response.headers = {}
        with patch.object(updater.requests, "get", return_value=response):
            with self.assertRaisesRegex(updater.UpdateCheckError, "unexpected"):
                updater.check_for_update()


if __name__ == "__main__":
    unittest.main()
