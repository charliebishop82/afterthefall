"""Admin-only, bounded player log reading; disposable fixtures only."""
import json
from pathlib import Path
import tempfile
import unittest

from admin_suite import create_app, COOKIE
from game import accounts, admin, lobby


class PlayerLogViewerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = Path(self.tmp.name)/'playtest.db'
        lobby.prepare(self.database)
        self.owner = accounts.register(self.database, 'owner', 'owner-password-long', 1000)
        self.player = accounts.register(self.database, 'player', 'player-password-long', 1000)
        admin.grant(self.database, 'owner', 1000)
        self.log = Path(self.tmp.name)/'player-actions.jsonl'
        self.app = create_app(self.database, clock=lambda:1000, player_log_path=self.log)
        self.client = self.app.test_client()
        self.addCleanup(lambda:[h.close() for h in self.app.extensions['operator_logger'].handlers])
        self.sign_in(self.owner)

    def sign_in(self, account):
        cookie, _ = accounts.new_session(self.database, account, 1000)
        self.client.set_cookie(COOKIE, cookie, domain='127.0.0.1')

    def get(self, query=''):
        return self.client.get('/player-logs'+query, base_url='http://127.0.0.1:8768')

    def write(self, records, suffix=''):
        Path(str(self.log)+suffix).write_text(
            ''.join(json.dumps(r)+'\n' for r in records), encoding='utf-8')

    def record(self, **changes):
        data = dict(database=self.database.name, account_id=self.owner,
                    request_id='a'*32, status=303, event='request_finished')
        data.update(changes)
        return data

    def test_admin_required_for_html_and_export(self):
        self.client.delete_cookie(COOKIE, domain='127.0.0.1')
        self.assertEqual(self.get().status_code, 303)
        self.assertEqual(self.get('?format=json').status_code, 303)
        self.sign_in(self.player)
        self.assertEqual(self.get().status_code, 403)
        self.assertEqual(self.get('?format=json').status_code, 403)

    def test_filters_export_and_save_isolation(self):
        self.write([self.record(), self.record(status=400, request_id='b'*32),
                    self.record(database='other.db', status=500)])
        result = self.get('?errors=1&format=json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual([r['status'] for r in result.json], [400])
        self.assertEqual(len(self.get('?request_id='+'a'*32+'&format=json').json), 1)
        self.assertEqual(self.get('?account='+str(self.player)+'&format=json').json, [])
        self.assertIn('attachment', result.headers['Content-Disposition'])

    def test_missing_rotations_and_invalid_path_selection(self):
        self.assertIn('No records in this file yet', self.get().text)
        self.write([self.record(status=403)], '.1')
        self.assertEqual(self.get('?rotation=1&format=json').json[0]['status'], 403)
        for value in ('6', '-1', '../private', '1.5'):
            self.assertEqual(self.get('?rotation='+value).status_code, 400)

    def test_invalid_lines_html_escaping_and_no_log_rewrite(self):
        self.write([self.record(action='<script>alert(1)</script>')])
        with self.log.open('a', encoding='utf-8') as stream:
            stream.write('{"partial":\n[]\n')
        before = self.log.read_bytes()
        result = self.get()
        self.assertEqual(result.status_code, 200)
        self.assertIn('Skipped 2', result.text)
        self.assertNotIn('<script>alert(1)</script>', result.text)
        self.assertIn('&lt;script&gt;', result.text)
        self.assertEqual(self.log.read_bytes(), before)
        self.assertEqual(lobby.status(self.database)['status'], 'waiting')

    def test_bounded_newest_first_history(self):
        self.write([self.record(sequence=i) for i in range(150)])
        records = self.get('?format=json').json
        self.assertEqual(len(records), 100)
        self.assertEqual((records[0]['sequence'], records[-1]['sequence']), (149, 50))
        self.write([self.record(action='x'*270000), self.record(sequence=999)])
        self.assertEqual(self.get('?format=json').json, [self.record(sequence=999)])


if __name__ == '__main__':
    unittest.main()
