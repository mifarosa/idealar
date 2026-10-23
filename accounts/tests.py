from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

PASSWORD = "correct-horse-battery"


class LoginTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("faruk", password=PASSWORD)

    def test_login_with_valid_credentials_redirects_to_ideas(self):
        response = self.client.post(reverse("accounts:login"), {"username": "faruk", "password": PASSWORD})

        self.assertRedirects(response, reverse("ideas:list"))

    def test_login_with_wrong_password_shows_error_and_stays_anonymous(self):
        response = self.client.post(reverse("accounts:login"), {"username": "faruk", "password": "wrong"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(reverse("ideas:list"))

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('ideas:list')}")

    def test_logout_requires_post_and_ends_session(self):
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))

        self.assertNotIn("_auth_user_id", self.client.session)

    def test_passwords_are_hashed_with_argon2(self):
        self.assertTrue(self.user.password.startswith("argon2"))

    def test_session_cookie_is_http_only(self):
        self.client.post(reverse("accounts:login"), {"username": "faruk", "password": PASSWORD})

        self.assertTrue(self.client.cookies["sessionid"]["httponly"])
