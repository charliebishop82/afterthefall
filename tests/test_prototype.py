"""Regression tests for local settlement creation, storage, and HTTP pages."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import http.client
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from app import PrototypeServer
from database.create_database import connect_database
from game.settlement import create_settlement, load_config, prepare_database, read_settlement


class SettlementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'prototype.db'
        prepare_database(self.path)

    def query(self, sql, params=()):
        with closing(connect_database(self.path)) as connection, connection:
            return connection.execute(sql, params).fetchall()

    def test_starting_configuration_matches_reference_workbook(self):
        # Read only the original cells; verify copied balance values independently.
        source = Path(__file__).resolve().parents[1] / 'sources' / load_config()['sources']['workbook']
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with ZipFile(source) as book:
            def rows(sheet):
                result = []
                for row in ET.fromstring(book.read(f'xl/worksheets/sheet{sheet}.xml')).findall('.//s:row', ns):
                    cells = {}
                    for cell in row.findall('s:c', ns):
                        value = ''.join(cell.itertext()) if cell.get('t') == 'inlineStr' else cell.findtext('s:v', '', ns)
                        cells[''.join(filter(str.isalpha, cell.get('r')))] = value
                    result.append(cells)
                return result
            settings = {r.get('A'):r.get('D') for r in rows(6)}
            config = load_config()
            for resource, value in config['resources'].items():
                self.assertEqual(value, float(settings['starting_' + resource]))
            for key in ['starting_population', 'map_width', 'map_height', 'starting_attacks']:
                self.assertEqual(config[key], float(settings[key]))
            buildings = rows(1)
            headers = {label: column for column, label in buildings[0].items()}
            hall = next(r for r in buildings if r.get('A') == 'town_hall')
            for config_key, column_label in [('hp','HP_L1'), ('housing','Housing_Capacity_L1'),
                    ('food_storage','Food_Storage_L1'), ('water_storage','Water_Storage_L1'),
                    ('material_storage','Material_Storage_L1')]:
                self.assertEqual(config['town_hall'][config_key], float(hall[headers[column_label]]))

    def test_read_does_not_initialize(self):
        self.assertIsNone(read_settlement(self.path))
        self.assertEqual(self.query('SELECT count(*) FROM settlements'), [(0,)])

    def test_starting_settlement_and_history(self):
        create_settlement(self.path, 'New Avalon', now=1000)
        state = read_settlement(self.path)
        self.assertEqual(state['settlement']['settlement_name'], 'New Avalon')
        self.assertEqual(len(state['citizens']), 6)
        self.assertEqual(len({c['name'] for c in state['citizens']}), 6)
        self.assertTrue(all(c['level'] == 1 and c['xp'] == 0 for c in state['citizens']))
        self.assertEqual(state['buildings'][0]['building_type'], 'town_hall')
        self.assertEqual(state['buildings'][0]['current_hp'], 1000)
        self.assertEqual(self.query('SELECT count(*) FROM citizen_settlement_history'), [(6,)])
        self.assertEqual(self.query('SELECT count(*) FROM citizen_level_history'), [(6,)])
        self.assertEqual(self.query('SELECT assignment_type FROM citizen_assignments'), [('administrator',)])
        self.assertEqual(self.query('SELECT status,paused_at FROM seasons'), [('paused',1000)])
        self.assertEqual(self.query('SELECT sum(amount) FROM credit_transactions'), [(0,)])
        self.assertEqual(self.query('PRAGMA foreign_key_check'), [])

    def test_reopen_and_repeat_creation_preserve_saved_changes(self):
        first = create_settlement(self.path, 'First Home', now=1000)
        self.query('UPDATE settlement_resources SET food=91.5')
        before = read_settlement(self.path)
        prepare_database(self.path)
        second = create_settlement(self.path, 'Do not rename', now=9000)
        self.assertEqual(first, second)
        self.assertEqual(read_settlement(self.path), before)
        self.assertEqual(self.query('SELECT count(*) FROM accounts'), [(1,)])
        self.assertEqual(self.query('SELECT count(*) FROM credit_transactions'), [(2,)])

    def test_concurrent_creation_initializes_only_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: create_settlement(self.path, 'Home', now=1000), range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(self.query('SELECT count(*) FROM citizens'), [(6,)])

    def test_invalid_names_leave_database_empty(self):
        for name in ['', '   ', 'x'*41, 'Bad\nName', None]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                create_settlement(self.path, name, now=1000)
        self.assertIsNone(read_settlement(self.path))

    def test_failure_rolls_back_all_creation(self):
        self.query("CREATE TRIGGER fail_birth BEFORE INSERT ON citizens BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            create_settlement(self.path, 'Home', now=1000)
        for table in ['accounts','seasons','settlements','buildings','settlement_resources']:
            self.assertEqual(self.query(f'SELECT count(*) FROM {table}'), [(0,)])
        self.query('DROP TRIGGER fail_birth')
        create_settlement(self.path, 'Home', now=1000)
        self.assertEqual(len(read_settlement(self.path)['citizens']), 6)

    def test_unknown_schema_is_rejected_without_modification(self):
        self.query('PRAGMA user_version=999')
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            prepare_database(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unrelated_game_data_is_not_overwritten(self):
        self.query("INSERT INTO accounts (username,password_hash,display_name,created_at) VALUES ('real','hash','Real',0)")
        with self.assertRaises(ValueError):
            prepare_database(self.path)
        with self.assertRaises(ValueError):
            create_settlement(self.path, 'Home', now=1000)
        self.assertEqual(self.query('SELECT username FROM accounts'), [('real',)])

    def test_configuration_and_secrets_are_not_accepted_from_client(self):
        with self.assertRaises(ValueError):
            load_config('../../sources/anything')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'prototype.db'
        prepare_database(self.path)
        self.start_server()
        self.addCleanup(self.stop_server)

    def start_server(self):
        self.server = PrototypeServer(('127.0.0.1',0), self.path)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval':0.01}, daemon=True)
        self.thread.start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method='GET', path='/', body=None, headers=None):
        with closing(http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)) as client:
            client.request(method, path, body=body, headers=headers or {})
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode('utf-8')

    def create(self, name='New Avalon', token=None, headers=None):
        return self.request('POST','/settlement',urlencode({'name':name, 'token':self.server.form_token if token is None else token}),
                            {'Content-Type':'application/x-www-form-urlencoded', **(headers or {})})

    def test_full_browser_flow_survives_server_restart(self):
        status, headers, body = self.request()
        self.assertEqual(status,200)
        self.assertIn('Create settlement',body)
        self.assertIsNone(read_settlement(self.path))
        status, headers, _ = self.create()
        self.assertEqual(status,303)
        self.assertEqual(headers['Location'],'/')
        status, _, body = self.request()
        self.assertEqual(status,200)
        for text in ['New Avalon','Mara Vale','Town Hall','120','180','500','Time is paused.']:
            self.assertIn(text,body)
        before = read_settlement(self.path)
        self.stop_server()
        prepare_database(self.path)
        self.start_server()
        self.assertIn('New Avalon',self.request()[2])
        self.assertEqual(read_settlement(self.path),before)
        self.assertEqual(self.create('Second submission')[0],303)
        self.assertEqual(read_settlement(self.path),before)

    def test_validation_and_html_escaping(self):
        self.assertEqual(self.create(' ')[0],400)
        self.assertIsNone(read_settlement(self.path))
        self.assertEqual(self.create('<script>alert(1)</script>')[0],303)
        body = self.request()[2]
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',body)
        self.assertNotIn('<script>',body)

    def test_cross_site_or_invalid_token_cannot_create(self):
        self.assertEqual(self.create(token='wrong')[0],403)
        self.assertEqual(self.create(headers={'Origin':'https://example.invalid'})[0],403)
        self.assertEqual(self.request(headers={'Host':'other.example'})[0],403)
        self.assertIsNone(read_settlement(self.path))

    def test_static_files_and_private_paths(self):
        self.assertEqual(self.request(path='/static/style.css')[0],200)
        for path in ['/database/prototype.db','/sources/','/static/../app.py','/app.py']:
            self.assertEqual(self.request(path=path)[0],404)

    def test_non_ascii_token_is_rejected_cleanly(self):
        self.assertEqual(self.create(token='invalid-é')[0],403)
        self.assertIsNone(read_settlement(self.path))

    def test_bad_forms_are_rejected_without_mutation(self):
        self.assertEqual(self.request('POST','/settlement','{}',{'Content-Type':'application/json'})[0],415)
        self.assertEqual(self.request('POST','/settlement','x'*5000,{'Content-Type':'application/x-www-form-urlencoded'})[0],413)
        self.assertIsNone(read_settlement(self.path))


if __name__ == '__main__':
    unittest.main()
