import unittest
from unittest.mock import Mock, patch

import updater


class InstalledUpdaterTests(unittest.TestCase):
    def _response(self, assets):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "tag_name": "v1.3.1",
            "body": "Installer update",
            "zipball_url": "https://example.invalid/source.zip",
            "assets": assets,
        }
        return response

    def test_installed_build_selects_msi_release_asset(self):
        assets = [
            {
                "name": "Jira-Reminders-1.3.1.msi",
                "browser_download_url": "https://example.invalid/app.msi",
            }
        ]
        with (
            patch.object(updater, "IS_FROZEN", True),
            patch.object(updater, "current_version", return_value="1.3.0"),
            patch.object(updater.requests, "get", return_value=self._response(assets)),
        ):
            release = updater.check_for_update()

        self.assertEqual(release["installer_name"], "Jira-Reminders-1.3.1.msi")
        self.assertEqual(release["installer_url"], "https://example.invalid/app.msi")
        self.assertNotIn("zipball_url", release)

    def test_installed_build_ignores_release_without_msi(self):
        with (
            patch.object(updater, "IS_FROZEN", True),
            patch.object(updater, "current_version", return_value="1.3.0"),
            patch.object(updater.requests, "get", return_value=self._response([])),
        ):
            self.assertIsNone(updater.check_for_update())

    def test_source_build_keeps_zip_update_path(self):
        with (
            patch.object(updater, "IS_FROZEN", False),
            patch.object(updater, "current_version", return_value="1.3.0"),
            patch.object(updater.requests, "get", return_value=self._response([])),
        ):
            release = updater.check_for_update()

        self.assertEqual(release["zipball_url"], "https://example.invalid/source.zip")
        self.assertNotIn("installer_url", release)


if __name__ == "__main__":
    unittest.main()
