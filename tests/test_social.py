"""Disposable multiplayer economy, treaty and communication regression checks."""
from contextlib import closing
import http.client
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from database.create_database import connect_database
from game import accounts, market, diplomacy, communication, combat, trading
from game.settlement import account_scope, read_settlement
from game.simulation import advance_settlement
from accounts_app import AccountServer


class SocialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'social.db';accounts.prepare(self.path)
        self.a=self.player('alpha');self.b=self.player('bravo')
        self.sa=self.state(self.a)['settlement']['settlement_id'];self.sb=self.state(self.b)['settlement']['settlement_id']

    def sql(self,query,args=()):
        with closing(connect_database(self.path)) as c,c:return c.execute(query,args).fetchall()

    def player(self,name):
        # These tests exercise gameplay, not password hashing (covered by account tests).
        with closing(connect_database(self.path)) as c,c:
            aid=c.execute('INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES (?,\'fixture\',?,1000)',(name,name)).lastrowid
        accounts.join(self.path,aid,name,1000)
        return aid

    def state(self,aid):
        with account_scope(aid):return read_settlement(self.path)

    def action(self,module,aid,action,now=1000,**kwargs):
        with account_scope(aid):return module.transact(self.path,action,now,**kwargs)

    def listing(self,quantity=20,price=3):
        return self.action(market,self.a,'sell',resource='scrap',quantity=quantity)

    def treaty(self,kind='trade_agreement',now=1000):
        tid=self.action(diplomacy,self.a,'propose',now,target_id=self.sb,treaty_type=kind)
        self.action(diplomacy,self.b,'accept',now,treaty_id=tid)
        return tid

    def advance(self,aid,now):
        with account_scope(aid):return advance_settlement(self.path,now)

    def test_sales_remove_goods_and_cannot_spend_direct_trade_reservations(self):
        self.action(trading,self.a,'propose',recipient_id=self.sb,offered={'scrap':170},requested={'credits':1})
        with self.assertRaises(ValueError):self.listing(11)
        self.listing(10)
        self.assertEqual(self.state(self.a)['resources']['scrap'],170)
        self.assertEqual(self.state(self.a)['reserved'],{'scrap':170})
        self.assertEqual(self.sql('SELECT quantity FROM market_pool_stock'),[(10,)])

    def test_partial_purchase_conserves_goods_and_credit_ledger(self):
        bank=self.sql('SELECT credits FROM season_bank')[0][0]
        self.listing(20)
        self.action(market,self.b,'buy',resource='scrap',quantity=5)
        a,b=self.state(self.a),self.state(self.b)
        self.assertEqual((a['resources']['scrap'],b['resources']['scrap']),(160,185))
        self.assertEqual((a['resources']['credits'],b['resources']['credits']),(536,485))
        self.assertEqual(self.sql('SELECT quantity FROM market_pool_stock'),[(15,)])
        self.assertEqual(self.sql('SELECT credits FROM season_bank')[0][0],bank-21)
        self.assertEqual(self.sql("SELECT sum(amount) FROM credit_transactions WHERE transfer_ref LIKE 'market-pool:%'"),[(0,)])
        self.action(market,self.b,'buy',resource='scrap',quantity=15)
        with self.assertRaises(ValueError):self.action(market,self.b,'buy',resource='scrap',quantity=1)
        accounts.prepare(self.path)
        self.assertEqual(self.sql('SELECT count(*) FROM market_pool_trades'),[(3,)])

    def test_market_post_discount_rounding_and_no_treaty_discount(self):
        self.treaty()
        with patch('game.support.best',return_value=28):
            self.assertEqual(market.selling_fee(self.state(self.a),1000),58)
        with patch('game.support.best',return_value=99):
            self.assertEqual(market.selling_fee(self.state(self.a),1000),20)
        self.listing(10)
        self.assertEqual(self.sql('SELECT fee FROM market_pool_trades'),[(2,)])

    def test_bad_values_stale_listing_forms_and_unaffordable_are_atomic(self):
        for value in (0,-1,1.5,True,float('nan'),1_000_000_001):
            with self.assertRaises(ValueError):self.action(market,self.a,'sell',resource='scrap',quantity=value)
        with self.assertRaises(ValueError):self.action(market,self.a,'sell',resource='credits',quantity=1)
        with self.assertRaises(ValueError):self.action(market,self.a,'list',resource='scrap',quantity=1,unit_price=2)
        self.listing(10)
        for kwargs in ({'listing_id':1,'quantity':1},{'resource':'scrap','quantity':11}):
            with self.assertRaises(ValueError):self.action(market,self.b,'buy',**kwargs)
        self.sql('UPDATE settlement_resources SET credits=0 WHERE settlement_id=?',(self.sb,))
        with self.assertRaises(ValueError):self.action(market,self.b,'buy',resource='scrap',quantity=1)
        self.assertEqual(self.sql('SELECT quantity FROM market_pool_stock'),[(10,)])

    def test_storage_limit_and_credits_reserved_in_trade(self):
        self.listing(100)
        with self.assertRaises(ValueError):self.action(market,self.b,'buy',resource='scrap',quantity=100)
        self.action(trading,self.b,'propose',recipient_id=self.sa,offered={'credits':500},requested={'water':1})
        with self.assertRaises(ValueError):self.action(market,self.b,'buy',resource='scrap',quantity=1)

    def test_sales_are_not_listing_limited_and_final_window_is_enforced(self):
        for _ in range(21):self.listing(1)
        self.sql('UPDATE seasons SET ends_at=2000,finalization_at=1900')
        for action in ('buy','sell','reserve_buy'):
            with self.assertRaises(ValueError):self.action(market,self.b,action,1900,resource='scrap',quantity=1)

    def test_suspended_seller_cannot_sell(self):
        self.sql("UPDATE settlements SET status='suspended',suspended_at=1000 WHERE settlement_id=?",(self.sa,))
        with self.assertRaises(ValueError):self.listing()

    def test_market_rollback_on_ledger_failure(self):
        self.listing();a,b=self.state(self.a),self.state(self.b)
        self.sql("CREATE TRIGGER fail_market BEFORE INSERT ON credit_transactions WHEN NEW.transaction_type='market' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.action(market,self.b,'buy',resource='scrap',quantity=1)
        self.assertEqual(a,self.state(self.a));self.assertEqual(b,self.state(self.b))
        self.assertEqual(self.sql('SELECT quantity FROM market_pool_stock'),[(20,)])
        self.assertEqual(self.sql('SELECT count(*) FROM market_pool_trades'),[(1,)])

    def test_concurrent_purchase_has_only_one_winner(self):
        self.listing(1);results=[]
        def buy():
            try:self.action(market,self.b,'buy',resource='scrap',quantity=1);results.append('ok')
            except ValueError:results.append('closed')
        threads=[threading.Thread(target=buy) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertCountEqual(results,['ok','closed'])
        self.assertEqual(self.sql('SELECT quantity FROM market_pool_stock'),[(0,)])
        self.assertEqual(self.sql('SELECT count(*) FROM market_pool_trades'),[(2,)])

    def test_season_end_preserves_pool_history_and_archives_players(self):
        self.listing();self.sql('UPDATE seasons SET ends_at=1100,finalization_at=1050')
        self.advance(self.a,1100)
        self.assertEqual(self.state(self.a)['reserved'],{})
        self.assertEqual(self.sql('SELECT quantity FROM market_pool_stock'),[(20,)])
        self.assertEqual(self.state(self.b)['settlement']['status'],'archived')
        with self.assertRaises(ValueError):self.action(market,self.a,'buy',1100,resource='scrap',quantity=1)

    def test_treaties_coexist_require_acceptance_and_validate_roles(self):
        tid=self.action(diplomacy,self.a,'propose',target_id=self.sb,treaty_type='peace')
        with self.assertRaises(ValueError):self.action(diplomacy,self.a,'accept',treaty_id=tid)
        with self.assertRaises(ValueError):self.action(diplomacy,self.a,'propose',target_id=self.sb,treaty_type='peace')
        self.action(diplomacy,self.b,'accept',treaty_id=tid);self.treaty()
        self.assertEqual(self.sql("SELECT count(*) FROM treaties WHERE status='active'"),[(2,)])
        with self.assertRaises(ValueError):self.action(diplomacy,self.b,'accept',treaty_id=tid)
        with self.assertRaises(ValueError):self.action(diplomacy,self.a,'propose',target_id=self.sb,treaty_type='mutual_defense')

    def test_peace_acceptance_recalls_inbound_attack_and_ends_war(self):
        with account_scope(self.a):combat.command(self.path,'declare',1000,target_id=self.sb)
        # A real finite missile is unnecessary here; recall logic is separately covered.
        sid=self.state(self.a)['season']['season_id']
        self.sql("INSERT INTO attacks(season_id,attacker_settlement_id,defender_settlement_id,launched_at,resolves_at,status,raid_objective,random_seed) VALUES (?,?,?,1000,5000,'in_flight','scrap','fixture')",(sid,self.sa,self.sb))
        self.sql('UPDATE settlements SET attacks_remaining=2 WHERE settlement_id=?',(self.sa,))
        self.treaty('peace')
        self.assertEqual(self.sql('SELECT status,allowance_refunded FROM attacks'),[('cancelled',1)])
        self.assertEqual(self.state(self.a)['settlement']['attacks_remaining'],3)
        self.assertEqual(self.sql("SELECT status FROM treaties WHERE treaty_type='war'"),[('cancelled',)])
        with account_scope(self.a),self.assertRaises(ValueError):combat.command(self.path,'declare',1000,target_id=self.sb)

    def test_cancellation_cooldowns_block_hostility_and_reproposal(self):
        tid=self.treaty('peace');self.action(diplomacy,self.b,'cancel',treaty_id=tid)
        with self.assertRaises(ValueError):self.action(diplomacy,self.a,'propose',target_id=self.sb,treaty_type='peace')
        with account_scope(self.a),self.assertRaises(ValueError):combat.command(self.path,'declare',22599,target_id=self.sb)
        with account_scope(self.a):combat.command(self.path,'declare',22600,target_id=self.sb)
        tid=self.treaty('non_aggression',22600);self.action(diplomacy,self.b,'cancel',22600,treaty_id=tid)
        self.assertEqual(self.sql('SELECT cooldown_until FROM treaties WHERE treaty_id=?',(tid,)),[(65800,)])

    def test_proposal_expiry_boundary_reject_cancel_and_third_player(self):
        third=self.player('charlie');self.sql("UPDATE settlements SET status='suspended',suspended_at=1000");
        for sid in (self.sa,self.sb):
            self.sql("INSERT INTO game_events(season_id,settlement_id,event_type,occurred_at,event_data) SELECT season_id,settlement_id,'prototype_supply_pause',1000,'{}' FROM settlements WHERE settlement_id=?",(sid,))
        tid=self.action(diplomacy,self.a,'propose',target_id=self.sb,treaty_type='peace')
        with self.assertRaises(ValueError):self.action(diplomacy,third,'accept',treaty_id=tid)
        with self.assertRaises(ValueError):self.action(diplomacy,self.b,'cancel',treaty_id=tid)
        with self.assertRaises(ValueError):self.action(diplomacy,self.b,'accept',173800,treaty_id=tid)
        self.advance(self.a,173800)
        self.assertEqual(self.sql('SELECT status FROM treaties'),[('expired',)])
        tid=self.action(diplomacy,self.a,'propose',173800,target_id=self.sb,treaty_type='peace')
        self.action(diplomacy,self.b,'reject',173800,treaty_id=tid)
        self.assertEqual(self.sql('SELECT status FROM treaties WHERE treaty_id=?',(tid,)),[('rejected',)])

    def test_private_message_persistence_read_archive_and_no_third_party_access(self):
        third=self.player('charlie')
        mid=self.action(communication,self.a,'send',target_id=self.sb,subject='Private plan',body='Only bravo can see this.')
        with self.assertRaises(ValueError):self.action(communication,third,'read',message_id=mid)
        with self.assertRaises(ValueError):self.action(communication,self.a,'read',message_id=mid)
        self.action(communication,self.b,'read',1001,message_id=mid);self.action(communication,self.b,'read',1002,message_id=mid)
        self.assertEqual(self.sql('SELECT read_at FROM private_messages'),[(1001,)])
        self.action(communication,self.a,'archive',1002,message_id=mid)
        html=communication.panel(self.path,self.state(self.b),'token',1002)
        self.assertIn('Only bravo can see this.',html)
        self.assertNotIn('Only bravo can see this.',communication.panel(self.path,self.state(third),'token',1002))
        self.action(communication,self.b,'archive',1002,message_id=mid)
        archived=communication.panel(self.path,self.state(self.b),'token',1002)
        self.assertNotIn('Only bravo can see this.',archived.split('<h3>Archived inbox</h3>')[0])
        self.assertIn('Only bravo can see this.',archived.split('<h3>Archived inbox</h3>')[1])
        accounts.prepare(self.path);self.assertEqual(self.sql('SELECT count(*) FROM private_messages'),[(1,)])

    def test_messages_escape_markup_and_reject_invalid_text(self):
        self.action(communication,self.a,'send',target_id=self.sb,subject='<script>hello</script>',body='<img src=x onerror=alert(1)>')
        html=communication.panel(self.path,self.state(self.b),'token',1000)
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<img src=x',html)
        for body in ('','x'*1001,'hello\x00there'):
            with self.assertRaises(ValueError):self.action(communication,self.a,'send',target_id=self.sb,subject='hello',body=body)
        with self.assertRaises(ValueError):self.action(communication,self.a,'send',target_id=self.sa,subject='hello',body='body')

    def test_board_is_public_moderation_private_and_audited(self):
        pid=self.action(communication,self.a,'post',body='A public hello')
        self.assertIn('A public hello',communication.panel(self.path,self.state(self.b),'token',1000))
        with self.assertRaises(ValueError):self.action(communication,self.b,'hide',post_id=pid,reason='test')
        self.sql('UPDATE accounts SET is_admin=1 WHERE account_id=?',(self.b,))
        with self.assertRaises(ValueError):self.action(communication,self.b,'hide',post_id=pid,reason='test moderation')
        from game import admin
        admin.transact(self.path,self.b,'hide_post',1000,target=pid,reason='test moderation')
        self.assertNotIn('A public hello',communication.panel(self.path,self.state(self.a),'token',1000))
        self.assertNotIn('A public hello',communication.panel(self.path,self.state(self.b),'token',1000))
        self.assertIn('A public hello',admin.panel(self.path,self.b,'token'))
        self.assertNotIn('Moderate post',communication.panel(self.path,self.state(self.b),'token',1000))
        self.assertEqual(self.sql('SELECT count(*) FROM admin_actions'),[(1,)])
        with self.assertRaises(ValueError):self.action(communication,self.b,'restore',post_id=pid,reason='restore')
        admin.transact(self.path,self.b,'restore_post',1000,target=pid,reason='restore')
        self.assertIn('A public hello',communication.panel(self.path,self.state(self.a),'token',1000))

    def test_communication_rate_limits_and_notifications(self):
        for _ in range(20):self.action(communication,self.a,'send',target_id=self.sb,subject='hi',body='hello')
        with self.assertRaises(ValueError):self.action(communication,self.a,'send',target_id=self.sb,subject='hi',body='hello')
        self.action(communication,self.a,'send',1060,target_id=self.sb,subject='hi',body='hello')
        self.action(communication,self.b,'read_notifications',1060)
        self.assertEqual(self.sql('SELECT count(*) FROM notifications WHERE read_at IS NULL'),[(0,)])

    def test_communication_survives_pause_but_finished_season_is_read_only(self):
        self.sql("UPDATE seasons SET status='paused',paused_at=1000")
        self.action(communication,self.a,'post',body='Paused hello')
        with self.assertRaises(ValueError):self.listing()
        self.sql("UPDATE seasons SET status='finished'")
        with self.assertRaises(ValueError):self.action(communication,self.a,'post',body='too late')

    def test_refresh_changes_for_incoming_mail_market_treaties_and_board(self):
        state=self.state(self.b);before=communication.revision(self.path,state,1000)
        self.action(communication,self.a,'send',target_id=self.sb,subject='hi',body='hello')
        after=communication.revision(self.path,state,1000);self.assertNotEqual(before,after)
        self.listing();next_revision=communication.revision(self.path,state,1000);self.assertNotEqual(after,next_revision)
        self.treaty();after=communication.revision(self.path,state,1000);self.assertNotEqual(next_revision,after)
        self.action(communication,self.a,'post',body='hello world');self.assertNotEqual(after,communication.revision(self.path,state,1000))


class SocialHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'http.db';accounts.prepare(self.path)
        self.server=AccountServer(('127.0.0.1',0),self.path,clock=lambda:1000)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.stop)
        self.a,self.ta=self.player('alpha');self.b,self.tb=self.player('bravo')

    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,method='GET',path='/',fields=None,cookie='',headers=None):
        c=http.client.HTTPConnection(*self.server.server_address);h={'Cookie':cookie};body=urlencode(fields) if fields is not None else None
        if body is not None:h['Content-Type']='application/x-www-form-urlencoded'
        h.update(headers or {});c.request(method,path,body,h);r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read().decode());c.close();return result

    def player(self,name):
        # Create an authenticated fixture session; old HTTP tests cover registration.
        with closing(connect_database(self.path)) as c,c:aid=c.execute("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES (?,'fixture',?,1000)",(name,name)).lastrowid
        accounts.join(self.path,aid,name,1000);token,session=accounts.new_session(self.path,aid,1000)
        return 'settlement_session='+token,session['csrf']

    def test_forms_market_diplomacy_and_message_round_trip(self):
        html=self.request(cookie=self.a)[2]
        for label in ('Public market','Diplomacy','Player messages','Season message board'):self.assertIn(label,html)
        self.assertEqual(self.request('POST','/market',{'token':self.ta,'action':'sell','resource':'scrap','quantity':10},self.a)[0],303)
        self.assertEqual(self.request('POST','/market',{'token':self.tb,'action':'buy','resource':'scrap','quantity':2},self.b)[0],303)
        self.assertEqual(self.request('POST','/diplomacy',{'token':self.ta,'action':'propose','target_id':2,'treaty_type':'peace'},self.a)[0],303)
        self.assertEqual(self.request('POST','/diplomacy',{'token':self.tb,'action':'accept','treaty_id':1},self.b)[0],303)
        before=json.loads(self.request(path='/api/resources',cookie=self.b)[2])['revision']
        self.assertEqual(self.request('POST','/communication',{'token':self.ta,'action':'send','target_id':2,'subject':'Hello','body':'Trade with me?'},self.a)[0],303)
        html=self.request(cookie=self.b)[2];self.assertIn('Trade with me?',html)
        after=json.loads(self.request(path='/api/resources',cookie=self.b)[2])['revision']
        self.assertNotEqual(before,after);self.assertEqual(re.search('data-revision="([^"]*)"',html)[1],after)

    def test_auth_origin_csrf_duplicate_and_bad_numbers_rejected(self):
        for route in ('market','diplomacy','communication'):
            self.assertEqual(self.request('POST','/'+route,{'action':'list'})[0],403)
            fields={'token':self.ta,'action':'bad'}
            self.assertEqual(self.request('POST','/'+route,fields,self.a,{'Origin':'https://wrong.invalid'})[0],403)
            self.assertEqual(self.request('POST','/'+route,dict(fields,token=self.tb),self.a)[0],403)
            self.assertEqual(self.request('POST','/'+route,[('token',self.ta),('action','post'),('action','send')],self.a)[0],400)
        self.assertEqual(self.request('POST','/market',{'token':self.ta,'action':'sell','resource':'scrap','quantity':'nan'},self.a)[0],400)


if __name__=='__main__':unittest.main()
