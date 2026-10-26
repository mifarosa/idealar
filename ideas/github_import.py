"""Lists a GitHub account's repositories so they can be imported as projects (nothing is imported automatically)."""
import re
from dataclasses import dataclass

from .github_repo import GitHubClient, GitHubError
from .models import Project

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")  # GitHub allows 39 characters
PAGE_SIZE = 100
MAX_PAGES = 5  # up to 500 repositories


@dataclass(frozen=True)
class RemoteRepo:
    name: str
    full_name: str
    description: str
    url: str
    language: str
    pushed_at: str
    fork: bool
    archived: bool
    private: bool


def validate_username(username: str) -> str:
    username = username.strip()
    if username and not USERNAME_PATTERN.match(username):
        raise GitHubError("GitHub kullanıcı adı geçersiz.")
    return username


def _page_path(username: str, page: int) -> str:
    if username:
        return f"/users/{username}/repos?type=owner&sort=pushed&per_page={PAGE_SIZE}&page={page}"
    return f"/user/repos?affiliation=owner&sort=pushed&per_page={PAGE_SIZE}&page={page}"


def _to_repo(item: dict) -> RemoteRepo:
    return RemoteRepo(
        name=item["name"],
        full_name=item["full_name"],
        description=item.get("description") or "",
        url=item["html_url"],
        language=item.get("language") or "",
        pushed_at=(item.get("pushed_at") or "")[:10],
        fork=bool(item.get("fork")),
        archived=bool(item.get("archived")),
        private=bool(item.get("private")),
    )


def list_repos(client: GitHubClient, username: str, has_token: bool) -> list[RemoteRepo]:
    """Public repositories of `username`; with an empty username and a token, the token owner's (incl. private)."""
    username = validate_username(username)
    if not username and not has_token:
        raise GitHubError("Kullanıcı adı yaz (ya da .env'ye GITHUB_TOKEN ekle).")
    repos: list[RemoteRepo] = []
    for page in range(1, MAX_PAGES + 1):
        items = client.get_json(_page_path(username, page))
        repos.extend(_to_repo(item) for item in items)
        if len(items) < PAGE_SIZE:
            break
    return repos


def normalize_url(url: str) -> str:
    return url.strip().lower().removesuffix("/").removesuffix(".git")


def already_imported_urls(owner) -> set[str]:
    return {normalize_url(url) for url in Project.objects.filter(owner=owner).values_list("github_url", flat=True) if url}


def import_repos(owner, repos: list[RemoteRepo]) -> int:
    """Creates a project per repository that is not already a project of `owner`; returns how many were added."""
    existing = already_imported_urls(owner)
    created = 0
    for repo in repos:
        if normalize_url(repo.url) in existing:
            continue
        Project.objects.create(owner=owner, name=repo.name, description=repo.description, github_url=repo.url)
        existing.add(normalize_url(repo.url))
        created += 1
    return created
