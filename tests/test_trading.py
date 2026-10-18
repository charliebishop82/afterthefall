"""Atomic exchanges, reservations, elapsed time, ownership and HTTP regressions."""
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
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from database.create_database import connect_database
from game import accounts, trading
from game.settlement import account_scope, read_settlement, load_config
from game.simulation import advance_settlement
from game.buildings import change_building
from game.economy import advance_resources, rates
from accounts_app import AccountServer
from tests.fixtures import restore_case_baseline


class TradingTests(unittest.TestCase):
    def setUp(self):
        seed = patch('game.scavenging.secrets.token_hex', return_value='0123456789abcdef0123456789abcdef')
        seed.start(); self.addCleanup(seed.stop)
        restore_case_baseline(self,'trading',TradingTests.prepare_world)

    def prepare_world(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'trading.db'
        accounts.prepare(self.path)
        self.a = self.player('alpha'); self.b = self.player('bravo')
        self.sa = self.state(self.a)['settlement']['settlement_id']
        self.sb = self.state(self.b)['settlement']['settlement_id']

    def player(self, name):
        aid = accounts.register(self.path, name, 'long-test-password', 1000)
        accounts.join(self.path, aid, name, 1000)
        return aid

    def sql(self, query, values=()):
        with closing(connect_database(self.path)) as c, c:
            return c.execute(query, values).fetchall()

    def state(self, aid):
        with account_scope(aid): return read_settlement(self.path)

    def action(self, aid, action, now=1000, **kwargs):
        with account_scope(aid): return trading.transact(self.path, action, now, **kwargs)

    def offer(self, offered=None, requested=None, now=1000):
        return self.action(self.a, 'propose', now, recipient_id=self.sb,
                           offered=offered or {'scrap': 20}, requested=requested or {'credits': 50})

    def advance(self, aid, now):
        with account_scope(aid): return advance_settlement(self.path, now)

    def test_rules_match_current_workbook(self):
        workbook = Path(__file__).resolve().parents[1] / 'sources' / load_config('prototype_v8')['sources']['workbook']
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        found = {}
        with ZipFile(workbook) as z:
            for name in z.namelist():
                if not name.startswith('xl/worksheets/sheet') or not name.endswith('.xml'): continue
                for row in ET.fromstring(z.read(name)).findall('.//s:row', ns):
                    cells = {''.join(filter(str.isalpha, c.get('r'))): ''.join(c.itertext()) if c.get('t') == 'inlineStr' else c.findtext('s:v', '', ns) for c in row}
                    if cells.get('A', '').startswith('direct_trade_'): found[cells['A']] = float(cells['D'])
        self.assertEqual(found['direct_trade_fee'], 0)
        self.assertEqual(found['direct_trade_expiry'] * 3600, trading.EXPIRY_SECONDS)
        self.assertEqual(found['direct_trade_max_open'], trading.MAX_OPEN)

    def test_offer_reserves_stock_without_removing_storage_usage(self):
        before = self.state(self.a)['resources']; tid = self.offer()
        after = self.state(self.a)
        self.assertEqual(before, after['resources'])
        self.assertEqual(after['reserved'], {'scrap': 20})
        self.assertEqual(trading.available(after, 'scrap'), 160)
        self.assertEqual(self.sql('SELECT expires_at FROM trade_proposals WHERE trade_id=?', (tid,))[0][0], 87400)
        self.assertEqual(self.state(self.b)['reserved'], {})

    def test_atomic_exchange_multi_resource_credits_ledger_persistence_and_repeat(self):
        tid = self.offer({'scrap': 20, 'food': 5}, {'credits': 50, 'metal': 10})
        self.action(self.b, 'accept', trade_id=tid)
        a, b = self.state(self.a), self.state(self.b)
        self.assertEqual((a['resources']['scrap'], b['resources']['scrap']), (160, 200))
        self.assertEqual((a['resources']['metal'], b['resources']['metal']), (50, 30))
        self.assertEqual((a['resources']['credits'], b['resources']['credits']), (550, 450))
        self.assertEqual((a['resources']['food'], b['resources']['food']), (115, 125))
        self.assertEqual(a['reserved'], {})
        self.assertEqual(self.sql("SELECT amount FROM credit_transactions WHERE transaction_type='direct_trade' ORDER BY transaction_id"), [(50,), (-50,)])
        accounts.prepare(self.path)
        self.assertEqual(a, self.state(self.a))
        for actor, action in [(self.b, 'accept'), (self.a, 'cancel'), (self.b, 'reject')]:
            with self.assertRaises(ValueError): self.action(actor, action, trade_id=tid)
        self.assertEqual(a, self.state(self.a)); self.assertEqual(b, self.state(self.b))

    def test_insufficient_recipient_resources_leaves_everything_unchanged(self):
        tid = self.offer(requested={'credits': 501}); a, b = self.state(self.a), self.state(self.b)
        with self.assertRaises(ValueError): self.action(self.b, 'accept', trade_id=tid)
        self.assertEqual(a, self.state(self.a)); self.assertEqual(b, self.state(self.b))
        self.assertEqual(self.sql('SELECT status FROM trade_proposals')[0][0], 'pending')

    def test_storage_revalidated_and_counts_other_reservations(self):
        tid = self.offer({'scrap': 30}, {'credits': 1})
        with self.assertRaisesRegex(ValueError, 'storage'): self.action(self.b, 'accept', trade_id=tid)
        self.assertEqual(self.sql('SELECT status FROM trade_proposals')[0][0], 'pending')
        self.sql('UPDATE settlement_resources SET scrap=150 WHERE settlement_id=?', (self.sb,))
        self.action(self.b, 'accept', trade_id=tid)
        self.assertEqual(self.state(self.b)['resources']['scrap'], 180)

    def test_exchange_checks_net_capacity_not_gross_incoming(self):
        tid = self.offer({'scrap': 40}, {'metal': 40})
        self.action(self.b, 'accept', trade_id=tid)
        self.assertEqual(sum(self.state(self.b)['resources'][r] for r in ('scrap','metal','electronics')), 230)

    def test_cancel_and_reject_release_exactly_once(self):
        for action, actor in [('cancel', self.a), ('reject', self.b)]:
            tid = self.offer(); a, b = self.state(self.a)['resources'], self.state(self.b)['resources']
            self.action(actor, action, trade_id=tid)
            self.assertEqual(self.state(self.a)['reserved'], {})
            self.assertEqual(a, self.state(self.a)['resources']); self.assertEqual(b, self.state(self.b)['resources'])
            with self.assertRaises(ValueError): self.action(actor, action, trade_id=tid)

    def test_wrong_party_and_third_party_cannot_modify_trade(self):
        tid = self.offer(); third = self.player('charlie')
        for actor, action in [(self.a, 'accept'), (self.a, 'reject'), (self.b, 'cancel'), (third, 'accept'), (third, 'cancel')]:
            with self.assertRaises(ValueError): self.action(actor, action, trade_id=tid)
        self.assertEqual(self.sql('SELECT status FROM trade_proposals')[0][0], 'pending')
        self.assertNotIn('#' + str(tid) + ':', trading.panel(self.path, self.state(third), 'token'))

    def test_invalid_self_missing_and_inactive_targets(self):
        for recipient in (self.sa, 999):
            with self.assertRaises(ValueError): self.action(self.a, 'propose', recipient_id=recipient, offered={'scrap': 1}, requested={'credits': 1})
        self.sql('UPDATE accounts SET is_active=0 WHERE account_id=?', (self.b,))
        with self.assertRaises(ValueError): self.offer()
        self.assertEqual(self.sql('SELECT count(*) FROM trade_proposals')[0][0], 0)

    def test_invalid_quantities_and_overcommitted_stock(self):
        for items in ({}, {'scrap': 0}, {'scrap': -1}, {'scrap': float('nan')}, {'scrap': float('inf')}, {'credits': .5}, {'gold': 2}, {'scrap': True}, {'scrap': 1_000_000_001}):
            with self.assertRaises(ValueError): self.action(self.a, 'propose', recipient_id=self.sb, offered=items, requested={'credits': 1})
        self.offer({'scrap': 170})
        with self.assertRaises(ValueError): self.offer({'scrap': 11})
        self.assertEqual(self.sql('SELECT count(*) FROM trade_proposals')[0][0], 1)

    def test_ten_outgoing_limit_and_release_slot(self):
        tids = [self.offer({'credits': 1}, {'scrap': 1}) for _ in range(10)]
        with self.assertRaisesRegex(ValueError, 'ten'): self.offer({'credits': 1}, {'scrap': 1})
        self.action(self.a, 'cancel', trade_id=tids[0]); self.offer({'credits': 1}, {'scrap': 1})
        self.assertEqual(self.state(self.a)['reserved'], {'credits': 10})

    def test_reserved_materials_cannot_be_spent_on_building_or_repairs(self):
        self.offer({'scrap': 170})
        self.sql("UPDATE settlement_derelicts SET status='cleared' WHERE settlement_id=?", (self.sa,))
        with account_scope(self.a):
            with self.assertRaisesRegex(ValueError, 'materials'): change_building(self.path, 'build', building_type='garden', x=21, y=18, rotation=0, now=1000)
        hp=load_config('prototype_v8')['buildings']['garden']['levels'][0]['hp']
        bid=self.sql("INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at) VALUES (?,'garden',1,21,18,?,'active',1000,1000) RETURNING building_id",(self.sa,hp*.1))[0][0]
        with account_scope(self.a):
            with self.assertRaisesRegex(ValueError, 'materials'): change_building(self.path, 'repair', building_id=bid, now=1000)
        self.assertEqual(self.state(self.a)['resources']['scrap'], 180)

    def test_reserved_materials_are_not_converted(self):
        self.offer({'scrap': 180})
        c = self.state(self.a)['citizens'][1]['citizen_id']
        spec = load_config('prototype_v8')['buildings']['recycler']['levels'][0]
        bid = self.sql('''INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at)
            VALUES (?,'recycler',1,21,18,?,'active',1000,1000) RETURNING building_id''', (self.sa, spec['hp']))[0][0]
        self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,?,'production',?,1000)", (c,self.sa,bid))
        state = self.advance(self.a, 4600)
        self.assertEqual(state['resources']['scrap'], 180)
        self.assertEqual(state['resources']['metal'], 40)

    def test_reserved_food_is_not_eaten_and_cancel_resumes_supply_freeze(self):
        tid = self.offer({'food': 119}, {'credits': 1})
        state = self.advance(self.a, 4600)
        self.assertEqual(state['settlement']['status'], 'suspended')
        self.assertAlmostEqual(state['resources']['food'], 119)
        frozen_at = state['settlement']['simulation_processed_at']
        self.action(self.a, 'cancel', now=5000, trade_id=tid)
        state = self.state(self.a)
        self.assertEqual(state['settlement']['status'], 'active')
        self.assertEqual(state['settlement']['simulation_processed_at'], 5000)
        self.assertEqual(state['recovery_clock']['anchor'], 1000+5000-frozen_at)
        self.assertEqual(state['season']['ends_at'], 1000+30*86400)

    def test_reserved_water_is_not_drunk(self):
        self.offer({'water': 119}, {'credits': 1})
        state = self.advance(self.a, 4600)
        self.assertEqual(state['settlement']['status'], 'suspended')
        self.assertEqual(state['resources']['water'], 119)

    def test_expiry_exact_boundary_and_no_offline_retroactive_consumption(self):
        tid = self.offer({'food': 100}, {'credits': 1})
        state = self.advance(self.a, 87400)
        self.assertEqual(state['reserved'], {})
        self.assertEqual(state['resources']['food'], 100)
        self.assertEqual(state['settlement']['status'], 'active')
        self.assertEqual(state['settlement']['simulation_processed_at'], 87400)
        self.assertEqual(self.sql('SELECT status,completed_at FROM trade_proposals WHERE trade_id=?', (tid,))[0], ('expired',87400))
        self.assertEqual(state, self.advance(self.a,87400))

    def test_active_expiry_splits_elapsed_time_consistently(self):
        tid = self.offer({'scrap': 10})
        self.advance(self.a, 87399)
        self.assertEqual(self.state(self.a)['reserved'], {'scrap': 10})
        state = self.advance(self.a, 87400)
        self.assertEqual(state['reserved'], {})
        self.assertEqual(self.sql('SELECT status FROM trade_proposals WHERE trade_id=?',(tid,))[0][0], 'expired')

    def test_recipient_read_expires_offline_proposers_offer(self):
        tid=self.offer({'food':119},{'credits':1})
        self.advance(self.b,87400)
        self.assertEqual(self.sql('SELECT status FROM trade_proposals WHERE trade_id=?',(tid,))[0][0],'expired')
        self.assertEqual(self.state(self.a)['reserved'],{})
        self.assertEqual(self.state(self.a)['resources']['food'],119)

    def test_storage_damage_preserves_committed_food(self):
        self.offer({'food':119},{'credits':1})
        self.sql('UPDATE buildings SET current_hp=100 WHERE settlement_id=?',(self.sa,))
        state=self.advance(self.a,2000)
        self.assertEqual(state['resources']['food'],119)
        self.assertEqual(state['reserved'],{'food':119})

    def test_recipient_other_pending_offer_cannot_be_double_spent(self):
        self.action(self.b,'propose',recipient_id=self.sa,offered={'credits':490},requested={'scrap':1})
        tid=self.offer(requested={'credits':20})
        with self.assertRaisesRegex(ValueError,'available'):self.action(self.b,'accept',trade_id=tid)
        self.assertEqual(self.state(self.b)['resources']['credits'],500)

    def test_broken_reservation_rejected_without_partial_transfer(self):
        tid=self.offer()
        self.sql('UPDATE resource_reservations SET quantity=19 WHERE trade_proposal_id=?',(tid,))
        before=self.state(self.a)['resources'],self.state(self.b)['resources']
        with self.assertRaisesRegex(ValueError,'reservation'):self.action(self.b,'accept',trade_id=tid)
        self.assertEqual(before,(self.state(self.a)['resources'],self.state(self.b)['resources']))

    def test_cannot_accept_expired_trade_and_end_releases_all_reservations(self):
        tid = self.offer()
        self.action(self.b, 'accept', now=87400, trade_id=tid)
        self.assertEqual(self.sql('SELECT status FROM trade_proposals')[0][0], 'expired')
        self.assertEqual(self.state(self.a)['resources']['credits'], 500)
        self.sql('UPDATE seasons SET finalization_at=87500,ends_at=87600')
        second=self.offer({'credits':1},{'scrap':1},now=87400)
        self.advance(self.a,87600)
        self.assertEqual(self.state(self.a)['reserved'], {})
        self.assertEqual(self.sql('SELECT status FROM trade_proposals WHERE trade_id=?',(second,))[0][0],'expired')

    def test_final_window_blocks_new_exchange_but_allows_cancel(self):
        tid = self.offer(); self.sql('UPDATE seasons SET finalization_at=1001')
        with self.assertRaisesRegex(ValueError, 'final three'): self.offer(now=1001)
        with self.assertRaisesRegex(ValueError, 'final three'): self.action(self.b,'accept',now=1001,trade_id=tid)
        self.action(self.a,'cancel',now=1001,trade_id=tid)
        self.assertEqual(self.state(self.a)['reserved'], {})

    def test_trade_supplies_resume_only_shortage_frozen_settlement(self):
        self.sql('UPDATE settlement_resources SET food=.01 WHERE settlement_id=?', (self.sb,))
        self.advance(self.b,1060)
        self.assertEqual(self.state(self.b)['settlement']['status'],'suspended')
        tid=self.offer({'food':20},{'credits':1},now=1100)
        self.action(self.b,'accept',now=1100,trade_id=tid)
        self.assertEqual(self.state(self.b)['settlement']['status'],'active')
        self.assertEqual(self.state(self.b)['resources']['food'],20)
        self.assertGreater(self.advance(self.b,1160)['citizens'][0]['xp'],0)
        self.sql("UPDATE settlements SET status='suspended',suspended_at=1160 WHERE settlement_id=?",(self.sb,))
        with self.assertRaisesRegex(ValueError,'suspended'): self.offer(now=1160)

    def test_failed_accept_rolls_back_both_advances(self):
        tid=self.offer(requested={'credits':501})
        a,b=self.state(self.a),self.state(self.b)
        with self.assertRaises(ValueError):self.action(self.b,'accept',now=1100,trade_id=tid)
        self.assertEqual(a,self.state(self.a));self.assertEqual(b,self.state(self.b))

    def test_concurrent_accept_has_one_exchange(self):
        tid=self.offer(); outcomes=[]
        def accept():
            try:self.action(self.b,'accept',trade_id=tid);outcomes.append('accepted')
            except ValueError:outcomes.append('rejected')
        threads=[threading.Thread(target=accept) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sorted(outcomes),['accepted','rejected'])
        self.assertEqual(self.state(self.a)['resources']['credits'],550)


class TradingHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'http.db';accounts.prepare(self.path)
        self.server=AccountServer(('127.0.0.1',0),self.path,clock=lambda:1000)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
        self.a,self.ta=self.player('alpha');self.b,self.tb=self.player('bravo')
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,method='GET',path='/',fields=None,cookie='',headers=None):
        c=http.client.HTTPConnection(*self.server.server_address);h={'Cookie':cookie};body=urlencode(fields) if fields is not None else None
        if body is not None:h['Content-Type']='application/x-www-form-urlencoded'
        h.update(headers or {});c.request(method,path,body,h);r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read().decode());c.close();return result
    def player(self,name):
        _,h,html=self.request();cookie=h['Set-Cookie'].split(';')[0];token=re.search('name="token" value="([^"]+)"',html)[1]
        _,h,_=self.request('POST','/register',{'token':token,'username':name,'password':'long-test-password'},cookie);cookie=h['Set-Cookie'].split(';')[0]
        _,_,html=self.request(cookie=cookie);token=re.search('name="token" value="([^"]+)"',html)[1]
        self.assertEqual(self.request('POST','/settlement',{'token':token,'name':name},cookie)[0],303)
        return cookie,token
    def test_browser_form_exchange_and_csrf_origin_guards(self):
        html=self.request(cookie=self.a)[2];self.assertIn('Player trading',html);self.assertIn('Propose trade',html)
        fields={'token':self.ta,'action':'propose','recipient_id':'2','offered_resource':'scrap','offered_quantity':'10','requested_resource':'credits','requested_quantity':'5'}
        self.assertEqual(self.request('POST','/trade',fields,self.a,{'Origin':'https://wrong.invalid'})[0],403)
        self.assertEqual(self.request('POST','/trade',dict(fields,token=self.tb),self.a)[0],403)
        initial=json.loads(self.request(path='/api/resources',cookie=self.b)[2])['revision']
        self.assertEqual(self.request('POST','/trade',fields,self.a)[0],303)
        payload=json.loads(self.request(path='/api/resources',cookie=self.b)[2])
        self.assertNotEqual(initial,payload['revision'])
        html=self.request(cookie=self.b)[2]
        self.assertEqual(re.search('data-revision="([^"]*)"',html)[1],payload['revision'])
        self.assertIn('Accept trade #1',self.request(cookie=self.b)[2])
        self.assertEqual(self.request('POST','/trade',{'token':self.tb,'action':'accept','trade_id':1},self.b)[0],303)
        self.assertIn('Accepted.',self.request(cookie=self.a)[2])
        self.assertEqual(self.request('POST','/trade',{'token':self.tb,'action':'accept','trade_id':1},self.b)[0],400)
    def test_bad_quantities_and_unauthed_trade_rejected(self):
        self.assertEqual(self.request('POST','/trade',{'action':'accept','trade_id':1})[0],403)
        for value in ('nan','inf','-1','junk'):
            fields={'token':self.ta,'action':'propose','recipient_id':2,'offered_resource':'scrap','offered_quantity':value,'requested_resource':'credits','requested_quantity':1}
            self.assertEqual(self.request('POST','/trade',fields,self.a)[0],400)
        with closing(connect_database(self.path)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM trade_proposals').fetchone()[0],0)


if __name__=='__main__':unittest.main()
