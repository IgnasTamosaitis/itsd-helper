import unittest

from mover_automation import (
    build_mover_plan,
    build_mover_script,
    choose_enabled_account,
    plan_group_changes,
)


class MoverGroupPlanTests(unittest.TestCase):
    def test_exact_group_diff_preserves_shared_and_blocks_restricted(self):
        plan = plan_group_changes(
            ["Shared", "Old Access", "Power BI Pro license"],
            ["shared", "New Access", "Power BI Pro license", "RDS-Disabled"],
        )
        self.assertEqual(plan["add"], ["New Access"])
        self.assertEqual(plan["keep"], ["shared"])
        self.assertEqual(plan["remove"], ["Old Access", "Power BI Pro license"])
        self.assertEqual(plan["desired"], ["New Access", "shared"])
        self.assertEqual(
            plan["blocked_buddy"], ["Power BI Pro license", "RDS-Disabled"]
        )

    def test_enabled_account_must_be_unambiguous(self):
        self.assertEqual(
            choose_enabled_account(
                [{"username": "USER1", "enabled": True, "disabled": False}], "employee"
            )["username"],
            "USER1",
        )
        with self.assertRaisesRegex(ValueError, "Multiple enabled"):
            choose_enabled_account([
                {"username": "ONE", "enabled": True, "disabled": False},
                {"username": "TWO", "enabled": True, "disabled": False},
            ], "employee")


class MoverScriptTests(unittest.TestCase):
    def setUp(self):
        self.ticket = {
            "key": "PNC-1",
            "new_position": "Team Lead",
            "company_name": "Girteka Logistics UAB",
            "manager": "New Manager",
            "office": "Girteka Park",
            "axapta_notice": "Axapta rights must match AXUSER",
        }
        self.mover = {
            "sam": "MOVER",
            "enabled": True,
            "ou": "OU=Old,DC=example,DC=com",
            "title": "Old title",
            "description": "Old title",
            "department": "Old Dept",
            "company": "Old Company",
            "manager_name": "Old Manager",
            "groups": ["Shared", "Old Group"],
        }
        self.buddy = {
            "sam": "BUDDY",
            "enabled": True,
            "ou": "OU=New,DC=example,DC=com",
            "department": "New Dept",
            "manager_sam": "MANAGER",
            "groups": ["Shared", "New Group", "Power BI Pro license"],
        }
        self.manager = {
            "sam": "MANAGER",
            "display_name": "New Manager",
            "enabled": True,
            "email": "manager@example.com",
        }

    def test_plan_and_script_set_required_state_without_onboarding_changes(self):
        plan = build_mover_plan(self.ticket, self.mover, self.buddy, self.manager)
        script = build_mover_script(plan)

        self.assertEqual(plan["groups"]["add"], ["New Group"])
        self.assertEqual(plan["groups"]["remove"], ["Old Group"])
        self.assertIn("Title = 'Team Lead'", script)
        self.assertIn("Description = 'Team Lead'", script)
        self.assertIn("Department = 'New Dept'", script)
        self.assertIn("Company = 'Girteka Logistics UAB'", script)
        self.assertIn("Manager = $manager.DistinguishedName", script)
        self.assertIn("TargetPath 'OU=New,DC=example,DC=com'", script)
        self.assertIn("Add-ADGroupMember -Identity 'New Group'", script)
        self.assertIn("Remove-ADGroupMember -Identity 'Old Group'", script)
        self.assertIn("Final group verification failed", script)
        self.assertNotIn("Set-ADAccountPassword", script)
        self.assertNotIn("proxyAddresses", script)
        self.assertNotIn("Power BI Pro license' -Members", script)

    def test_manager_mismatch_requires_acknowledgement(self):
        self.buddy["manager_sam"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "Manager mismatch"):
            build_mover_plan(self.ticket, self.mover, self.buddy, self.manager)
        plan = build_mover_plan(
            self.ticket, self.mover, self.buddy, self.manager,
            acknowledge_manager_mismatch=True,
        )
        self.assertTrue(plan["manager_mismatch"])

    def test_missing_buddy_manager_blocks_crosscheck(self):
        self.buddy["manager_sam"] = ""
        with self.assertRaisesRegex(ValueError, "buddy has no Manager"):
            build_mover_plan(self.ticket, self.mover, self.buddy, self.manager)

    def test_unknown_address_blocks_plan(self):
        self.ticket["company_name"] = "Unknown Company"
        self.ticket["office"] = "Unknown Office"
        with self.assertRaisesRegex(ValueError, "No safe address mapping"):
            build_mover_plan(self.ticket, self.mover, self.buddy, self.manager)

    def test_current_office_wins_when_no_new_office_is_requested(self):
        self.ticket["office"] = "Girteka HUB (GBS)"
        self.ticket["new_office"] = ""
        plan = build_mover_plan(self.ticket, self.mover, self.buddy, self.manager)
        self.assertEqual(plan["address"]["city"], "Tbilisi")
        self.assertEqual(plan["address"]["country"], "GE")

    def test_explicit_new_office_can_override_company_site(self):
        self.ticket["office"] = "Vilnius"
        self.ticket["new_office"] = "Tbilisi"
        plan = build_mover_plan(self.ticket, self.mover, self.buddy, self.manager)
        self.assertEqual(plan["address"]["city"], "Tbilisi")
        self.assertEqual(plan["address"]["country"], "GE")

    def test_company_is_fallback_when_both_office_fields_are_empty(self):
        self.ticket["office"] = ""
        self.ticket["current_office"] = ""
        self.ticket["new_office"] = ""
        plan = build_mover_plan(self.ticket, self.mover, self.buddy, self.manager)
        self.assertEqual(plan["address"]["city"], "Vilnius")
        self.assertEqual(plan["address"]["country"], "LT")


if __name__ == "__main__":
    unittest.main()
