"""Covers the @rdc.in auto-approve behavior in OAuthManager.get_user_role,
added so new RDC staff signing in via Google OAuth don't land in the
manual-approval "pending" role that DEFAULT_USER_ROLE otherwise assigns.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_webui.utils.oauth import OAuthManager, auth_manager_config


def _manager():
    return OAuthManager(app=SimpleNamespace())


class GetUserRoleRdcAutoApproveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._original_default_role = auth_manager_config.DEFAULT_USER_ROLE
        self._original_role_mgmt = auth_manager_config.ENABLE_OAUTH_ROLE_MANAGEMENT
        auth_manager_config.DEFAULT_USER_ROLE = "pending"
        auth_manager_config.ENABLE_OAUTH_ROLE_MANAGEMENT = False

    def tearDown(self):
        auth_manager_config.DEFAULT_USER_ROLE = self._original_default_role
        auth_manager_config.ENABLE_OAUTH_ROLE_MANAGEMENT = self._original_role_mgmt

    async def test_new_rdc_in_user_skips_pending(self):
        manager = _manager()
        with patch("open_webui.utils.oauth.Users.get_num_users", AsyncMock(return_value=5)):
            role = await manager.get_user_role(None, {"email": "someone@rdc.in"})
        self.assertEqual(role, "user")

    async def test_new_non_rdc_user_still_gets_default_pending(self):
        manager = _manager()
        with patch("open_webui.utils.oauth.Users.get_num_users", AsyncMock(return_value=5)):
            role = await manager.get_user_role(None, {"email": "someone@gmail.com"})
        self.assertEqual(role, "pending")

    async def test_existing_pending_rdc_in_user_gets_promoted(self):
        manager = _manager()
        existing_user = SimpleNamespace(role="pending")
        with patch("open_webui.utils.oauth.Users.get_num_users", AsyncMock(return_value=5)):
            role = await manager.get_user_role(existing_user, {"email": "someone@rdc.in"})
        self.assertEqual(role, "user")

    async def test_existing_non_pending_rdc_in_user_keeps_role(self):
        manager = _manager()
        existing_user = SimpleNamespace(role="admin")
        with patch("open_webui.utils.oauth.Users.get_num_users", AsyncMock(return_value=5)):
            role = await manager.get_user_role(existing_user, {"email": "someone@rdc.in"})
        self.assertEqual(role, "admin")

    async def test_existing_pending_non_rdc_user_stays_pending(self):
        manager = _manager()
        existing_user = SimpleNamespace(role="pending")
        with patch("open_webui.utils.oauth.Users.get_num_users", AsyncMock(return_value=5)):
            role = await manager.get_user_role(existing_user, {"email": "someone@gmail.com"})
        self.assertEqual(role, "pending")

    async def test_case_insensitive_domain_match(self):
        manager = _manager()
        with patch("open_webui.utils.oauth.Users.get_num_users", AsyncMock(return_value=5)):
            role = await manager.get_user_role(None, {"email": "Someone@RDC.IN"})
        self.assertEqual(role, "user")


if __name__ == "__main__":
    unittest.main()
