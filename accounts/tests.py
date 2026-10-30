from unittest.mock import MagicMock, patch

from authlib.integrations.base_client.errors import OAuthError
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.http import HttpResponseRedirect
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import GoogleAccount

GOOGLE = {"GOOGLE_CLIENT_ID": "id", "GOOGLE_CLIENT_SECRET": "secret"}


def identity(sub="g-1", email="faruk@example.com", verified=True, **extra):
    return {"sub": sub, "email": email, "email_verified": verified, **extra}


def fake_google(userinfo=None, error=None):
    """Stands in for the Authlib client so no request ever leaves the test process."""
    client = MagicMock()
    client.authorize_redirect.return_value = HttpResponseRedirect("https://accounts.google.com/o/oauth2/auth")
    if error:
        client.authorize_access_token.side_effect = error
    else:
        client.authorize_access_token.return_value = {"userinfo": userinfo}
    return patch("accounts.google.oauth_client", return_value=client), client


@override_settings(**GOOGLE)
class LoginPageTests(TestCase):
    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(reverse("ideas:list"))

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('ideas:list')}")

    def test_login_page_offers_google_and_no_password_form(self):
        page = self.client.get(reverse("accounts:login"))

        self.assertContains(page, "Google ile giriş yap")
        self.assertNotContains(page, 'type="password"')

    @override_settings(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_SECRET="")
    def test_page_explains_when_google_is_not_configured(self):
        self.assertContains(self.client.get(reverse("accounts:login")), "henüz ayarlanmadı")
        self.assertEqual(self.client.get(reverse("accounts:google-start"), follow=True).status_code, 200)

    def test_password_posts_to_login_are_not_accepted(self):
        get_user_model().objects.create_user("faruk", password="correct-horse-battery")

        self.client.post(reverse("accounts:login"), {"username": "faruk", "password": "correct-horse-battery"})

        self.assertNotIn("_auth_user_id", self.client.session)

    def test_signed_in_user_skips_the_login_page(self):
        self.client.force_login(get_user_model().objects.create_user("faruk"))

        self.assertRedirects(self.client.get(reverse("accounts:login")), reverse("ideas:list"))

    def test_logout_requires_post_and_ends_session(self):
        self.client.force_login(get_user_model().objects.create_user("faruk"))

        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))

        self.assertNotIn("_auth_user_id", self.client.session)

    def test_passwords_use_argon2_and_session_cookie_is_http_only(self):
        user = get_user_model().objects.create_user("faruk", password="correct-horse-battery")

        self.assertTrue(user.password.startswith("argon2"))
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)


