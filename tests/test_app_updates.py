import queue
import unittest
from unittest.mock import patch

import app


class AppUpdatePromptTests(unittest.TestCase):
    def setUp(self):
        self.target = app.App.__new__(app.App)
        self.target._ui_queue = queue.Queue()
        self.target._pending_update = None

    def test_new_release_is_queued_for_prompting(self):
        release = {"version": "v1.3.1", "notes": "Update available"}

        with patch.object(app.updater, "check_for_update", return_value=release):
            self.target._do_update_check()

        self.assertEqual(
            self.target._ui_queue.get_nowait(),
            ("update_available", release),
        )

    def test_pending_release_is_not_queued_again(self):
        release = {"version": "v1.3.1", "notes": "Update available"}
        self.target._pending_update = release

        with patch.object(app.updater, "check_for_update", return_value=release):
            self.target._do_update_check()

        self.assertTrue(self.target._ui_queue.empty())


if __name__ == "__main__":
    unittest.main()
