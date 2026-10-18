"""Read snapshots must be fresh, read-only, isolated and exception-safe."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from game.read_queries import read_connection


class ReadConnectionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'read.db'
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute('CREATE TABLE sample(value INTEGER)');c.execute('INSERT INTO sample VALUES(1)')

    def test_owned_connection_rejects_writes_and_closes_on_error(self):
        with self.assertRaises(sqlite3.OperationalError):
            with read_connection(self.path) as c:
                self.assertEqual(c.execute('SELECT value FROM sample').fetchone(),(1,))
                c.execute('UPDATE sample SET value=2')
        with self.assertRaises(sqlite3.ProgrammingError):c.execute('SELECT 1')
        with read_connection(self.path) as fresh:
            self.assertEqual(fresh.execute('SELECT value FROM sample').fetchone(),(1,))

    def test_borrowed_connection_restores_row_factory_without_closing_or_committing(self):
        with closing(sqlite3.connect(self.path)) as c:
            c.row_factory=sqlite3.Row;c.execute('BEGIN')
            with self.assertRaises(ValueError):
                with read_connection(self.path,c) as borrowed:
                    self.assertIs(borrowed,c)
                    self.assertEqual(c.execute('SELECT value FROM sample').fetchone(),(1,))
                    with read_connection(self.path,c,rows=True):
                        self.assertEqual(c.execute('SELECT value FROM sample').fetchone()['value'],1)
                    raise ValueError('reader failure')
            self.assertIs(c.row_factory,sqlite3.Row)
            self.assertTrue(c.in_transaction)
            self.assertEqual(c.execute('SELECT value FROM sample').fetchone()['value'],1)

    def test_next_snapshot_sees_committed_changes(self):
        with read_connection(self.path) as c:self.assertEqual(c.execute('SELECT value FROM sample').fetchone()[0],1)
        with closing(sqlite3.connect(self.path)) as writer,writer:writer.execute('UPDATE sample SET value=2')
        with read_connection(self.path) as c:self.assertEqual(c.execute('SELECT value FROM sample').fetchone()[0],2)

    def test_missing_save_is_not_created(self):
        missing=self.path.with_name('missing.db')
        with self.assertRaises(sqlite3.OperationalError):
            with read_connection(missing):self.fail('Missing save was opened')
        self.assertFalse(missing.exists())

    def test_one_snapshot_stays_consistent_when_another_connection_commits(self):
        # WAL is used only in this disposable test to permit a concurrent writer.
        with closing(sqlite3.connect(self.path)) as c:c.execute('PRAGMA journal_mode=WAL')
        with read_connection(self.path) as reader:
            self.assertEqual(reader.execute('SELECT value FROM sample').fetchone()[0],1)
            with closing(sqlite3.connect(self.path)) as writer,writer:
                writer.execute('UPDATE sample SET value=2')
            self.assertEqual(reader.execute('SELECT value FROM sample').fetchone()[0],1)
        with read_connection(self.path) as reader:
            self.assertEqual(reader.execute('SELECT value FROM sample').fetchone()[0],2)
