"""Real authenticated Flask requests accept citizen groups and enforce CSRF."""
import unittest
from flask_app import create_app,COOKIE
from game import accounts
from tests import test_economy_bots as fixtures

class ExpeditionHTTPTests(unittest.TestCase):
    setUp=fixtures.EconomyBotTests.setUp
    state=fixtures.EconomyBotTests.state
    def test_multi_citizen_launch_api_and_csrf(self):
        app=create_app(self.path,clock=lambda:1000);client=app.test_client()
        token,session=accounts.new_session(self.path,self.owner,1000)
        client.set_cookie(COOKIE,token,domain='127.0.0.1')
        free=[c['citizen_id'] for c in self.state(self.owner)['citizens'] if c['assignment']=='unassigned'][:2]
        fields=dict(token=session['csrf'],action='launch',citizen_id=[str(cid) for cid in free],food='6',water='6')
        response=client.post('/expeditions',data=dict(fields,token='forged'),base_url='http://127.0.0.1:8767')
        self.assertEqual(response.status_code,403)
        response=client.post('/expeditions',data=fields,base_url='http://127.0.0.1:8767')
        self.assertEqual(response.status_code,303)
        self.assertEqual(sum(c.get('exploring',False) for c in self.state(self.owner)['citizens']),2)
        payload=client.get('/api/resources',base_url='http://127.0.0.1:8767').get_json()
        self.assertEqual(payload['expeditions'][0]['status'],'exploring')
        self.assertIn('storage_status',payload)
        page=client.get('/',base_url='http://127.0.0.1:8767').text
        self.assertIn('Explore the Wastes',page)
        self.assertIn('Exploring the Wastes',page)
