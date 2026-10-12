"""Operator navigation and read-only inspection on disposable saves."""
from pathlib import Path
import tempfile
import unittest

from admin_suite import create_app, COOKIE
from game import accounts, admin, lobby
from game.operator_views import control_sections, request_table


class OperatorDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.db';lobby.prepare(self.path)
        self.owner=accounts.register(self.path,'owner','owner-password-long',1000)
        admin.grant(self.path,'owner',1000)
        lobby.enroll(self.path,self.owner,'Owner town',1000);lobby.start(self.path,self.owner,1000,'Test launch')
        self.app=create_app(self.path,clock=lambda:1000)
        self.client=self.app.test_client()
        cookie,_=accounts.new_session(self.path,self.owner,1000)
        self.client.set_cookie(COOKIE,cookie,domain='127.0.0.1')

    def get(self,path):return self.client.get(path,base_url='http://127.0.0.1:8768')

    def test_dashboard_has_navigation_and_bot_creation_controls(self):
        response=self.get('/')
        self.assertEqual(response.status_code,200)
        for title in ('Players & maps','Diagnostics','Corrections'):
            self.assertIn(title,response.text)
        self.assertIn('Create paused bot',self.get('/bots').text)

    def test_inspection_does_not_write_save_or_offer_player_actions(self):
        before=self.path.read_bytes()
        response=self.get('/players/1')
        self.assertEqual(response.status_code,200)
        self.assertIn('<svg',response.text)
        self.assertIn('Read-only committed snapshot',response.text)
        self.assertNotIn('action="/buildings"',response.text)
        self.assertNotIn('/static/resources.js',response.text)
        self.assertEqual(self.path.read_bytes(),before)

    def test_new_pages_require_administrator_login(self):
        self.client.delete_cookie(COOKIE,domain='127.0.0.1')
        for path in ('/players','/players/1','/bots','/controls'):
            self.assertEqual(self.get(path).status_code,303)

    def test_control_sections_preserve_forms_and_reject_unknown_selection(self):
        html='<h1>Admin</h1><h2>Accounts</h2><form action="/admin">Account</form><h2>Corrections</h2><form action="/admin">Fix</form>'
        selected=control_sections(html,'corrections')
        self.assertIn('Fix',selected);self.assertNotIn('Account</form>',selected)
        with self.assertRaises(ValueError):control_sections(html,'arbitrary')

    def test_request_table_escapes_record_contents_and_shows_error_code(self):
        html=request_table([dict(method='POST',route='/buildings',status=400,
            error_code='clock_before_saved_state',action='<script>bad</script>',request_id='a'*32)])
        self.assertIn('clock_before_saved_state',html)
        self.assertNotIn('<script>bad</script>',html)
        self.assertIn('&lt;script&gt;',html)
