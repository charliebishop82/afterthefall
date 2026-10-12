"""Bot market observations expose public stock and only the caller's allowance."""
import unittest
from game import market
from tests import test_social as fixtures

class MarketSnapshotTests(unittest.TestCase):
    setUp=fixtures.SocialTests.setUp
    player=fixtures.SocialTests.player
    state=fixtures.SocialTests.state
    sql=fixtures.SocialTests.sql
    action=fixtures.SocialTests.action

    def test_snapshot_limits_are_own_and_sales_are_public(self):
        self.action(market,self.a,'reserve_buy',resource='scrap',quantity=2)
        self.action(market,self.a,'sell',resource='scrap',quantity=10)
        a=market.public_snapshot(self.path,self.state(self.a),1000)
        b=market.public_snapshot(self.path,self.state(self.b),1000)
        self.assertEqual(a['resources']['scrap']['stock'],10)
        self.assertEqual(b['resources']['scrap']['stock'],10)
        self.assertEqual(a['resources']['scrap']['reserve_remaining'],18)
        self.assertEqual(b['resources']['scrap']['reserve_remaining'],20)
        self.assertNotIn('players',a)

    def test_paused_and_finalizing_markets_are_unavailable(self):
        self.sql("UPDATE seasons SET status='paused',paused_at=1000")
        self.assertFalse(market.public_snapshot(self.path,self.state(self.a),1000)['can_trade'])
        self.sql("UPDATE seasons SET status='active',finalization_at=1000")
        self.assertFalse(market.public_snapshot(self.path,self.state(self.a),1000)['can_trade'])


class RunnerMarketTests(unittest.TestCase):
    from tests import test_economy_bots as fixtures
    setUp=fixtures.EconomyBotTests.setUp
    state=fixtures.EconomyBotTests.state

    def test_rejected_market_action_keeps_source_quantity_and_request_id(self):
        import json
        from contextlib import closing
        from unittest.mock import patch
        from database.create_database import connect_database
        from game import bots
        from run_bots import step
        aid=bots.create(self.path,self.owner,'market_bot','Market bot town',1000)
        bots.control(self.path,self.owner,aid,'start',1000)
        state=self.state(aid)
        observed=market.public_snapshot(self.path,state,1000)
        values=dict(rates={},market=observed,targets=[],account_id=aid,
                    settlement_id=state['settlement']['settlement_id'],
                    season_id=state['season']['season_id'],map_seed=state['season']['map_seed'])
        chosen=dict(route='/market',reason='Buy emergency water from reserve.',
                    form=dict(action='reserve_buy',resource='water',quantity=10))
        with patch('run_bots.time.time',return_value=1000), \
             patch('run_bots.choose',return_value=chosen) as policy, \
             patch('run_bots.request',side_effect=[(200,json.dumps(values).encode(),'refresh-id'),
                                                  (400,b'No allowance remains','market-id')]):
            step(self.path,'http://127.0.0.1:8767',dict(account_id=aid,seed=1,steps=0))
        self.assertEqual(policy.call_args.args[-1],observed)
        with closing(connect_database(self.path)) as c:
            row=c.execute('SELECT route,parameters,status,request_id FROM bot_decisions WHERE account_id=?',(aid,)).fetchone()
            self.assertEqual(row[0],'/market');self.assertEqual(json.loads(row[1]),chosen['form'])
            self.assertEqual(row[2:],(400,'market-id'))