@override_settings(**GOOGLE)
class GoogleFlowTests(TestCase):
    def callback(self, userinfo=None, error=None):
        patcher, client = fake_google(userinfo, error)
        with patcher:
            return self.client.get(reverse("accounts:google-callback")), client

    def test_start_redirects_to_google_with_our_callback_address(self):
        patcher, client = fake_google()
        with patcher:
            self.client.get(reverse("accounts:google-start"))

        redirect_uri = client.authorize_redirect.call_args.args[1]
        self.assertTrue(redirect_uri.endswith("/accounts/google/callback/"))

    def test_existing_user_is_matched_by_email_and_linked_to_the_google_id(self):
        user = get_user_model().objects.create_user("faruk", email="Faruk@Example.com")

        response, _ = self.callback(identity(email="faruk@example.com"))

        self.assertRedirects(response, reverse("ideas:list"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertEqual(user.google_account.sub, "g-1")

    def test_known_google_id_signs_in_even_after_the_email_changed(self):
        user = get_user_model().objects.create_user("faruk", email="old@example.com")
        GoogleAccount.objects.create(user=user, sub="g-1")

        self.callback(identity(email="new@example.com"))

        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    @override_settings(GOOGLE_SIGNUP=False)
    def test_unknown_account_is_refused_while_signup_is_closed(self):
        response, _ = self.callback(identity(email="stranger@example.com"))

        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(get_user_model().objects.exists())

    @override_settings(GOOGLE_SIGNUP=True)
    def test_unknown_account_creates_a_user_when_signup_is_open(self):
        self.callback(identity(sub="g-9", email="new.person@example.com", given_name="Ayşe"))

        user = get_user_model().objects.get()
        self.assertEqual((user.username, user.email, user.first_name), ("new.person", "new.person@example.com", "Ayşe"))
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    @override_settings(GOOGLE_SIGNUP=True)
    def test_usernames_stay_unique(self):
        get_user_model().objects.create_user("ayse")

        self.callback(identity(sub="g-2", email="ayse@example.com"))

        self.assertTrue(get_user_model().objects.filter(username="ayse2", email="ayse@example.com").exists())

    @override_settings(GOOGLE_SIGNUP=True)
    def test_unverified_email_never_signs_in(self):
        get_user_model().objects.create_user("faruk", email="faruk@example.com")

        response, _ = self.callback(identity(verified=False))

        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_is_refused(self):
        get_user_model().objects.create_user("faruk", email="faruk@example.com", is_active=False)

        self.callback(identity())

        self.assertNotIn("_auth_user_id", self.client.session)

    def test_ambiguous_email_is_refused(self):
        for name in ("a", "b"):
            get_user_model().objects.create_user(name, email="faruk@example.com")

        self.callback(identity())

        self.assertNotIn("_auth_user_id", self.client.session)

    def test_failed_google_exchange_shows_an_error_and_stays_anonymous(self):
        with self.assertLogs("accounts.views", level="WARNING"):
            response, _ = self.callback(error=OAuthError(error="access_denied"))

        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_next_address_is_kept_but_only_for_our_own_host(self):
        get_user_model().objects.create_user("faruk", email="faruk@example.com")
        patcher, _ = fake_google(identity())
        with patcher:
            self.client.get(reverse("accounts:google-start"), {"next": "/projects/"})
            response = self.client.get(reverse("accounts:google-callback"))
        self.assertRedirects(response, "/projects/", fetch_redirect_response=False)

        self.client.logout()
        patcher, _ = fake_google(identity())
        with patcher:
            self.client.get(reverse("accounts:google-start"), {"next": "https://evil.example/"})
            response = self.client.get(reverse("accounts:google-callback"))
        self.assertRedirects(response, reverse("ideas:list"), fetch_redirect_response=False)


class LinkGoogleCommandTests(TestCase):
    def test_sets_the_email_used_for_matching(self):
        user = get_user_model().objects.create_user("faruk")

        call_command("link_google", "faruk", "Faruk@Example.com")

        user.refresh_from_db()
        self.assertEqual(user.email, "faruk@example.com")


@override_settings(**GOOGLE)
class LandingTests(TestCase):
    def test_timeline_is_listed_newest_first_and_shown_on_the_login_page(self):
        from accounts.timeline import TIMELINE

        days = [item.day for item in TIMELINE]
        self.assertEqual(days, sorted(days, reverse=True))  # new features are added at the top
        page = self.client.get(reverse("accounts:login"))
        for item in TIMELINE:
            self.assertContains(page, item.title)

    def test_only_recent_entries_get_the_new_badge(self):
        from datetime import date, timedelta

        from accounts.timeline import Feature

        self.assertTrue(Feature(date.today(), "a", "b").is_new)
        self.assertFalse(Feature(date.today() - timedelta(days=60), "a", "b").is_new)

    def test_login_card_and_pitch_are_both_on_the_page(self):
        page = self.client.get(reverse("accounts:login"))

        self.assertContains(page, "Google ile giriş yap")
        self.assertContains(page, "Neler var, neler geliyor")


@override_settings(**GOOGLE)
class LandingPreviewTests(TestCase):
    def test_the_page_shows_only_the_newest_entries_and_the_rest_wait_in_a_dialog(self):
        from accounts.timeline import TIMELINE, TIMELINE_PREVIEW

        page = self.client.get(reverse("accounts:login"))
        html = page.content.decode()
        before_dialog, _, dialog = html.partition('<dialog class="dialog"')

        for item in TIMELINE[:TIMELINE_PREVIEW]:
            self.assertIn(f"<h3>{item.title}", before_dialog)
        for item in TIMELINE[TIMELINE_PREVIEW:]:
            self.assertNotIn(f"<h3>{item.title}", before_dialog)
            self.assertIn(f"<h3>{item.title}", dialog)  # but the full list is one click away
        self.assertContains(page, f"Tümünü gör (+{len(TIMELINE) - TIMELINE_PREVIEW})")
        self.assertContains(page, 'data-open-dialog="timeline-dialog"')

    def test_no_button_when_everything_already_fits(self):
        with patch("accounts.views.TIMELINE_PREVIEW", 999):
            page = self.client.get(reverse("accounts:login"))

        self.assertNotContains(page, "data-open-dialog")


@override_settings(**GOOGLE)
class LinkPreviewTests(TestCase):
    def meta(self, page, name):
        import re

        match = re.search(rf'<meta (?:property|name)="{re.escape(name)}" content="([^"]*)"', page.content.decode())
        return match.group(1) if match else None

    @override_settings(ALLOWED_HOSTS=["idealar.example"])
    def test_shared_links_carry_a_title_description_and_an_absolute_image(self):
        page = self.client.get(reverse("accounts:login"), headers={"host": "idealar.example"}, secure=True)

        self.assertEqual(self.meta(page, "og:title"), "Idealar · fikirlerini yapay zekâyla düşün")
        self.assertEqual(self.meta(page, "og:image"), "https://idealar.example/static/img/og-image-tr.png")
        self.assertEqual(self.meta(page, "og:url"), "https://idealar.example/")
        self.assertEqual(self.meta(page, "twitter:card"), "summary_large_image")
        self.assertEqual((self.meta(page, "og:image:width"), self.meta(page, "og:image:height")), ("1200", "630"))
        self.assertIn("yapay zekâ", self.meta(page, "og:description"))

    def test_the_preview_follows_the_language(self):
        self.client.post(reverse("set_language"), {"language": "en"})

        page = self.client.get(reverse("accounts:login"))

        self.assertTrue(self.meta(page, "og:image").endswith("/static/img/og-image-en.png"))
        self.assertEqual(self.meta(page, "og:locale"), "en_US")
        self.assertIn("idea notebook", self.meta(page, "og:image:alt").lower() + " idea notebook")  # alt text is translated, not Turkish
        self.assertNotIn("yapay", self.meta(page, "og:description"))

    def test_the_preview_images_exist_and_are_1200_by_630(self):
        import struct
        from pathlib import Path

        for lang in ("tr", "en"):
            data = (Path(settings.BASE_DIR) / "static" / "img" / f"og-image-{lang}.png").read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (1200, 630), lang)

    def test_private_pages_are_not_indexed_but_the_landing_page_is(self):
        self.assertNotContains(self.client.get(reverse("accounts:login")), 'name="robots"')
        self.client.force_login(get_user_model().objects.create_user("faruk"))

        self.assertContains(self.client.get(reverse("ideas:list")), '<meta name="robots" content="noindex">')
