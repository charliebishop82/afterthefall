"""Authenticated HTTP controls for rations and military production."""
from contextlib import closing
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlencode

from accounts_app import AccountServer
from database.create_database import connect_database
from game import accounts
from game.settlement import account_scope,read_settlement


from tests.fixtures import HTTPFixture

class FeatureHTTPTests(HTTPFixture, unittest.TestCase):
    def setUp(self):
        self.setup_http()

    def test_ration_forms_csrf_origin_duplicates_invalid_values_and_owner_isolation(self):
        csrf=self.players[0][2]
        self.assertEqual(self.request('/needs',{'action':'enable','token':'wrong'})[0],403)
        self.assertEqual(self.request('/needs',{'action':'enable','token':csrf},origin='https://example.com')[0],403)
        self.assertEqual(self.request('/needs',{'action':['enable','enable'],'token':csrf})[0],400)
        self.assertEqual(self.request('/needs',{'action':'enable','token':csrf})[0],303)
        self.assertEqual(self.request('/needs',{'action':'rations','token':csrf,'food':'reduced','water':'emergency'})[0],303)
        self.assertEqual(self.state()['policies']['food_ration'],'reduced')
        self.assertEqual(self.state(1)['policies']['food_ration'],'full')
        self.assertIsNone(self.state(1)['needs_clock'])
        before=self.state()
        self.assertEqual(self.request('/needs',{'action':'rations','token':csrf,'food':'invalid'})[0],400)
        self.assertEqual(before,self.state())
        status,body=self.request();self.assertEqual(status,200)
        self.assertIn(b'Food shortage: 6-hour grace',body)
        self.assertIn(b'Ground Defense Drone',body)
        status,body=self.request('/api/resources');self.assertEqual(status,200)
        self.assertAlmostEqual(json.loads(body)['rates']['food']['consumption'],4.5)
    def test_manufacturing_controls_reject_foreign_factory_and_anonymous_actor(self):
        csrf=self.players[0][2]
        self.assertEqual(self.request('/manufacturing',{'action':'enable','token':csrf})[0],303)
        with closing(connect_database(self.path)) as c,c:
            bid=c.execute("INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at) VALUES (1,'drone_factory',1,21,18,900,'active',1000,1000)").lastrowid
        foreign_csrf=self.players[1][2]
        fields={'action':'queue','token':foreign_csrf,'building_id':bid,'unit_type':'offensive_drone','quantity':'1'}
        self.assertEqual(self.request('/manufacturing',fields,player=1)[0],400)
        self.assertEqual(self.state()['jobs'],[])
        anon,session=accounts.new_session(self.path,None,1000)
        old=self.players[1];self.players[1]=(None,anon,session['csrf'])
        self.assertEqual(self.request('/manufacturing',{'action':'enable','token':session['csrf']},player=1)[0],401)
        self.players[1]=old
