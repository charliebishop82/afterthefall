"""Request history uses disposable saves and never records credentials."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from flask_app import COOKIE, create_app
from game import accounts


class PlayerLoggingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = Path(self.tmp.name) / 'playtest.db'
        self.log = Path(self.tmp.name) / 'player-actions.jsonl'
        self.app = create_app(self.database, clock=lambda: 1000, log_path=self.log)
        self.client = self.app.test_client()
        for handler in self.app.extensions['player_logger'].handlers:
            self.addCleanup(handler.close)

    def records(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def get(self, path):
        response = self.client.get(path, base_url='http://127.0.0.1:8767')
        self.addCleanup(response.close)
        return response

    def player(self):
        aid = accounts.register(self.database, 'learner', 'private-password-long', 1000)
        token, session = accounts.new_session(self.database, aid, 1000)
        self.client.set_cookie(COOKIE, token, domain='127.0.0.1')
        return aid, token, session['csrf']

    def test_read_requests_have_utc_time_correlated_id_and_safe_route(self):
        response = self.get('/help?password=query-secret')
        row = self.records()[-1]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-Request-ID'], row['request_id'])
        self.assertEqual(row['route'], '/help')
        self.assertEqual(row['received_at'], 1000)
        self.assertTrue(row['timestamp_utc'].endswith('+00:00'))
        self.assertGreaterEqual(row['duration_ms'], 0)
        self.assertNotIn('query-secret', self.log.read_text())

    def test_clock_rejection_keeps_actor_targets_and_safe_error_frames(self):
        aid, cookie, csrf = self.player()
        with patch('game.lobby.status', return_value={'status': 'started'}), \
             patch('flask_app.game_action', side_effect=ValueError('The clock is earlier than the save.')):
            response = self.client.post('/scavenging', data={
                'token': csrf, 'action': 'assign', 'citizen_id': '7', 'derelict_id': '12'},
                base_url='http://127.0.0.1:8767')
        self.addCleanup(response.close)
        row = self.records()[-1]
        self.assertEqual(response.status_code, 400)
        self.assertEqual(row['account_id'], aid)
        self.assertEqual(row['action_timestamp'], 1000)
        self.assertEqual(row['route'], '/scavenging')
        self.assertEqual(row['action'], 'assign')
        self.assertEqual(row['parameters'], {'citizen_id': 7, 'derelict_id': 12})
        self.assertEqual(row['error_code'], 'clock_before_saved_state')
        self.assertEqual(row['error_type'], 'ValueError')
        self.assertTrue(row['error_frames'])
        self.assertNotIn(cookie, self.log.read_text())
        self.assertNotIn(csrf, self.log.read_text())

    def test_rejected_auth_and_unknown_paths_do_not_leak_supplied_text(self):
        response = self.client.post('/login', data={
            'username': 'private-user', 'password': 'private-password',
            'token': 'private-token'}, base_url='http://127.0.0.1:8767')
        self.addCleanup(response.close)
        self.assertEqual(response.status_code, 403)
        self.get('/private-path-secret?token=query-secret')
        text = self.log.read_text()
        for secret in ('private-user', 'private-password', 'private-token',
                       'private-path-secret', 'query-secret'):
            self.assertNotIn(secret, text)
        self.assertEqual(self.records()[-1]['route'], '(unknown route)')

    def test_unexpected_error_records_location_without_exception_message(self):
        with patch('flask_app.send_file', side_effect=RuntimeError('private-exception-secret')):
            response = self.get('/help.pdf')
        self.assertEqual(response.status_code, 500)
        row = self.records()[-1]
        self.assertEqual(row['error_type'], 'RuntimeError')
        self.assertEqual(row['outcome'], 'rejected')
        self.assertTrue(row['error_frames'])
        self.assertNotIn('private-exception-secret', self.log.read_text())

    def test_rotation_keeps_a_bounded_recent_history(self):
        handler = self.app.extensions['player_logger'].handlers[0]
        handler.maxBytes = 700
        handler.backupCount = 2
        for _ in range(8):
            self.get('/help')
        files = list(self.log.parent.glob('player-actions.jsonl*'))
        self.assertGreater(len(files), 1)
        self.assertLessEqual(len(files), 3)
        for path in files:
            for line in path.read_text().splitlines():
                self.assertIn('request_id', json.loads(line))


if __name__ == '__main__':
    unittest.main()
