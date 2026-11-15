"""Проверки авторизации без сети и без настоящих учётных данных."""

import base64
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx

import supabase_client as backend
from supabase_client import AuthError, AuthService, get_username, validate_password, validate_username


def response(session=True):
    return SimpleNamespace(
        user=SimpleNamespace(id="test-id", user_metadata={"username": "maxim33"}, identities=[{}]),
        session=object() if session else None,
    )


class FakeAuthError(Exception):
    def __init__(self, message, code="", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.service = AuthService(self.client)
        self.client.auth.sign_in_with_password.return_value = response()
        self.client.auth.get_user.return_value = SimpleNamespace(user=self.client.auth.sign_in_with_password.return_value.user)
        self.client.auth.sign_up.return_value = response()

    def test_username_validation_and_normalization(self):
        self.assertEqual(validate_username("  MaXim_33  "), "maxim_33")
        for invalid in ("", "ab", "x" * 21, "максим", "with space", "user@email", "a.b"):
            with self.subTest(invalid=invalid), self.assertRaises(AuthError):
                validate_username(invalid)

    def test_exact_password_length_and_no_trimming(self):
        validate_password(" ab12 ")
        for invalid in ("", "12345", "1234567"):
            with self.subTest(invalid=invalid), self.assertRaises(AuthError):
                validate_password(invalid)

    def test_invalid_input_does_not_send_requests(self):
        with self.assertRaises(AuthError):
            self.service.sign_up("ab", "123456")
        with self.assertRaises(AuthError):
            self.service.sign_in("maxim33", "123")
        self.client.auth.sign_up.assert_not_called()
        self.client.auth.sign_in_with_password.assert_not_called()

    def test_sign_in_uses_internal_address_and_server_user(self):
        user = self.service.sign_in("MAXIM33", " ab12 ")
        self.assertIs(user, self.client.auth.sign_in_with_password.return_value.user)
        self.client.auth.sign_in_with_password.assert_called_once_with({
            "email": "maxim33@gesturecontrol.local", "password": " ab12 ",
        })
        self.client.auth.get_user.assert_called_once_with()

    def test_get_user_failure_or_different_identity_prevents_login(self):
        self.client.auth.get_user.return_value = SimpleNamespace(user=None)
        with self.assertRaises(AuthError):
            self.service.sign_in("maxim33", "abc123")
        self.client.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(id="another-user"))
        with self.assertRaisesRegex(AuthError, "отличается"):
            self.service.sign_in("maxim33", "abc123")

    def test_signup_records_username_and_clears_temporary_session(self):
        user = self.service.sign_up("MAXIM33", "abc123")
        self.assertEqual(user.user_metadata["username"], "maxim33")
        self.client.auth.sign_up.assert_called_once_with({
            "email": "maxim33@gesturecontrol.local", "password": "abc123",
            "options": {"data": {"username": "maxim33"}},
        })
        self.client.auth.sign_out.assert_called_once_with({"scope": "local"})

    def test_signup_cleanup_failure_does_not_report_failed_creation(self):
        self.client.auth.sign_out.side_effect = httpx.ConnectError("offline")
        self.assertIsNotNone(self.service.sign_up("maxim33", "abc123"))

    def test_confirmation_enabled_gets_useful_message(self):
        self.client.auth.sign_up.return_value = response(session=False)
        with self.assertRaisesRegex(AuthError, "Confirm email"):
            self.service.sign_up("maxim33", "abc123")

    def test_obfuscated_duplicate_is_not_treated_as_new_user(self):
        self.client.auth.sign_up.return_value.user.identities = []
        with self.assertRaisesRegex(AuthError, "уже занят"):
            self.service.sign_up("maxim33", "abc123")

    def test_no_session_is_not_successful_login(self):
        self.client.auth.sign_in_with_password.return_value = response(session=False)
        with self.assertRaises(AuthError):
            self.service.sign_in("maxim33", "abc123")

    def test_errors_are_translated_without_exposing_server_details(self):
        cases = [
            (FakeAuthError("private@gesturecontrol.local token=secret", "invalid_credentials"), "Неверный"),
            (FakeAuthError("private@gesturecontrol.local", "user_already_exists"), "уже занят"),
            (FakeAuthError("private@gesturecontrol.local", status=429), "Слишком много"),
            (FakeAuthError("private@gesturecontrol.local", "over_request_rate_limit"), "Слишком много"),
            (FakeAuthError("private@gesturecontrol.local", "email_not_confirmed"), "Confirm email"),
            (FakeAuthError("private@gesturecontrol.local", "weak_password"), "Пароль отклонён"),
            (FakeAuthError("private@gesturecontrol.local", "signup_disabled"), "отключена"),
            (httpx.ReadTimeout("private@gesturecontrol.local token=secret"), "Нет соединения"),
            (RuntimeError("private@gesturecontrol.local token=secret"), "Не удалось"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected):
                self.client.auth.sign_in_with_password.side_effect = error
                with self.assertRaises(AuthError) as caught:
                    self.service.sign_in("maxim33", "abc123")
                self.assertIn(expected, str(caught.exception))
                self.assertNotIn("@", str(caught.exception))
                self.assertNotIn("token=secret", str(caught.exception))

    def test_metadata_fallback_never_uses_email(self):
        self.assertEqual(get_username(SimpleNamespace(user_metadata={"name": "Максим"})), "Максим")
        self.assertEqual(get_username(SimpleNamespace(user_metadata={"username": "private@gesturecontrol.local"})), "Пользователь")
        self.assertEqual(get_username(None, "maxim33"), "maxim33")
        self.assertEqual(get_username(None, "private@gesturecontrol.local"), "Пользователь")

    def test_logout_only_ends_current_session(self):
        self.service.sign_out()
        self.client.auth.sign_out.assert_called_once_with({"scope": "local"})

    def test_logout_failure_remains_retryable(self):
        self.client.auth.sign_out.side_effect = httpx.ConnectError("offline")
        with self.assertRaises(AuthError):
            self.service.sign_out()
        self.client.auth.sign_out.side_effect = None
        self.service.sign_out()
        self.assertEqual(self.client.auth.sign_out.call_count, 2)

    @patch.object(backend, "SUPABASE_URL", "")
    @patch.object(backend, "SUPABASE_KEY", "")
    def test_missing_configuration_does_not_prevent_window_startup(self):
        with patch.object(backend, "create_client") as factory:
            service = AuthService()
            self.assertFalse(service.configured)
            self.assertIn("config", service.configuration_error())
            factory.assert_not_called()
            with self.assertRaises(AuthError):
                service.sign_in("maxim33", "abc123")
            factory.assert_not_called()

    @patch.object(backend, "SUPABASE_URL", "https://project.supabase.co")
    def test_server_keys_are_rejected_before_connecting(self):
        payload = base64.urlsafe_b64encode(json.dumps({"role": "service_role"}).encode()).decode().rstrip("=")
        for key in ("sb_secret_private", f"header.{payload}.signature", "not-a-key"):
            with self.subTest(key=key), patch.object(backend, "SUPABASE_KEY", key):
                with patch.object(backend, "create_client") as factory:
                    service = AuthService()
                    with self.assertRaisesRegex(AuthError, "публичный"):
                        service.sign_up("maxim33", "abc123")
                    factory.assert_not_called()

    @patch.object(backend, "SUPABASE_URL", "https://project.supabase.co")
    def test_publishable_and_legacy_anon_keys_are_allowed(self):
        payload = base64.urlsafe_b64encode(json.dumps({"role": "anon"}).encode()).decode().rstrip("=")
        for key in ("sb_publishable_publicKey123", f"header.{payload}.signature"):
            with self.subTest(key=key), patch.object(backend, "SUPABASE_KEY", key):
                self.assertTrue(AuthService().configured)

    @patch.object(backend, "SUPABASE_URL", "https://project.supabase.co")
    @patch.object(backend, "SUPABASE_KEY", "sb_publishable_publicKey123")
    def test_signup_uses_separate_client_and_login_keeps_only_memory_session(self):
        signup_client = Mock()
        signup_client.auth.sign_up.return_value = response()
        login_client = Mock()
        login_client.auth.sign_in_with_password.return_value = response()
        login_client.auth.get_user.return_value = SimpleNamespace(user=login_client.auth.sign_in_with_password.return_value.user)
        with patch.object(backend, "create_client", side_effect=[signup_client, login_client]) as factory:
            with patch.object(backend.httpx, "Client"):
                service = AuthService()
                service.sign_up("maxim33", "abc123")
                self.assertIsNone(service._client)
                signup_client.auth.close.assert_called_once()
                service.sign_in("maxim33", "abc123")
                options = factory.call_args.kwargs["options"]
                self.assertFalse(options.persist_session)
                self.assertTrue(options.auto_refresh_token)
                self.assertFalse(factory.call_args_list[0].kwargs["options"].auto_refresh_token)
                service.sign_out()
                login_client.auth.close.assert_called_once()
                self.assertIsNone(service._client)

    @patch.object(backend, "SUPABASE_URL", "https://project.supabase.co")
    @patch.object(backend, "SUPABASE_KEY", "sb_publishable_publicKey123")
    def test_installed_sdk_signup_login_and_logout_over_mock_http(self):
        # Здесь настоящий supabase-py: подменяем только HTTP, а не методы Auth.
        requests = []
        user = {
            "id": "11111111-1111-4111-8111-111111111111", "aud": "authenticated",
            "email": "maxim33@gesturecontrol.local", "app_metadata": {},
            "user_metadata": {"username": "maxim33"}, "created_at": "2026-01-01T00:00:00Z",
        }
        expiry = int(time.time()) + 3600
        payload = base64.urlsafe_b64encode(json.dumps({"exp": expiry, "sub": user["id"]}).encode()).decode().rstrip("=")
        session = {
            "access_token": f"header.{payload}.signature", "refresh_token": "test-refresh-token",
            "token_type": "bearer", "expires_in": 3600, "expires_at": expiry, "user": user,
        }

        def respond(request):
            requests.append(request)
            if request.url.path.endswith("/logout"):
                return httpx.Response(204)
            if request.url.path.endswith("/user"):
                return httpx.Response(200, json=user)
            return httpx.Response(200, json=session)

        http_client_class = httpx.Client

        def make_transport(**kwargs):
            return http_client_class(transport=httpx.MockTransport(respond), **kwargs)

        with patch.object(backend.httpx, "Client", side_effect=make_transport):
            service = AuthService()
            self.assertEqual(service.sign_up("maxim33", "abc123").id, user["id"])
            self.assertEqual(service.sign_in("maxim33", "abc123").id, user["id"])
            service.sign_out()

        self.assertEqual([request.url.path for request in requests], [
            "/auth/v1/signup", "/auth/v1/logout", "/auth/v1/token", "/auth/v1/user", "/auth/v1/logout",
        ])
        self.assertEqual(json.loads(requests[0].content)["data"], {"username": "maxim33"})
        self.assertEqual(requests[2].url.params["grant_type"], "password")
        self.assertEqual(requests[1].url.params["scope"], "local")
        self.assertEqual(requests[4].url.params["scope"], "local")


if __name__ == "__main__":
    unittest.main()
