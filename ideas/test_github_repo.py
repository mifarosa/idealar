import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from django.test import SimpleTestCase

from ideas.github_repo import GitHubClient, GitHubError, build_snapshot, parse_repo_url


def b64(text: str) -> dict:
    return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}


class FakeGitHub:
    """A real local HTTP server that answers GitHub-style paths from a dict of path -> (status, json)."""

    def __init__(self, routes: dict):
        self.routes, self.requests = routes, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "agent": self.headers.get("User-Agent")})
                status, body = outer.routes.get(self.path, (404, {"message": "Not Found"}))
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def log_message(self, *args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


def repo_routes(**overrides) -> dict:
    base = "/repos/octo/habits"
    routes = {
        base: (200, {"full_name": "octo/habits", "description": "Habit tracker", "language": "Python", "topics": ["health"], "pushed_at": "2026-10-01", "default_branch": "main"}),
        f"{base}/git/trees/main?recursive=1": (
            200,
            {
                "tree": [
                    {"type": "blob", "path": "README.md", "size": 10},
                    {"type": "blob", "path": "requirements.txt", "size": 10},
                    {"type": "blob", "path": "app/views.py", "size": 100},
                    {"type": "blob", "path": "app/huge_models.py", "size": 10},
                    {"type": "blob", "path": "node_modules/lib/index.js", "size": 10},
                    {"type": "blob", "path": "static/logo.png", "size": 10},
                    {"type": "tree", "path": "app"},
                ]
            },
        ),
        f"{base}/readme": (200, b64("# Habits\nTrack your habits daily.")),
        f"{base}/contents/requirements.txt": (200, b64("Django==5.2\n")),
        f"{base}/contents/app/views.py": (200, b64("def streaks(request): ...")),
        f"{base}/contents/app/huge_models.py": (200, b64("class Habit: ...")),
        f"{base}/commits?per_page=30": (200, [{"commit": {"message": "Add streak counter\n\nlong body"}}, {"commit": {"message": "Initial commit"}}]),
    }
    routes.update(overrides)
    return routes


class ParseRepoUrlTests(SimpleTestCase):
    def test_accepts_common_github_forms(self):
        for url in ("https://github.com/octo/habits", "https://github.com/octo/habits/", "https://github.com/octo/habits.git", "http://www.github.com/octo/habits", " https://github.com/octo/habits "):
            ref = parse_repo_url(url)
            self.assertEqual((ref.owner, ref.name), ("octo", "habits"))

    def test_rejects_other_hosts_extra_paths_and_junk(self):
        for url in ("https://gitlab.com/octo/habits", "https://github.com/octo", "https://github.com/octo/habits/issues", "https://github.com.evil.io/octo/habits", "https://github.com/octo/habits?x=1", "ftp://github.com/a/b", "not a url", "https://evil.io/https://github.com/a/b", ""):
            with self.assertRaises(GitHubError, msg=url):
                parse_repo_url(url)


class SnapshotTests(SimpleTestCase):
    def snapshot(self, routes=None, token="", max_chars=24000):
        server = FakeGitHub(repo_routes() if routes is None else routes)
        self.addCleanup(server.close)
        self.server = server
        client = GitHubClient(api_url=server.url, token=token, timeout=5)
        return build_snapshot(client, parse_repo_url("https://github.com/octo/habits"), max_chars)

    def test_snapshot_contains_metadata_readme_tree_manifests_sources_and_commits(self):
        snapshot = self.snapshot()

        for expected in ("octo/habits", "Habit tracker", "Track your habits daily.", "app/views.py", "Django==5.2", "def streaks", "Add streak counter", "Initial commit"):
            self.assertIn(expected, snapshot.text)
        self.assertNotIn("long body", snapshot.text)  # only the first line of each commit
        self.assertEqual(set(snapshot.files_read), {"requirements.txt", "app/views.py"})

    def test_vendored_and_binary_files_are_left_out(self):
        text = self.snapshot().text

        self.assertNotIn("node_modules", text)
        self.assertNotIn("logo.png", text)

    def test_snapshot_respects_the_character_budget(self):
        self.assertLessEqual(len(self.snapshot(max_chars=300).text), 300)

    def test_missing_readme_is_tolerated(self):
        snapshot = self.snapshot(repo_routes(**{"/repos/octo/habits/readme": (404, {})}))

        self.assertNotIn("## README", snapshot.text)
        self.assertIn("Habit tracker", snapshot.text)

    def test_unknown_repo_gives_a_friendly_message_with_token_hint(self):
        with self.assertRaises(GitHubError) as caught:
            self.snapshot({})

        self.assertIn("bulunamadı", str(caught.exception))
        self.assertIn("GITHUB_TOKEN", str(caught.exception))

    def test_rate_limit_or_bad_token_is_reported(self):
        with self.assertRaises(GitHubError) as caught:
            self.snapshot({"/repos/octo/habits": (403, {"message": "rate limit"})})

        self.assertIn("reddetti", str(caught.exception))

    def test_unreadme_error_other_than_404_is_not_swallowed(self):
        with self.assertRaises(GitHubError):
            self.snapshot(repo_routes(**{"/repos/octo/habits/readme": (500, {})}))

    def test_token_and_user_agent_are_sent_when_configured(self):
        self.snapshot(token="ghp_secret")

        for request in self.server.requests:
            self.assertEqual(request["auth"], "Bearer ghp_secret")
            self.assertEqual(request["agent"], "idealar/1.0")

    def test_no_authorization_header_without_a_token(self):
        self.snapshot()

        self.assertTrue(all(request["auth"] is None for request in self.server.requests))

    def test_unreachable_github_is_a_friendly_error(self):
        server = FakeGitHub({})
        client = GitHubClient(api_url=server.url, timeout=2)
        server.close()

        with self.assertRaises(GitHubError):
            client.get_json("/repos/a/b")
