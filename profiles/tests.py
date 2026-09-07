"""Exercise the project's allauth configuration through its real HTTP views."""

import re
from unittest.mock import patch
from urllib.parse import urlsplit

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.sites.models import Site
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import UserProfile


class AccountFlowTests(TestCase):
    password = "Separate-auth-regression-2026!"

    @classmethod
    def setUpTestData(cls):
        Site.objects.update_or_create(
            pk=settings.SITE_ID,
            defaults={"domain": "testserver", "name": "Account tests"},
        )
        cls.user = get_user_model().objects.create_user(
            username="verified_user",
            email="verified@example.invalid",
            password=cls.password,
        )
        EmailAddress.objects.create(
            user=cls.user, email=cls.user.email, primary=True, verified=True
        )

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        for operation in ("connect", "connect_ex"):
            blocker = patch(
                "socket.socket." + operation,
                side_effect=AssertionError("Authentication tests must not use the network"),
            )
            blocker.start()
            self.addCleanup(blocker.stop)

    def test_verified_user_can_log_in_by_username_and_email(self):
        for login in (self.user.username, self.user.email):
            with self.subTest(login=login):
                response = self.client.post(
                    reverse("account_login"),
                    {"login": login, "password": self.password},
                )
                self.assertRedirects(
                    response, settings.LOGIN_REDIRECT_URL, fetch_redirect_response=False
                )
                self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))
                self.client.logout()

    def test_unverified_login_email_is_blocked_even_with_verified_primary(self):
        secondary = EmailAddress.objects.create(
            user=self.user, email="unverified@example.invalid", verified=False
        )
        response = self.client.post(
            reverse("account_login"),
            {"login": secondary.email, "password": self.password},
        )
        self.assertRedirects(response, reverse("account_email_verification_sent"))
        self.assertNotIn(SESSION_KEY, self.client.session)
        secondary.refresh_from_db()
        self.assertFalse(secondary.verified)

    def test_signup_requires_email_confirmation_before_login(self):
        email = "new-account@example.invalid"
        response = self.client.post(
            reverse("account_signup"),
            {
                "username": "new_account",
                "email": email,
                "email2": email,
                "password1": self.password,
                "password2": self.password,
            },
        )
        self.assertRedirects(response, reverse("account_email_verification_sent"))
        self.assertNotIn(SESSION_KEY, self.client.session)
        address = EmailAddress.objects.get(email=email)
        self.assertFalse(address.verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [email])

        # Follow the actual emailed link and submit the project's confirmation form.
        confirmation_link = re.search(
            r"https?://[^\s]+/accounts/confirm-email/[^\s]+", mail.outbox[0].body
        )
        self.assertIsNotNone(confirmation_link)
        confirmation_path = urlsplit(confirmation_link.group()).path
        confirmation_page = self.client.get(confirmation_path)
        self.assertEqual(confirmation_page.status_code, 200)
        self.assertTemplateUsed(confirmation_page, "account/email_confirm.html")
        address.refresh_from_db()
        self.assertFalse(address.verified, "GET must not verify an email address")

        confirmation_response = self.client.post(confirmation_path)
        self.assertEqual(confirmation_response.status_code, 302)
        address.refresh_from_db()
        self.assertTrue(address.verified)

        response = self.client.post(
            reverse("account_login"), {"login": email, "password": self.password}
        )
        self.assertRedirects(
            response, settings.LOGIN_REDIRECT_URL, fetch_redirect_response=False
        )
        self.assertEqual(self.client.session[SESSION_KEY], str(address.user_id))

    def test_password_reset_hides_whether_email_exists(self):
        known = self.client.post(
            reverse("account_reset_password"), {"email": self.user.email}
        )
        self.assertRedirects(known, reverse("account_reset_password_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn("/accounts/password/reset/key/", mail.outbox[0].body)

        unknown = self.client.post(
            reverse("account_reset_password"), {"email": "missing@example.invalid"}
        )
        self.assertRedirects(unknown, reverse("account_reset_password_done"))
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.url, unknown.url)
        # Allauth sends an informational signup email to the unknown address,
        # while keeping the public response identical and issuing no reset token.
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, ["missing@example.invalid"])
        self.assertNotIn("/accounts/password/reset/key/", mail.outbox[1].body)
        self.assertFalse(
            get_user_model().objects.filter(email="missing@example.invalid").exists()
        )
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_password_reset_rate_limit_renders_429(self):
        # Exercise the default per-email limit (five requests per minute).
        url = reverse("account_reset_password")
        for attempt in range(5):
            with self.subTest(attempt=attempt):
                response = self.client.post(url, {"email": self.user.email})
                self.assertRedirects(
                    response, reverse("account_reset_password_done"),
                    fetch_redirect_response=False,
                )
        limited = self.client.post(url, {"email": self.user.email})
        self.assertEqual(limited.status_code, 429)
        self.assertTemplateUsed(limited, "429.html")
        self.assertEqual(len(mail.outbox), 5, "Rate-limited requests must not send mail")


class ProfileCountryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="country_user")

    def test_country_code_round_trips_through_profile(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.default_country = "IE"
        profile.full_clean()
        profile.save(update_fields=["default_country"])
        profile.refresh_from_db()
        self.assertEqual(str(profile.default_country), "IE")
        self.assertEqual(profile.default_country.name, "Ireland")

    def test_blank_country_remains_valid(self):
        profile = UserProfile.objects.get(user=self.user)
        profile.default_country = ""
        profile.full_clean()
        profile.save(update_fields=["default_country"])
        profile.refresh_from_db()
        self.assertEqual(str(profile.default_country), "")
        self.assertFalse(profile.default_country)
