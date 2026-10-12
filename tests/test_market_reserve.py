"""Daily fallback supply uses disposable saves; no server is required."""
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import market, market_reserve
from game.settlement import read_state, account_scope
from tests import test_social as fixtures


class ReserveTests(unittest.TestCase):
    setUp = fixtures.SocialTests.setUp
    sql = fixtures.SocialTests.sql
    player = fixtures.SocialTests.player
    state = fixtures.SocialTests.state
    action = fixtures.SocialTests.action

    def buy(self, resource='scrap', quantity=1, aid=None):
        return self.action(market,aid or self.a,'reserve_buy',resource=resource,quantity=quantity)

    def test_goods_without_sellers_and_paired_credit_ledger(self):
        before = self.state(self.a)
        bank = self.sql('SELECT credits FROM season_bank')[0][0]
        self.buy(quantity=5)
        after = self.state(self.a)
        self.assertEqual(after['resources']['scrap'],before['resources']['scrap']+5)
        self.assertEqual(after['resources']['credits'],before['resources']['credits']-15)
        self.assertEqual(self.sql('SELECT credits FROM season_bank')[0][0],bank+15)
        self.assertEqual(self.sql("SELECT sum(amount),count(*) FROM credit_transactions WHERE transfer_ref='market-reserve:1'"),[(0,2)])
        self.assertEqual(self.sql('SELECT count(*) FROM market_listings'),[(0,)])

    def test_limit_is_independent_per_settlement_and_resource(self):
        # Leave room to purchase another resource after using Scrap allowance.
        self.sql('UPDATE settlement_resources SET scrap=100 WHERE settlement_id=?',(self.sa,))
        self.buy(quantity=20)
        with self.assertRaisesRegex(ValueError,'daily allowance'): self.buy()
        self.buy(aid=self.b,quantity=20)
        self.buy(resource='electronics',quantity=1)
        self.assertEqual(self.sql('SELECT count(*) FROM market_reserve_purchases'),[(3,)])

    def test_midnight_reset_does_not_accumulate(self):
        # Calendar rollover is independent of storage: both daily buys must fit.
        self.sql('UPDATE settlement_resources SET scrap=100 WHERE settlement_id=?',(self.sa,))
        # Isolate calendar accounting from a full day's survival simulation.
        def purchase(at,quantity):
            with account_scope(self.a),closing(connect_database(self.path)) as c,c:
                c.row_factory=sqlite3.Row
                c.execute('BEGIN IMMEDIATE')
                market_reserve.purchase(c,read_state(c),'scrap',quantity,at)
        purchase(86399,20)
        with self.assertRaisesRegex(ValueError,'daily allowance'): purchase(86399,1)
        purchase(86400,20)
        with self.assertRaisesRegex(ValueError,'daily allowance'): purchase(86400,1)
        with self.assertRaisesRegex(ValueError,'daily allowance'): purchase(4*86400,21)

    def test_rejections_preserve_balances_and_allowance(self):
        for resource,quantity in [('credits',1),('scrap',0),('scrap',True),('scrap',21)]:
            with self.assertRaises(ValueError): self.buy(resource,quantity)
        self.sql('UPDATE settlement_resources SET credits=0 WHERE settlement_id=?',(self.sa,))
        with self.assertRaises(ValueError): self.buy()
        self.sql('UPDATE settlement_resources SET credits=500,scrap=250,metal=0,electronics=0 WHERE settlement_id=?',(self.sa,))
        with self.assertRaises(ValueError): self.buy()
        self.sql('UPDATE settlement_resources SET scrap=0 WHERE settlement_id=?',(self.sa,))
        self.buy(quantity=20)
        self.assertEqual(self.sql('SELECT count(*) FROM market_reserve_purchases'),[(1,)])

    def test_disabled_and_paused_season_reject(self):
        config=market_reserve.settings();config['enabled']=False
        with patch('game.market_reserve.settings',return_value=config):
            with self.assertRaises(ValueError): self.buy()
        self.sql("UPDATE seasons SET status='paused',paused_at=1000")
        with self.assertRaises(ValueError): self.buy()

    def test_panel_is_read_only_and_history_survives_reopen(self):
        with account_scope(self.a):
            html=market.panel(self.path,self.state(self.a),'test-token',1000)
        self.assertIn('Daily market reserve',html)
        self.assertEqual(self.sql("SELECT count(*) FROM sqlite_master WHERE name='market_reserve_purchases'"),[(0,)])
        self.buy()
        with closing(connect_database(self.path)) as c:
            self.assertEqual(market_reserve.remaining(c,self.sa,0,market_reserve.settings())['scrap'],19)
        self.assertIn('Recent reserve purchases',market.panel(self.path,self.state(self.a),'test-token',1000))
