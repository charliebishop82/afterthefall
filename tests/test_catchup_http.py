"""Catch-up transport must not render or act on a partially updated world."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask_app import create_app, COOKIE
from game import accounts


class CatchupHTTPTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'game.db'
        self.app=create_app(self.path,clock=lambda:1000)
        self.client=self.app.test_client()
        self.aid=accounts.register(self.path,'tester','a-long-test-password',1000)
        token,self.session=accounts.new_session(self.path,self.aid,1000)
        self.client.set_cookie(COOKIE,token,domain='127.0.0.1')
        self.progress={'status':'catching_up','remaining_seconds':10000}

    def test_initial_page_and_poll_defer_full_render(self):
        with patch('game.lobby.status',return_value={'status':'started'}), \
             patch('game.catchup.status',return_value=self.progress), \
             patch('game.expansion.refresh') as refresh:
            response=self.client.get('/',base_url='http://127.0.0.1:8767')
            self.assertEqual(response.status_code,200)
            self.assertIn(b'catchup-progress',response.data)
            self.assertIn(b'/static/catchup.js',response.data)
            self.assertEqual(self.client.get('/api/resources',base_url='http://127.0.0.1:8767').status_code,202)
            refresh.assert_not_called()

    def test_actions_deferred_without_invoking_game_service(self):
        with patch('game.lobby.status',return_value={'status':'started'}), \
             patch('game.catchup.status',return_value=self.progress), \
             patch('flask_app.game_action') as action:
            response=self.client.post('/buildings',base_url='http://127.0.0.1:8767',data={'token':self.session['csrf'],'action':'build'})
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.headers['Retry-After'],'2')
            action.assert_not_called()

    def test_disallowed_host_still_rejected_before_catchup(self):
        with patch('game.catchup.step') as step:
            response=self.client.get('/api/catchup',base_url='http://untrusted.invalid:8767')
            self.assertEqual(response.status_code,403)
            step.assert_not_called()

    def test_action_with_wrong_csrf_does_not_reach_game_service(self):
        with patch('flask_app.game_action') as action:
            response=self.client.post('/buildings',base_url='http://127.0.0.1:8767',data={'token':'wrong','action':'build'})
            self.assertEqual(response.status_code,403)
            action.assert_not_called()

    def test_batch_route_requires_login(self):
        self.client.delete_cookie(COOKIE,domain='127.0.0.1')
        with patch('game.catchup.step') as step:
            self.assertEqual(self.client.get('/api/catchup',base_url='http://127.0.0.1:8767').status_code,401)
            step.assert_not_called()


    def test_readiness_is_authenticated_and_does_not_run_simulation(self):
        with patch('game.catchup.status',return_value={'status':'ready'}) as status,patch('game.catchup.step') as step,patch('game.expansion.refresh') as refresh:
            response=self.client.get('/api/catchup-status?scope=bank',base_url='http://127.0.0.1:8767')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['status'],'ready')
            self.assertTrue(status.call_args.kwargs['shared'])
            step.assert_not_called();refresh.assert_not_called()

    def test_readiness_requires_login(self):
        self.client.delete_cookie(COOKIE,domain='127.0.0.1')
        with patch('game.catchup.status') as status:
            response=self.client.get('/api/catchup-status',base_url='http://127.0.0.1:8767')
            self.assertEqual(response.status_code,401);status.assert_not_called()
