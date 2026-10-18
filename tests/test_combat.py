"""Disposable citizen-raid scenarios with controlled time and deterministic rolls."""
from contextlib import closing
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from database.create_database import connect_database
from game import accounts,combat,trading
from game.settlement import account_scope,read_settlement
from game.simulation import advance_settlement
from game.buildings import change_building
from accounts_app import AccountServer


from tests.fixtures import CombatFixture,CombatWorld

class CombatTests(CombatFixture, unittest.TestCase):
    def setUp(self):
        world=CombatWorld(self)
        self.__dict__.update({k:v for k,v in vars(world).items() if k!='addCleanup'})

    def test_source_values_match_current_workbook(self):
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};found={}
        workbook=Path(__file__).resolve().parents[1]/'sources'/'Post_Apocalyptic_Game_V1_Building_Settings(1).xlsx'
        with ZipFile(workbook) as z:
            sheets=ET.fromstring(z.read('xl/workbook.xml')).findall('.//s:sheet',ns)
            for i,sheet in enumerate(sheets,1):
                if sheet.attrib['name'] not in combat.settings():continue
                values={}
                for row in ET.fromstring(z.read(f'xl/worksheets/sheet{i}.xml')).findall('.//s:row',ns):
                    r={''.join(filter(str.isalpha,c.attrib['r'])):''.join(c.itertext()) if c.get('t')=='inlineStr' else c.findtext('s:v','',ns) for c in row}
                    try:values[r['A']]=float(r['D'])
                    except (KeyError,ValueError):pass
                found[sheet.attrib['name']]=values
        self.assertEqual(combat.settings(),found)
    def test_declaration_notifies_both_warning_and_duplicate(self):
        tid=self.action(self.a,'declare',target_id=self.sb)
        self.assertEqual(self.sql('SELECT effective_at FROM treaties WHERE treaty_id=?',(tid,))[0][0],4600)
        self.assertEqual(self.sql("SELECT count(*) FROM notifications WHERE notification_type='war_declared'")[0][0],2)
        ids=self.extra(self.sa)
        with self.assertRaises(ValueError):self.action(self.a,'launch',now=4599,target_id=self.sb,citizen_ids=ids)
        with self.assertRaises(ValueError):self.action(self.b,'declare',target_id=self.sa)
        self.assertEqual(len(self.sql('SELECT * FROM treaties')),1)
    def test_protection_and_six_home_floor(self):
        self.action(self.a,'declare',target_id=self.sb)
        cid=self.state(self.a)['citizens'][1]['citizen_id']
        with self.assertRaisesRegex(ValueError,'six'):self.action(self.a,'launch',now=4600,target_id=self.sb,citizen_ids=[cid])
        ids=self.extra(self.sa);self.sql('UPDATE settlements SET protection_until=4601 WHERE settlement_id=?',(self.sb,))
        with self.assertRaisesRegex(ValueError,'protected'):self.action(self.a,'launch',now=4600,target_id=self.sb,citizen_ids=ids)
        self.sql('UPDATE settlements SET protection_until=4600 WHERE settlement_id=?',(self.sb,))
        self.action(self.a,'launch',now=4600,target_id=self.sb,citizen_ids=ids)
        self.assertEqual(self.state(self.a)['settlement']['has_attacked'],1)
        self.assertEqual(self.state(self.a)['settlement']['protection_until'],4600)
    def test_unintegrated_low_hp_foreign_duplicate_and_working_citizens_rejected(self):
        self.action(self.a,'declare',target_id=self.sb);ids=self.extra(self.sa,2)
        self.advance(self.a,4600)
        for values in ([ids[0],ids[0]],[self.state(self.b)['citizens'][1]['citizen_id']],[self.state(self.a)['citizens'][0]['citizen_id']]):
            with self.assertRaises(ValueError):self.action(self.a,'launch',now=4600,target_id=self.sb,citizen_ids=values)
        self.sql('UPDATE citizens SET current_hp=24 WHERE citizen_id=?',(ids[0],))
        with self.assertRaisesRegex(ValueError,'25%'):self.action(self.a,'launch',now=4600,target_id=self.sb,citizen_ids=[ids[0]])
        self.sql('UPDATE citizens SET current_hp=25,integrated=0 WHERE citizen_id=?',(ids[0],))
        with self.assertRaisesRegex(ValueError,'integrated'):self.action(self.a,'launch',now=4600,target_id=self.sb,citizen_ids=[ids[0]])
        self.sql('UPDATE citizens SET integrated=1 WHERE citizen_id=?',(ids[0],));self.action(self.a,'launch',now=4600,target_id=self.sb,citizen_ids=[ids[0]])
    def test_unprotected_target_self_cross_season_and_invalid_objective(self):
        for target in (self.sa,999):
            with self.assertRaises(ValueError):self.action(self.a,'declare',target_id=target)
        ids=self.extra(self.sa);self.action(self.a,'declare',target_id=self.sb)
        with self.assertRaises(ValueError):self.action(self.a,'launch',now=4600,target_id=self.sb,citizen_ids=ids,objective='secret-inventory')
        self.assertEqual(len(self.sql('SELECT * FROM attacks')),0)
    def test_away_cannot_work_heal_or_double_commit_and_consumes_no_home_supplies(self):
        aid,ids=self.launch();before=self.state(self.a)
        self.assertEqual(len(combat.home(before)),6)
        self.sql('UPDATE citizens SET current_hp=70 WHERE citizen_id=?',(ids[0],))
        after=self.advance(self.a,4660)
        raider=next(c for c in after['citizens'] if c['citizen_id']==ids[0]);self.assertEqual(raider['current_hp'],70);self.assertEqual(raider['xp'],0)
        self.assertAlmostEqual(after['resources']['food']-before['resources']['food'],-4/60)
        with account_scope(self.a):
            from game.simulation import apply_action
            with self.assertRaisesRegex(ValueError,'away'):apply_action(self.path,'assign',citizen_id=ids[0],now=4660)
        with self.assertRaises(ValueError):self.action(self.a,'launch',now=4660,target_id=self.sb,citizen_ids=ids)
    def test_fixed_timer_anonymous_incoming_and_no_voluntary_recall(self):
        aid,ids=self.launch()
        self.assertEqual(self.sql('SELECT resolves_at FROM attacks')[0][0],8200)
        html=combat.panel(self.path,self.state(self.b),'token',4600)
        self.assertIn('Incoming hostile attack',html)
        # War notices name both parties, but the incoming countdown carries no composition/objective.
        incoming=html.split('Incoming hostile attack',1)[1].split('</p>',1)[0]
        self.assertNotIn('alpha',incoming);self.assertNotIn('scrap',incoming);self.assertNotIn('Test raider',incoming)
        with self.assertRaises(ValueError):self.action(self.a,'cancel',now=4600,target_id=self.sb)
        self.advance(self.b,8199);self.assertEqual(self.sql('SELECT status FROM attacks')[0][0],'in_flight')
    def test_defender_victory_injury_xp_returns_and_reports_private(self):
        aid,ids=self.launch();self.advance(self.b,8200)
        reports=self.reports();self.assertEqual(len(reports),2);report=reports[0]
        self.assertEqual(report['result'],'defender_win');self.assertEqual(report['attackers'][0]['hp_after'],70)
        self.assertEqual(report['defenders'][0]['hp_after'],90)
        self.assertEqual(report['loot']['taken'],{})
        c=next(c for c in self.state(self.a)['citizens'] if c['citizen_id']==ids[0]);self.assertEqual(c['xp'],10);self.assertFalse(c['away']);self.assertEqual(c['morale'],55)
        defender=next(c for c in self.state(self.b)['citizens'] if c['assignment']=='unassigned');self.assertEqual(defender['xp'],20)
        third,_=self.player('charlie');self.assertNotIn('Raid #',combat.panel(self.path,self.state(third),'token',8200))
        before=self.sql('SELECT count(*) FROM citizen_xp_events')[0][0];self.advance(self.a,8200);self.assertEqual(self.sql('SELECT count(*) FROM citizen_xp_events')[0][0],before)
    def test_attacker_victory_loot_overflow_loss_and_xp(self):
        self.weak_defense();aid,ids=self.launch();self.advance(self.a,8200)
        report=self.reports()[0];self.assertEqual(report['result'],'attacker_win')
        self.assertEqual(report['attackers'][0]['hp_after'],90)
        self.assertAlmostEqual(report['loot']['taken']['scrap'],12)
        self.assertEqual(report['loot']['deposited']['scrap'],12)
        self.assertEqual(self.state(self.a)['resources']['scrap'],192)
        self.assertEqual(self.state(self.b)['resources']['scrap'],168)
        self.assertEqual(next(c for c in self.state(self.a)['citizens'] if c['citizen_id']==ids[0])['xp'],20)
        notices=self.sql("SELECT account_id,message FROM notifications WHERE notification_type='raid_result' AND related_id=?",(aid,))
        self.assertEqual({n[0] for n in notices},{self.a,self.b});self.assertEqual(len(notices),2)
        self.advance(self.a,8200)
        self.assertEqual(self.sql("SELECT count(*) FROM notifications WHERE notification_type='raid_result' AND related_id=?",(aid,))[0][0],2)
    def test_storage_overflow_is_lost_and_reserved_defender_stock_is_safe(self):
        self.weak_defense();aid,ids=self.launch()
        self.sql('UPDATE settlement_resources SET scrap=200 WHERE settlement_id=?',(self.sa,))
        with account_scope(self.b):trading.transact(self.path,'propose',4600,recipient_id=self.sa,offered={'scrap':175},requested={'credits':1})
        self.advance(self.a,8200);report=self.reports()[0]
        self.assertEqual(report['loot']['taken']['scrap'],5)
        self.assertEqual(report['loot']['deposited']['scrap'],0)
        self.assertEqual(report['loot']['lost']['scrap'],5)
        self.assertEqual(self.state(self.b)['resources']['scrap'],175);self.assertEqual(self.state(self.b)['reserved'],{'scrap':175})
    def test_contested_injuries_and_no_loot(self):
        # Five raiders against five idle defenders; zero variance isolates the margin rule.
        aid,ids=self.launch(5)
        with patch('game.combat.random.Random') as rng:
            rng.return_value.uniform.return_value=1
            self.advance(self.a,8200)
        report=self.reports()[0];self.assertEqual(report['result'],'contested')
        self.assertEqual(report['attackers'][0]['hp_after'],80);self.assertEqual(report['defenders'][0]['hp_after'],80)
        self.assertEqual(report['loot']['taken'],{})
    def test_protection_suspend_or_peace_recall_and_refund_once(self):
        aid,ids=self.launch();self.sql('UPDATE settlements SET protection_until=9000 WHERE settlement_id=?',(self.sb,))
        self.advance(self.a,8200)
        self.assertEqual(self.sql('SELECT status,allowance_refunded FROM attacks')[0],('cancelled',1))
        self.assertEqual(self.state(self.a)['settlement']['attacks_remaining'],3)
        self.assertFalse(next(c for c in self.state(self.a)['citizens'] if c['citizen_id']==ids[0])['away'])
        self.advance(self.b,8201);self.assertEqual(self.state(self.a)['settlement']['attacks_remaining'],3)
        self.assertEqual(self.reports(),[])
    def test_three_daily_allowances_and_midnight_reset(self):
        ids=self.extra(self.sa,4);self.action(self.a,'declare',target_id=self.sb)
        for cid in ids[:3]:self.action(self.a,'launch',now=4600,target_id=self.sb,citizen_ids=[cid])
        with self.assertRaisesRegex(ValueError,'allowances'):self.action(self.a,'launch',now=4600,target_id=self.sb,citizen_ids=[ids[3]])
        # Avoid prototype shortage freeze when fast-forwarding to midnight.
        self.advance(self.a,8200)
        self.sql('UPDATE settlement_resources SET food=150,water=150')
        self.sql('UPDATE settlements SET simulation_processed_at=82800,last_rollover_at=0')
        self.advance(self.a,86400)
        state=self.state(self.a)
        self.assertEqual(state['settlement']['attacks_remaining'],3)
        self.assertEqual(state['settlement']['last_rollover_at'],86400)
    def test_final_window_blocks_launch_and_existing_raid_finishes(self):
        aid,ids=self.launch();self.sql('UPDATE seasons SET finalization_at=4700,ends_at=10000')
        with self.assertRaisesRegex(ValueError,'final three'):self.action(self.a,'declare',now=4700,target_id=self.sb)
        self.advance(self.b,8200);self.assertEqual(self.sql('SELECT status FROM attacks')[0][0],'resolved')
    def test_resource_only_raid_does_not_damage_buildings_or_capture(self):
        aid,ids=self.launch();before=self.sql('SELECT citizen_id,settlement_id FROM citizens')
        self.advance(self.a,8200)
        self.assertEqual(before,self.sql('SELECT citizen_id,settlement_id FROM citizens'))
        self.assertEqual(self.sql('SELECT current_hp FROM buildings'),[(1000.0,),(1000.0,)])
    def test_deaths_are_recorded_and_midnight_restores_floor(self):
        aid,ids=self.launch()
        self.sql("UPDATE citizens SET current_hp=1 WHERE settlement_id=? AND citizen_id NOT IN (SELECT citizen_id FROM citizen_assignments WHERE ended_at IS NULL)",(self.sb,))
        self.advance(self.b,8200)
        self.assertGreater(self.sql("SELECT count(*) FROM citizens WHERE status='dead'")[0][0],0)
        self.sql('UPDATE settlement_resources SET food=150,water=150')
        self.advance(self.b,86400)
        self.assertEqual(len(self.state(self.b)['citizens']),6)
        self.assertEqual(self.sql("SELECT count(*) FROM citizen_settlement_history WHERE arrival_reason='midnight_population_floor'")[0][0],5)
    def test_arrival_exactly_midnight_rolls_allowances_before_combat(self):
        self.action(self.a,'declare',target_id=self.sb);ids=self.extra(self.sa)
        self.sql('UPDATE settlements SET simulation_processed_at=82800,last_rollover_at=0')
        self.action(self.a,'launch',now=82800,target_id=self.sb,citizen_ids=ids)
        self.advance(self.b,86400)
        self.assertEqual(self.state(self.a)['settlement']['attacks_remaining'],3)
        self.assertEqual(self.sql('SELECT resolved_at FROM attacks')[0][0],86400)
    def test_sequential_same_timestamp_resolution_uses_previous_injuries(self):
        ids=self.extra(self.sa,2);self.action(self.a,'declare',target_id=self.sb)
        for cid in ids:self.action(self.a,'launch',now=4600,target_id=self.sb,citizen_ids=[cid])
        self.advance(self.b,8200)
        reports=self.reports();self.assertEqual(reports[0]['defenders'][0]['hp_before'],100)
        self.assertEqual(reports[2]['defenders'][0]['hp_before'],90)
    def test_offline_resolution_then_healing_matches_smaller_requests(self):
        aid,ids=self.launch();copy=Path(self.tmp.name)/'copy.db'
        with closing(sqlite3.connect(self.path)) as src,closing(sqlite3.connect(copy)) as dst:src.backup(dst)
        large=self.advance(self.a,8800)
        with account_scope(self.a):
            for now in (8100,8200,8500,8800):small=advance_settlement(copy,now)
        for resource in trading.RESOURCES:self.assertAlmostEqual(large['resources'][resource],small['resources'][resource],places=7)
        self.assertEqual(large['citizens'],small['citizens'])
    def test_resolution_error_rolls_back_entire_battle(self):
        aid,ids=self.launch();a,b=self.state(self.a),self.state(self.b)
        with patch('game.combat.participants_result',side_effect=ValueError('test failure')):
            with self.assertRaises(ValueError):self.advance(self.b,8200)
        self.assertEqual(a,self.state(self.a));self.assertEqual(b,self.state(self.b))
        self.assertEqual(self.sql('SELECT status FROM attacks')[0][0],'in_flight')
        self.assertEqual(self.reports(),[])

    def test_citizen_killed_during_catchup_cannot_become_administrator(self):
        aid,ids=self.launch()
        target=next(c for c in self.state(self.b)['citizens'] if c['assignment']=='unassigned')['citizen_id']
        self.sql('UPDATE citizens SET current_hp=1 WHERE citizen_id=?',(target,))
        from game.simulation import apply_action
        with account_scope(self.b):
            with self.assertRaisesRegex(ValueError,'no longer available'):apply_action(self.path,'assign',citizen_id=target,now=8200)
        self.advance(self.b,8200)
        self.assertEqual(self.sql("SELECT status FROM citizens WHERE citizen_id=?",(target,))[0][0],'dead')
        self.assertEqual(self.sql('SELECT count(*) FROM citizen_assignments WHERE citizen_id=? AND ended_at IS NULL',(target,))[0][0],0)

    def test_treaty_block_and_suspension_recall(self):
        aid,ids=self.launch()
        self.sql("INSERT INTO treaties(season_id,settlement_a_id,settlement_b_id,treaty_type,status,proposer_settlement_id,proposed_at,accepted_at,effective_at) VALUES (1,1,2,'peace','active',2,4600,4600,4600)")
        with self.assertRaisesRegex(ValueError,'treaty'):self.action(self.a,'declare',now=4600,target_id=self.sb)
        self.advance(self.b,8200)
        self.assertEqual(self.sql('SELECT status FROM attacks')[0][0],'cancelled')
        self.sql("UPDATE treaties SET status='cancelled',cooldown_until=8200 WHERE treaty_type='peace'")
        new=self.action(self.a,'launch',now=8200,target_id=self.sb,citizen_ids=ids)
        self.sql("UPDATE settlements SET status='suspended',suspended_at=8300 WHERE settlement_id=?",(self.sb,))
        self.advance(self.a,11800)
        self.assertEqual(self.sql('SELECT status,allowance_refunded FROM attacks WHERE attack_id=?',(new,))[0],('cancelled',1))

    def test_balanced_loot_and_unavailable_objective_fallback(self):
        self.weak_defense();aid,ids=self.launch(objective='balanced');self.advance(self.a,8200)
        taken=self.reports()[0]['loot']['taken']
        self.assertAlmostEqual(sum(taken.values()),12)
        self.assertTrue(all(quantity>0 for quantity in taken.values()))
        self.sql('UPDATE settlement_resources SET electronics=0 WHERE settlement_id=?',(self.sb,))
        aid=self.action(self.a,'launch',now=8200,target_id=self.sb,citizen_ids=ids,objective='electronics')
        self.advance(self.a,11800)
        taken=self.reports()[-1]['loot']['taken'];self.assertEqual(taken['electronics'],0);self.assertGreater(taken['food'],0)


class CombatHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'http.db';accounts.prepare(self.path);self.now=1000
        with closing(connect_database(self.path)) as c,c:
            for name in ('alpha','bravo'):c.execute("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES (?,'!',?,1000)",(name,name))
        for aid,name in [(1,'alpha'),(2,'bravo')]:accounts.join(self.path,aid,name,1000)
        self.raw,self.session=accounts.new_session(self.path,1,1000);self.cookie='settlement_session='+self.raw
        self.server=AccountServer(('127.0.0.1',0),self.path,clock=lambda:self.now);self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,method='GET',fields=None,cookie=None,headers=None):
        c=http.client.HTTPConnection(*self.server.server_address);h={'Cookie':self.cookie if cookie is None else cookie};body=urlencode(fields,doseq=True) if fields is not None else None
        if body is not None:h['Content-Type']='application/x-www-form-urlencoded'
        h.update(headers or {});c.request(method,'/conflict' if method=='POST' else '/',body,h);r=c.getresponse();out=(r.status,r.read().decode());c.close();return out
    def test_war_form_authenticated_csrf_origin_and_duplicate_guards(self):
        self.assertIn('Citizen raids',self.request()[1]);self.assertIn('Rescue additional survivors',self.request()[1])
        f={'action':'declare','target_id':2,'token':self.session['csrf']}
        self.assertEqual(self.request('POST',f,cookie='')[0],403)
        self.assertEqual(self.request('POST',dict(f,token='wrong'))[0],403)
        self.assertEqual(self.request('POST',f,headers={'Origin':'https://foreign.invalid'})[0],403)
        self.assertEqual(self.request('POST',f)[0],303)
        self.assertIn('id="war-timer-1">3600</span> seconds',self.request()[1])
        self.assertEqual(self.request('POST',f)[0],400)
    def test_forged_ids_invalid_actions_and_duplicate_fields(self):
        base={'action':'declare','target_id':1,'token':self.session['csrf']}
        self.assertEqual(self.request('POST',base)[0],400)
        self.assertEqual(self.request('POST',dict(base,target_id=[2,2]))[0],400)
        self.assertEqual(self.request('POST',dict(base,target_id=2,action='recall'))[0],400)


if __name__=='__main__':unittest.main()
