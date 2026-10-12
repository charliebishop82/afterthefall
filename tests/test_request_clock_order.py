"""Player requests sample gameplay time after overlapping refreshes finish."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from flask_app import COOKIE, create_app
from game import accounts


class RequestClockOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'playtest.db'
        self.clock = 1000
        self.app = create_app(self.path, clock=lambda:self.clock)
        aid = accounts.register(self.path, 'player', 'player-password-long', 1000)
        self.cookie, session = accounts.new_session(self.path, aid, 1000)
        self.csrf = session['csrf']

    def request(self, path, data=None):
        with self.app.test_client() as client:
            client.set_cookie(COOKIE, self.cookie, domain='127.0.0.1')
            if data is None: return client.get(path, base_url='http://127.0.0.1:8767').status_code
            return client.post(path, data=data, base_url='http://127.0.0.1:8767').status_code

    def overlap(self, action_path):
        refresh_entered = Event(); action_authenticated = Event(); finish_refresh = Event()
        seen = []; original_session = accounts.session

        def session(*args, **kwargs):
            actor = original_session(*args, **kwargs)
            if refresh_entered.is_set(): action_authenticated.set()
            return actor

        def advance(path, stamp):
            refresh_entered.set()
            if not finish_refresh.wait(5): raise RuntimeError('Test refresh was not released')
            self.clock = 1001
            seen.append(('refresh', self.clock))
            return {'mock_state': True}

        def action(path, route, form, stamp):
            # Equivalent to a service rejecting a time before the committed save.
            if stamp < self.clock: raise ValueError('The clock is earlier than the save.')
            seen.append((route, stamp))

        with patch('game.lobby.status', return_value={'status':'started'}), \
             patch('game.expansion.refresh'), \
             patch('game.simulation.advance_settlement', side_effect=advance), \
             patch('game.web_views.resources', return_value={'status':'active'}), \
             patch('game.accounts.session', side_effect=session), \
             patch('flask_app.game_action', side_effect=action):
            with ThreadPoolExecutor(max_workers=2) as executor:
                refresh = executor.submit(self.request, '/api/resources')
                try:
                    self.assertTrue(refresh_entered.wait(5))
                    submit = executor.submit(self.request, action_path, {'token':self.csrf, 'action':'build'})
                    self.assertTrue(action_authenticated.wait(5))
                finally:
                    finish_refresh.set()
                self.assertEqual(refresh.result(timeout=5), 200)
                self.assertEqual(submit.result(timeout=5), 303)
        self.assertEqual(seen, [('refresh',1001), (action_path,1001)])

    def test_build_waits_for_refresh_before_sampling_action_time(self):
        self.overlap('/buildings')

    def test_scavenging_waits_for_refresh_before_sampling_action_time(self):
        self.overlap('/scavenging')

    def test_genuine_backward_clock_error_is_not_suppressed_or_retried(self):
        with patch('game.lobby.status', return_value={'status':'started'}), \
             patch('flask_app.game_action', side_effect=ValueError('The clock is earlier than the save.')) as action:
            self.assertEqual(self.request('/buildings', {'token':self.csrf,'action':'build'}),400)
        self.assertEqual(action.call_count,1)
