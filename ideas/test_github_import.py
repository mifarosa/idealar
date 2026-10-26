import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ideas import github_import
from ideas.github_repo import GitHubClient, GitHubError
from ideas.models import Project
from ideas.test_github_repo import FakeGitHub

USER_PATH = "/users/octo/repos?type=owner&sort=pushed&per_page=100&page={page}"
TOKEN_PATH = "/user/repos?affiliation=owner&sort=pushed&per_page=100&page={page}"


def repo_item(name, **overrides):
    item = {
        "name": name, "full_name": f"octo/{name}", "description": f"{name} description", "html_url": f"https://github.com/octo/{name}",
        "language": "Python", "pushed_at": "2026-10-01T10:00:00Z", "fork": False, "archived": False, "private": False,
    }
    item.update(overrides)
    return item


def make_user(name="owner"):
    return get_user_model().objects.create_user(name, password="pw-for-tests-123")


class ListReposTests(TestCase):
    def client_for(self, routes):
        server = FakeGitHub(routes)
        self.addCleanup(server.close)
        self.server = server
        return GitHubClient(api_url=server.url, timeout=5)

    def test_public_repos_of_a_username_are_parsed(self):
        client = self.client_for({USER_PATH.format(page=1): (200, [repo_item("habits", fork=True, language=None, description=None)])})

        repos = github_import.list_repos(client, "octo", has_token=False)

        self.assertEqual(len(repos), 1)
        repo = repos[0]
        self.assertEqual((repo.name, repo.full_name, repo.url, repo.fork, repo.language, repo.description, repo.pushed_at), ("habits", "octo/habits", "https://github.com/octo/habits", True, "", "", "2026-10-01"))

    def test_follows_pagination_until_a_short_page(self):
        first_page = [repo_item(f"repo{n}") for n in range(100)]
        client = self.client_for({USER_PATH.format(page=1): (200, first_page), USER_PATH.format(page=2): (200, [repo_item("last")])})

        repos = github_import.list_repos(client, "octo", has_token=False)

        self.assertEqual((len(repos), repos[-1].name), (101, "last"))

    def test_empty_username_with_a_token_lists_the_token_owners_repos_including_private(self):
        client = self.client_for({TOKEN_PATH.format(page=1): (200, [repo_item("secret", private=True)])})

        repos = github_import.list_repos(client, "", has_token=True)

        self.assertTrue(repos[0].private)

    def test_empty_username_without_a_token_is_an_error(self):
        with self.assertRaises(GitHubError):
            github_import.list_repos(self.client_for({}), "", has_token=False)

    def test_malicious_or_malformed_usernames_never_reach_github(self):
        client = self.client_for({})
        for name in ("../etc", "a b", "octo/habits", "-bad", "bad-", "x" * 40, "oc?to"):
            with self.assertRaises(GitHubError, msg=name):
                github_import.list_repos(client, name, has_token=False)
        self.assertEqual(self.server.requests, [])

    def test_unknown_user_gives_a_friendly_error(self):
        with self.assertRaises(GitHubError) as caught:
            github_import.list_repos(self.client_for({}), "octo", has_token=False)

        self.assertIn("bulunamadı", str(caught.exception))


class ImportReposTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def repo(self, name):
        return github_import._to_repo(repo_item(name))

    def test_creates_projects_with_name_description_and_url(self):
        added = github_import.import_repos(self.user, [self.repo("habits")])

        project = Project.objects.get()
        self.assertEqual((added, project.owner, project.name, project.description, project.github_url), (1, self.user, "habits", "habits description", "https://github.com/octo/habits"))

    def test_already_imported_repos_are_skipped_even_with_different_url_spelling(self):
        Project.objects.create(owner=self.user, name="old", github_url="https://github.com/Octo/Habits.git/")

        added = github_import.import_repos(self.user, [self.repo("habits"), self.repo("other")])

        self.assertEqual((added, Project.objects.count()), (1, 2))

    def test_importing_twice_does_not_duplicate(self):
        github_import.import_repos(self.user, [self.repo("habits")])

        self.assertEqual(github_import.import_repos(self.user, [self.repo("habits")]), 0)

    def test_other_users_projects_do_not_count_as_imported(self):
        Project.objects.create(owner=make_user("other"), name="theirs", github_url="https://github.com/octo/habits")

        self.assertEqual(github_import.import_repos(self.user, [self.repo("habits")]), 1)


class ImportViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.url = reverse("ideas:project-import")
        self.server = FakeGitHub(
            {USER_PATH.format(page=1): (200, [repo_item("habits"), repo_item("forked", fork=True), repo_item("old", archived=True), repo_item("done")])}
        )
        self.addCleanup(self.server.close)
        patcher = patch("ideas.project_review.build_github_client", return_value=GitHubClient(api_url=self.server.url, timeout=5))
        patcher.start()
        self.addCleanup(patcher.stop)
        Project.objects.create(owner=self.user, name="done", github_url="https://github.com/octo/done")

    def test_form_page_alone_does_not_call_github(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.server.requests, [])

    def test_form_is_prefilled_from_the_environment(self):
        with patch.dict(os.environ, {"GITHUB_USERNAME": "octo"}):
            self.assertContains(self.client.get(self.url), 'value="octo"')

    def test_listing_preselects_only_normal_new_repos(self):
        response = self.client.get(self.url, {"kullanici": "octo"})

        rows = {row["repo"].name: row for row in response.context["rows"]}
        self.assertEqual({name: row["checked"] for name, row in rows.items()}, {"habits": True, "forked": False, "old": False, "done": False})
        self.assertTrue(rows["done"]["already"])
        for label in ("zaten ekli", "fork", "arşiv"):
            self.assertContains(response, label)

    def test_posting_imports_only_the_chosen_repos(self):
        response = self.client.post(self.url, {"kullanici": "octo", "repo": ["octo/habits", "octo/forked"]})

        self.assertRedirects(response, reverse("ideas:project-list"))
        self.assertEqual(sorted(Project.objects.filter(owner=self.user).values_list("name", flat=True)), ["done", "forked", "habits"])

    def test_names_that_github_did_not_just_list_are_ignored(self):
        self.client.post(self.url, {"kullanici": "octo", "repo": ["octo/habits", "evil/malware", "octo/not-listed"]})

        self.assertEqual(sorted(Project.objects.values_list("name", flat=True)), ["done", "habits"])

    def test_github_error_is_shown_without_importing(self):
        self.server.routes.clear()

        response = self.client.get(self.url, {"kullanici": "octo"}, follow=True)

        self.assertContains(response, "Depo bulunamadı")

    def test_empty_username_without_token_explains_what_to_do(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": ""}):
            response = self.client.get(self.url, {"kullanici": ""})

        self.assertContains(response, "Kullanıcı adı yaz")

    def test_imports_belong_to_the_signed_in_user_only(self):
        self.client.post(self.url, {"kullanici": "octo", "repo": ["octo/habits"]})

        self.assertEqual(Project.objects.filter(name="habits").get().owner, self.user)

    def test_login_is_required_and_project_list_links_to_the_import(self):
        self.assertContains(self.client.get(reverse("ideas:project-list")), self.url)
        self.client.logout()

        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.url, {"kullanici": "octo", "repo": ["octo/habits"]}).status_code, 302)
