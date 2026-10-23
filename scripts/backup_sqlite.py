"""Daily SQLite backup with retention.

Usage: python scripts/backup_sqlite.py
Reads DATABASE_URL, BACKUP_DIR and BACKUP_KEEP_DAYS from the environment / .env.
Uses SQLite's online backup API, so it is safe while the server is running.
"""
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_PREFIX = "idealar-"
BACKUP_SUFFIX = ".sqlite3"


class BackupError(Exception):
    pass


def sqlite_path_from_url(database_url: str) -> Path:
    config = dj_database_url.parse(database_url)
    if "sqlite" not in config["ENGINE"]:
        raise BackupError("Only SQLite databases are supported by this script; use pg_dump for Postgres.")
    path = Path(config["NAME"])
    if not path.is_file():
        raise BackupError(f"Database file not found: {path}")
    return path


def backup_file_name(day: date) -> str:
    return f"{BACKUP_PREFIX}{day.isoformat()}{BACKUP_SUFFIX}"


def copy_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    # Rename last so a half-written backup never looks like a valid one.
    temporary.replace(destination)


def _backup_date(path: Path) -> date | None:
    stamp = path.name.removeprefix(BACKUP_PREFIX).removesuffix(BACKUP_SUFFIX)
    try:
        return date.fromisoformat(stamp)
    except ValueError:
        return None


def prune_old_backups(backup_dir: Path, keep_days: int, today: date) -> list[Path]:
    cutoff = today - timedelta(days=keep_days)
    removed = []
    for path in backup_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"):
        backup_day = _backup_date(path)
        if backup_day is not None and backup_day < cutoff:
            path.unlink()
            removed.append(path)
    return removed


def run_backup(database_url: str, backup_dir: Path, keep_days: int, today: date) -> Path:
    source = sqlite_path_from_url(database_url)
    destination = backup_dir / backup_file_name(today)
    copy_database(source, destination)
    prune_old_backups(backup_dir, keep_days, today)
    return destination


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    database_url = os.environ.get("DATABASE_URL", f"sqlite:///{PROJECT_ROOT / 'db.sqlite3'}")
    backup_dir = PROJECT_ROOT / os.environ.get("BACKUP_DIR", "backups")
    keep_days = int(os.environ.get("BACKUP_KEEP_DAYS", "30"))
    try:
        destination = run_backup(database_url, backup_dir, keep_days, date.today())
    except BackupError as error:
        print(f"Backup failed: {error}", file=sys.stderr)
        return 1
    print(f"Backup written: {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
