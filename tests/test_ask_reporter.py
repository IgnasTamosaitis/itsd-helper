import unittest

from ui import AskReporterDialog


class AskReporterTemplateTests(unittest.TestCase):
    def test_standard_template_matches_requested_copy(self):
        rendered = AskReporterDialog._TEMPLATE.format(name="Gustas Pipiras")

        self.assertEqual(
            rendered,
            "Hello, @manager,\n"
            "Could you please let us know the name of an existing employee with similar "
            "access rights that we can use as a template for Gustas Pipiras's account setup?\n"
            "Thank you.",
        )

    def test_disabled_buddy_template_does_not_request_extra_access_details(self):
        rendered = AskReporterDialog._TEMPLATE_DISABLED_BUDDY.format(
            buddy_name="Former Employee",
            name="Gustas Pipiras",
        )

        self.assertNotIn("additional applications", rendered)
        self.assertTrue(rendered.endswith("account setup?\nThank you."))


if __name__ == "__main__":
    unittest.main()
