"""Read-only operator activity inspection boundaries on a minimal saved database."""
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from game.operator_views import inspection_activity

class ActivityInspectionTests(unittest.TestCase):
    def test_bounded_owned_escaped_records_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'inspection.db'
            with closing(sqlite3.connect(path)) as c,c:
                c.execute('CREATE TABLE military_units (unit_id INTEGER PRIMARY KEY,settlement_id INTEGER,note TEXT)')
                c.executemany('INSERT INTO military_units VALUES (?,1,?)',[(i,'<unsafe>') for i in range(1,61)])
                c.execute("INSERT INTO military_units VALUES (100,2,'other-player-secret')")
            before=path.read_bytes()
            html=inspection_activity(path,1)
            self.assertIn('Equipment (50)',html)
            self.assertEqual(html.count('&lt;unsafe&gt;'),50)
            self.assertNotIn('other-player-secret',html)
            self.assertNotIn('<unsafe>',html)
            self.assertEqual(path.read_bytes(),before)

    def test_missing_optional_tables_are_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'empty.db'
            with closing(sqlite3.connect(path)):pass
            self.assertIn('Saved activity and equipment',inspection_activity(path,1))
