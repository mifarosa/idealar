import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from django.test import SimpleTestCase

from scripts import backup_sqlite as backup


def _make_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE note (text TEXT)")
    connection.execute("INSERT INTO note VALUES ('hello')")
    connection.commit()
    connection.close()


class BackupTests(SimpleTestCase):
    def setUp(self):
        self.workdir = Path(tempfile.mkdtemp())
        self.database = self.workdir / "db.sqlite3"
        self.backup_dir = self.workdir / "backups"
        _make_database(self.database)

    def test_backup_contains_the_data(self):
        result = backup.run_backup(f"sqlite:///{self.database}", self.backup_dir, 30, date(2026, 1, 10))

        self.assertEqual(result.name, "idealar-2026-01-10.sqlite3")
        rows = sqlite3.connect(result).execute("SELECT text FROM note").fetchall()
        self.assertEqual(rows, [("hello",)])

    def test_old_backups_are_pruned_and_recent_ones_kept(self):
        self.backup_dir.mkdir()
        old = self.backup_dir / "idealar-2025-11-01.sqlite3"
        recent = self.backup_dir / "idealar-2026-01-05.sqlite3"
        unrelated = self.backup_dir / "notes.txt"
        for path in (old, recent, unrelated):
            path.write_text("x")

        backup.run_backup(f"sqlite:///{self.database}", self.backup_dir, 30, date(2026, 1, 10))

        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(unrelated.exists())

    def test_missing_database_is_an_error(self):
        with self.assertRaises(backup.BackupError):
            backup.sqlite_path_from_url(f"sqlite:///{self.workdir / 'nope.sqlite3'}")

    def test_non_sqlite_database_is_rejected(self):
        with self.assertRaises(backup.BackupError):
            backup.sqlite_path_from_url("postgres://u:p@localhost/db")
