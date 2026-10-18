"""Small database cases prove fixture resets preserve isolation and constraints."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from database.create_database import connect_database
from tests.fixtures import database_baseline,WorldBaseline,restore_case_baseline


class BaselineTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'fixture.db'
        with closing(sqlite3.connect(self.path)) as c,c:
            c.execute('CREATE TABLE parent (id INTEGER PRIMARY KEY,value TEXT)')
            c.execute('CREATE TABLE child (id INTEGER PRIMARY KEY,parent_id INTEGER REFERENCES parent(id))')
            c.execute("INSERT INTO parent VALUES (1,'baseline')")

    def test_repeated_resets_remove_rows_and_restore_baseline_values(self):
        with database_baseline(self.path) as restore:
            for i in range(3):
                restore()
                with closing(connect_database(self.path)) as c,c:
                    self.assertEqual(c.execute('SELECT * FROM parent').fetchall(),[(1,'baseline')])
                    self.assertEqual(c.execute('SELECT * FROM child').fetchall(),[])
                    c.execute("UPDATE parent SET value='changed'")
                    c.execute('INSERT INTO parent VALUES (2,?)',(str(i),))
                    c.execute('INSERT INTO child VALUES (1,2)')

    def test_reset_keeps_foreign_keys_and_includes_committed_wal_data(self):
        with closing(sqlite3.connect(self.path)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute("UPDATE parent SET value='committed WAL'");writer.commit()
            # Keep the writer open so the snapshot must handle WAL correctly.
            with database_baseline(self.path) as restore:
                writer.execute("UPDATE parent SET value='later change'");writer.commit()
                writer.close()  # Restore with no other fixture connection open.
                restore()
                with closing(connect_database(self.path)) as c:
                    self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)
                    self.assertEqual(c.execute('SELECT value FROM parent').fetchone()[0],'committed WAL')
                    with self.assertRaises(sqlite3.IntegrityError):
                        c.execute('INSERT INTO child VALUES (1,999)')


class WorldCloneTests(unittest.TestCase):
    def test_clone_databases_and_mutable_attributes_are_independent(self):
        from types import SimpleNamespace
        builds=[]
        def factory(owner):
            builds.append(1)
            temp=tempfile.TemporaryDirectory();owner.addCleanup(temp.cleanup)
            path=Path(temp.name)/'seed.db'
            with closing(sqlite3.connect(path)) as c,c:
                c.execute('CREATE TABLE example (value TEXT)')
                c.execute("INSERT INTO example VALUES ('baseline')")
            return SimpleNamespace(path=path,tmp=temp,config={'values':[1]},account=7)
        baseline=WorldBaseline(type(self),factory)
        first=baseline.restore(self);second=baseline.restore(self)
        self.assertTrue(first.path.is_file());self.assertTrue(second.path.is_file())
        self.assertEqual(builds,[1]);self.assertNotEqual(first.path,second.path)
        first.config['values'].append(2)
        self.assertEqual(second.config,{'values':[1]})
        with closing(connect_database(first.path)) as c,c:c.execute("UPDATE example SET value='changed'")
        with closing(connect_database(second.path)) as c:
            self.assertEqual(c.execute('SELECT value FROM example').fetchone()[0],'baseline')
        third=baseline.restore(self)
        with closing(connect_database(third.path)) as c:
            self.assertEqual(c.execute('SELECT value FROM example').fetchone()[0],'baseline')
        self.assertEqual(third.account,7)


class BorrowedFixtureTests(unittest.TestCase):
    def test_borrowed_setup_can_supply_preparer_without_inheriting_its_class(self):
        class Borrower(unittest.TestCase):
            pass
        builds=[]
        def prepare(world):
            builds.append(1)
            world.temp=tempfile.TemporaryDirectory();world.addCleanup(world.temp.cleanup)
            world.path=Path(world.temp.name)/'borrowed.db'
            with closing(sqlite3.connect(world.path)) as c,c:
                c.execute('CREATE TABLE example (value INTEGER)')
                c.execute('INSERT INTO example VALUES (7)')
            world.account=9
        first=Borrower();second=Borrower()
        try:
            restore_case_baseline(first,'borrowed',prepare)
            restore_case_baseline(second,'borrowed',prepare)
            self.assertEqual(builds,[1]);self.assertNotEqual(first.path,second.path)
            self.assertEqual(first.account,9);self.assertEqual(second.account,9)
            self.assertEqual(first.temp.name,str(first.path.parent))
            self.assertEqual(first._testMethodName,'runTest')
        finally:
            first.doCleanups();second.doCleanups();Borrower.doClassCleanups()
