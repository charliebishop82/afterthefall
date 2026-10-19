"""Normal market validation remains in force for in-place player requests."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from database.create_database import connect_database
from flask_app import create_app,COOKIE
from game import accounts,admin,lobby
from tests.fixtures import baseline_world


def market_world(owner):
    temp=TemporaryDirectory();owner.addCleanup(temp.cleanup)
    path=Path(temp.name)/'market.db';lobby.prepare(path)
    with closing(connect_database(path)) as c,c:
        aid=c.execute("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES ('owner','!','Owner',1000)").lastrowid
    admin.grant(path,'owner',1000);lobby.enroll(path,aid,'Test town',1000)
    lobby.start(path,aid,1000,'Market transport baseline')
    return SimpleNamespace(tmp=temp,path=path,aid=aid)


class MarketInPlaceTests(unittest.TestCase):
    def setUp(self):
        world=baseline_world(self,'market-in-place',market_world)
        self.path=world.path;self.aid=world.aid
        self.app=create_app(self.path,clock=lambda:1000);self.app.config['TESTING']=True
        self.client=self.app.test_client()
        cookie,session=accounts.new_session(self.path,self.aid,1000)
        self.token=session['csrf'];self.client.set_cookie(COOKIE,cookie,domain='127.0.0.1')

    def sql(self,query,args=()):
        with closing(connect_database(self.path)) as c,c:return c.execute(query,args).fetchall()

    def post(self,action,async_request=True,**fields):
        headers={'X-Market-Async':'1'} if async_request else {}
        return self.client.post('/market',base_url='http://127.0.0.1:8767',data=dict(token=self.token,action=action,resource='scrap',quantity=1,**fields),headers=headers)

    def test_sale_and_purchase_commit_once_without_redirect(self):
        before=self.sql('SELECT scrap FROM settlement_resources')[0][0]
        sold=self.post('sell');self.assertEqual(sold.status_code,204)
        self.assertNotIn('Location',sold.headers)
        self.assertEqual(self.sql('SELECT scrap FROM settlement_resources')[0][0],before-1)
        bought=self.post('buy');self.assertEqual(bought.status_code,204)
        self.assertEqual(self.sql('SELECT scrap FROM settlement_resources')[0][0],before)
        self.assertEqual(self.sql('SELECT count(*) FROM market_pool_trades')[0][0],2)

    def test_normal_form_keeps_existing_redirect_behavior(self):
        self.assertEqual(self.post('sell',async_request=False).status_code,303)

    def test_validation_failure_preserves_data(self):
        before=self.sql('SELECT scrap,credits FROM settlement_resources')
        result=self.client.post('/market',base_url='http://127.0.0.1:8767',data=dict(token=self.token,action='sell',resource='scrap',quantity=0),headers={'X-Market-Async':'1'})
        self.assertEqual(result.status_code,400)
        self.assertEqual(before,self.sql('SELECT scrap,credits FROM settlement_resources'))

    def test_async_header_does_not_bypass_csrf(self):
        result=self.client.post('/market',base_url='http://127.0.0.1:8767',data=dict(token='wrong',action='sell',resource='scrap',quantity=1),headers={'X-Market-Async':'1'})
        self.assertEqual(result.status_code,403)
        self.assertEqual(self.sql('SELECT count(*) FROM market_pool_trades')[0][0],0)

    def test_fragment_is_authenticated_and_does_not_advance_simulation(self):
        self.post('sell')
        before=self.sql('SELECT simulation_processed_at FROM settlements')
        response=self.client.get('/api/market-panel',base_url='http://127.0.0.1:8767')
        self.assertEqual(response.status_code,200)
        self.assertIn('id="market"',response.text)
        self.assertNotIn('<html',response.text.lower())
        self.assertEqual(before,self.sql('SELECT simulation_processed_at FROM settlements'))
        other=self.app.test_client()
        self.assertEqual(other.get('/api/market-panel',base_url='http://127.0.0.1:8767').status_code,401)
