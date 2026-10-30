"""Reads a public (or token-accessible) GitHub repository into a text snapshot for AI review.

Only github.com/<owner>/<repo> addresses are accepted and only the configured API host is contacted,
so a project URL can never make the server fetch arbitrary addresses.
"""
import base64
from django.utils.translation import gettext as _
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

DEFAULT_API_URL = "https://api.github.com"
DEFAULT_MAX_CHARS = 24000
REQUEST_TIMEOUT_SECONDS = 20
USER_AGENT = "idealar/1.0"

README_CHARS = 6000
TREE_MAX_PATHS = 300
MANIFEST_CHARS = 1500
SOURCE_FILE_CHARS = 2000
MAX_SOURCE_FILES = 6
MAX_FILE_BYTES = 40_000
MAX_COMMITS = 30

REPO_URL_PATTERN = re.compile(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
MANIFEST_NAMES = (
    "package.json", "requirements.txt", "pyproject.toml", "pom.xml", "build.gradle", "go.mod",
    "Cargo.toml", "composer.json", "Gemfile", "Dockerfile", "docker-compose.yml", "compose.yaml",
)
IGNORED_DIR_NAMES = frozenset({"node_modules", "vendor", "dist", "build", ".git", "__pycache__", "venv", ".venv", "target"})
IGNORED_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".pdf", ".zip", ".lock",
    ".min.js", ".map", ".mp4", ".webp",
)
KEY_FILE_PATTERN = re.compile(
    r"(^|/)(main|app|index|server|urls|routes|router|models|views|schema|api)\.[A-Za-z]+$", re.IGNORECASE
)


class GitHubError(Exception):
    """A problem reading the repository; the message is safe to show to the user."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RepoRef:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass
class RepoSnapshot:
    text: str
    files_read: list[str] = field(default_factory=list)


def parse_repo_url(url: str) -> RepoRef:
    match = REPO_URL_PATTERN.match(url.strip())
    if not match:
        raise GitHubError(_("GitHub adresi https://github.com/sahip/depo biçiminde olmalı."))
    return RepoRef(owner=match.group(1), name=match.group(2))


class GitHubClient:
    def __init__(self, api_url: str = DEFAULT_API_URL, token: str = "", timeout: float = REQUEST_TIMEOUT_SECONDS):
        self._api_url = api_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    def get_json(self, path: str):
        request = urllib.request.Request(f"{self._api_url}{path}", headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise GitHubError(self._message_for_status(error), status=error.code) from error
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise GitHubError(_("GitHub'a ulaşılamadı: {error}").format(error=error)) from error

    def _headers(self) -> dict:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _message_for_status(self, error: urllib.error.HTTPError) -> str:
        if error.code == 404:
            hint = "" if self._token else " " + _("Özel depo ise .env'ye GITHUB_TOKEN eklemelisin.")
            return _("Depo bulunamadı.") + hint
        if error.code in (401, 403):
            return _("GitHub erişimi reddetti (istek limiti dolmuş ya da GITHUB_TOKEN geçersiz olabilir).")
        return _("GitHub hata verdi (HTTP {code}).").format(code=error.code)


def _decode_content(payload: dict, limit: int) -> str:
    if payload.get("encoding") != "base64":
        return ""
    raw = base64.b64decode(payload.get("content", ""))
    return raw.decode("utf-8", errors="replace")[:limit]


def _is_readable_path(path: str) -> bool:
    directories = path.split("/")[:-1]
    return not IGNORED_DIR_NAMES.intersection(directories) and not path.endswith(IGNORED_SUFFIXES)


def _tree_files(tree: dict) -> list[dict]:
    entries = [e for e in tree.get("tree", []) if e.get("type") == "blob" and _is_readable_path(e["path"])]
    return sorted(entries, key=lambda e: (e["path"].count("/"), e["path"]))


def _pick_manifests(files: list[dict]) -> list[str]:
    return [e["path"] for e in files if e["path"].count("/") <= 1 and e["path"].rsplit("/", 1)[-1] in MANIFEST_NAMES]


def _pick_key_sources(files: list[dict]) -> list[str]:
    candidates = [e["path"] for e in files if KEY_FILE_PATTERN.search(e["path"]) and e.get("size", 0) <= MAX_FILE_BYTES]
    return candidates[:MAX_SOURCE_FILES]


class _Budget:
    """Appends text sections to the snapshot until the character budget (separators included) is used up."""

    SEPARATOR = "\n\n"

    def __init__(self, max_chars: int):
        self._remaining = max_chars
        self._sections: list[str] = []

    def add(self, title: str, body: str) -> None:
        separator = self.SEPARATOR if self._sections else ""
        room = self._remaining - len(separator)
        if not body.strip() or room <= 0:
            return
        section = f"## {title}\n{body.strip()}"[:room]
        self._remaining -= len(separator) + len(section)
        self._sections.append(section)

    @property
    def text(self) -> str:
        return self.SEPARATOR.join(self._sections)


def _header(meta: dict) -> str:
    topics = ", ".join(meta.get("topics") or [])
    return (
        f"name: {meta.get('full_name')}\ndescription: {meta.get('description') or '-'}\n"
        f"main language: {meta.get('language') or '-'}\ntopics: {topics or '-'}\n"
        f"last push: {meta.get('pushed_at')}\ndefault branch: {meta.get('default_branch')}"
    )


def _commit_lines(commits: list) -> str:
    firsts = (c.get("commit", {}).get("message", "").splitlines()[:1] for c in commits[:MAX_COMMITS])
    return "\n".join(f"- {line[0]}" for line in firsts if line)


def build_snapshot(client: GitHubClient, ref: RepoRef, max_chars: int = DEFAULT_MAX_CHARS) -> RepoSnapshot:
    repo_path = f"/repos/{urllib.parse.quote(ref.owner)}/{urllib.parse.quote(ref.name)}"
    meta = client.get_json(repo_path)
    branch = meta.get("default_branch", "HEAD")
    tree = client.get_json(f"{repo_path}/git/trees/{urllib.parse.quote(branch)}?recursive=1")
    files = _tree_files(tree)

    budget, files_read = _Budget(max_chars), []
    budget.add("Repository", _header(meta))
    budget.add("README", _optional_readme(client, repo_path))
    budget.add("File tree", "\n".join(e["path"] for e in files[:TREE_MAX_PATHS]))
    for path, limit in [(p, MANIFEST_CHARS) for p in _pick_manifests(files)] + [(p, SOURCE_FILE_CHARS) for p in _pick_key_sources(files)]:
        content = _read_file(client, repo_path, path, limit)
        if content:
            budget.add(f"File: {path}", content)
            files_read.append(path)
    budget.add("Recent commits", _commit_lines(client.get_json(f"{repo_path}/commits?per_page={MAX_COMMITS}")))
    return RepoSnapshot(text=budget.text, files_read=files_read)


def _optional_readme(client: GitHubClient, repo_path: str) -> str:
    try:
        return _decode_content(client.get_json(f"{repo_path}/readme"), README_CHARS)
    except GitHubError as error:
        if error.status == 404:
            return ""  # many repos have no README; that is information, not a failure
        raise


def _read_file(client: GitHubClient, repo_path: str, path: str, limit: int) -> str:
    quoted = urllib.parse.quote(path)
    return _decode_content(client.get_json(f"{repo_path}/contents/{quoted}"), limit)
