"""Pool migration, Bank ledger and daily-reserve independence."""
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch
from database.create_database import connect_database
from game import market,market_reserve,communication
from tests import test_social as fixtures


class PoolTests(unittest.TestCase):
    setUp=fixtures.SocialTests.setUp
    player=fixtures.SocialTests.player
    state=fixtures.SocialTests.state
    sql=fixtures.SocialTests.sql
    action=fixtures.SocialTests.action

    def test_migration_releases_unsold_stock_without_sale_or_credit_change(self):
        season=self.state(self.a)['season']['season_id']
        self.sql("INSERT INTO market_listings(season_id,seller_settlement_id,resource_type,original_quantity,remaining_quantity,unit_price,status,created_at) VALUES (?,?,'scrap',20,20,3,'open',1000)",(season,self.sa))
        self.sql("INSERT INTO resource_reservations(settlement_id,resource_type,quantity,market_listing_id,created_at) VALUES (?,'scrap',20,1,1000)",(self.sa,))
        before=self.state(self.a)['resources']
        with closing(connect_database(self.path)) as c,c:
            market.prepare(c,1000);market.prepare(c,1001)
        self.assertEqual(self.state(self.a)['resources'],before)
        self.assertEqual(self.state(self.a)['reserved'],{})
        self.assertEqual(self.sql('SELECT status,closed_at FROM market_listings'),[('cancelled',1000)])
        self.assertEqual(self.sql("SELECT count(*) FROM game_events WHERE event_type='market_listing_migrated'"),[(1,)])
        self.assertEqual(self.sql('SELECT count(*) FROM market_pool_stock'),[(0,)])
        self.assertEqual(self.sql('SELECT count(*) FROM market_pool_trades'),[(0,)])

    def test_reserve_and_shared_stock_have_independent_limits(self):
        # Make room for both 20-unit purchases without changing the real cap.
        self.sql('UPDATE settlement_resources SET scrap=100 WHERE settlement_id=?',(self.sb,))
        self.action(market,self.a,'sell',resource='scrap',quantity=20)
        self.action(market,self.b,'reserve_buy',resource='scrap',quantity=20)
        self.assertEqual(self.sql('SELECT quantity FROM market_pool_stock'),[(20,)])
        self.action(market,self.b,'buy',resource='scrap',quantity=20)
        self.assertEqual(self.sql('SELECT quantity FROM market_pool_stock'),[(0,)])
        self.assertEqual(self.state(self.b)['resources']['scrap'],140)
        with self.assertRaisesRegex(ValueError,'daily allowance'):self.action(market,self.b,'reserve_buy',resource='scrap',quantity=1)

    def test_sale_uses_existing_bank_ledger_even_with_negative_reserve(self):
        self.sql('UPDATE season_bank SET credits=0')
        before=self.state(self.a)['resources']['credits']
        self.action(market,self.a,'sell',resource='scrap',quantity=10)
        self.assertEqual(self.state(self.a)['resources']['credits'],before+18)
        self.assertEqual(self.sql('SELECT credits FROM season_bank'),[(-18,)])
        self.assertEqual(self.sql("SELECT sum(amount) FROM credit_transactions WHERE transfer_ref='market-pool:1'"),[(0,)])

    def test_no_free_stock_and_no_zero_proceeds_sale(self):
        with self.assertRaises(ValueError):self.action(market,self.a,'buy',resource='scrap',quantity=1)
        with self.assertRaises(ValueError):self.action(market,self.a,'sell',resource='water',quantity=1)
        self.action(market,self.a,'sell',resource='water',quantity=10)
        self.assertEqual(self.sql('SELECT fee,credit_amount FROM market_pool_trades'),[(1,9)])

    def test_prices_cannot_allow_pool_or_reserve_arbitrage(self):
        config=market.settings()
        config['scrap']['sell_price']=config['scrap']['buy_price']
        with patch('game.market.CONFIG') as path:
            import json
            path.read_text.return_value=json.dumps(config)
            with self.assertRaises(ValueError):market.settings()

    def test_inventory_is_scoped_to_season_and_refresh_notifies_other_players(self):
        state=self.state(self.b)
        revision=communication.revision(self.path,state,1000)
        self.action(market,self.a,'sell',resource='scrap',quantity=10)
        self.assertNotEqual(revision,communication.revision(self.path,state,1000))
        with closing(connect_database(self.path)) as c:
            self.assertEqual(market.stock(c,999999),dict.fromkeys(market.RESOURCES,0))

    def test_rollback_on_seller_ledger_failure(self):
        before=self.state(self.a)
        self.sql("CREATE TRIGGER fail_sell BEFORE INSERT ON credit_transactions WHEN NEW.transaction_type='market' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.action(market,self.a,'sell',resource='scrap',quantity=10)
        self.assertEqual(self.state(self.a),before)
        self.assertEqual(self.sql('SELECT count(*) FROM market_pool_stock'),[(0,)])

    def test_form_shows_both_markets_and_no_listing_controls(self):
        html=market.panel(self.path,self.state(self.a),'token',1000)
        self.assertIn('Shared inventory',html)
        self.assertIn('Daily market reserve',html)
        self.assertNotIn('List resources',html)
        self.assertIn('value="sell"',html)
