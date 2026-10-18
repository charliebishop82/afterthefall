"""Bot equipment decisions, normal form submission and audit privacy."""
from contextlib import closing
import copy
import json
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import bot_equipment as policy,equipment_market,market
from game.bot_military import choose_military
from game.settlement import account_scope,read_settlement
from tests.fixtures import EquipmentFixture


def action(route,reason,**form):return dict(route=route,reason=reason,form=form)


class BotEquipmentTests(EquipmentFixture, unittest.TestCase):
    def observe(self,kind=None):
        rows=market.public_snapshot(self.path,self.state(),1000)
        if kind:rows['equipment']={kind:rows['equipment'][kind]}
        return rows

    def decide(self,profile='aggressive',rows=None,rates=None,**kwargs):
        return policy.choose_equipment(self.state(),rates or {},rows or self.observe('offensive_drone'),profile,7,action,**kwargs)

    def submit(self,decision):
        return self.post(decision['route'],dict(token=self.token,**decision['form']))

    def test_bot_buys_daily_equipment_without_factory_through_normal_form(self):
        self.start();self.home('offensive_drone')
        decision=self.decide()
        self.assertEqual(decision['form'],dict(action='equipment_reserve_buy',unit_type='offensive_drone',quantity=1))
        self.assertEqual(self.submit(decision).status_code,303)
        self.assertEqual(len([u for u in self.state()['units'] if u['status']=='available']),1)
        self.assertIn('daily personal reserve',decision['reason'])

    def test_prefers_shared_on_equal_price_and_respects_cheaper_reserve(self):
        self.start();self.home('offensive_drone');self.trade('reserve_buy');self.trade('sell')
        self.assertEqual(self.decide()['form']['action'],'equipment_buy')
        rows=self.observe('offensive_drone');rows['equipment']['offensive_drone'].update(remaining=1,reserve_price=200)
        self.assertEqual(self.decide(rows=rows)['form']['action'],'equipment_reserve_buy')

    def test_no_purchase_without_stock_capacity_or_credit_buffer(self):
        self.start();self.home('offensive_drone')
        for change in (dict(stock=0,remaining=0),dict(free_slots=0)):
            rows=self.observe('offensive_drone');rows['equipment']['offensive_drone'].update(change)
            self.assertIsNone(self.decide(rows=rows))
        self.sql('UPDATE settlement_resources SET credits=350')
        self.assertIsNone(self.decide())
        self.assertIsNone(self.decide(rates={'food':dict(net=-1,consumption=5)}))

    def test_personalities_avoid_unwanted_offense_and_favor_repairs(self):
        self.start();self.home('offensive_drone')
        for personality in ('builder','defensive'):
            self.assertIsNone(self.decide(profile=personality))
        self.assertGreater(policy.profile('aggressive')['offensive_drone'],policy.profile('balanced')['offensive_drone'])
        self.assertGreater(policy.profile('builder')['repair_drone'],policy.profile('aggressive')['repair_drone'])
        self.assertEqual(policy.profile('defensive')['missile'],0)

    def test_sells_unwanted_equipment_but_does_not_rebuy_it(self):
        self.start();self.home('offensive_drone');self.trade('reserve_buy')
        decision=self.decide(profile='builder')
        self.assertEqual(decision['form']['action'],'equipment_sell')
        self.assertEqual(self.submit(decision).status_code,303)
        self.assertIsNone(self.decide(profile='builder'))

    def test_deployed_and_queued_equipment_count_toward_target(self):
        self.start();self.home('offensive_drone');self.trade('reserve_buy')
        state=self.state();state['units'][0]['status']='deployed'
        state['jobs'].append(dict(job_id=999,job_type='manufacturing',status='paused',output_type='offensive_drone',inputs_spent=json.dumps(dict(remaining=2,paid=False))))
        self.assertEqual(policy.holding(state,'offensive_drone'),3)
        rows=self.observe('offensive_drone');rows['equipment']['offensive_drone']['free_slots']=10
        self.assertIsNone(policy.choose_equipment(state,{},rows,'aggressive',7,action))
        before=copy.deepcopy(state)
        policy.choose_equipment(state,{},rows,'aggressive',7,action)
        self.assertEqual(state,before)

    def test_starter_storage_is_chosen_at_town_hall_one(self):
        self.start();state=self.state()
        free=[c for c in state['citizens'] if c['assignment']=='unassigned']
        decision=choose_military(state,[],'aggressive',7,action,free,self.observe())
        self.assertEqual(decision['form']['action'],'build')
        self.assertTrue(decision['form']['building_type'].startswith('starter_'))
        self.assertEqual(self.submit(decision).status_code,303)

    def test_services_damaged_drone_and_activates_repair_drone(self):
        self.start();self.home('offensive_drone');self.trade('reserve_buy')
        self.sql('UPDATE military_units SET current_hp=50')
        self.home('repair_drone')
        decision=policy.maintenance_decision(self.state(),action)
        self.assertEqual(decision['form']['action'],'service_drone')
        self.assertEqual(self.submit(decision).status_code,303)
        self.assertEqual(self.state()['units'][0]['status'],'repairing')
        self.trade('reserve_buy','repair_drone')
        decision=policy.maintenance_decision(self.state(),action)
        self.assertEqual(decision['form']['action'],'repair_drone_auto')
        self.assertEqual(self.submit(decision).status_code,303)
        self.assertEqual(self.observe()['equipment']['repair_drone']['sellable'],0)
        with self.assertRaises(ValueError):self.trade('sell','repair_drone')

    def test_small_workshop_gets_staff_and_growth_uses_larger_storage(self):
        self.start();bid=self.home('repair_drone')
        self.sql('UPDATE citizen_assignments SET ended_at=1000,end_reason=\'fixture\' WHERE building_id=? AND ended_at IS NULL',(bid,))
        state=self.state();free=[c for c in state['citizens'] if c['assignment']=='unassigned']
        decision=choose_military(state,[],'builder',7,action,free,self.observe())
        self.assertEqual(decision['form']['action'],'worker')
        self.assertEqual(decision['form']['building_id'],bid)
        self.assertEqual(self.submit(decision).status_code,303)
        state=self.state();state['buildings'][0]['level']=3
        self.assertEqual(policy.profile('aggressive',state)['offensive_drone'],9)

    def test_snapshot_exposes_only_own_allowance_and_safety_checks(self):
        self.start();self.home('offensive_drone');self.trade('reserve_buy')
        own=self.observe()['equipment']['offensive_drone']
        self.assertEqual((own['remaining'],own['free_slots'],own['sellable']),(0,0,1))
        other_client=self.app.test_client();self.player('visitor',client=other_client)
        aid=self.sql("SELECT account_id FROM accounts WHERE username='visitor'")[0][0]
        with account_scope(aid):state=read_settlement(self.path)
        other=market.public_snapshot(self.path,state,1000)['equipment']['offensive_drone']
        self.assertEqual((other['remaining'],other['free_slots'],other['sellable']),(1,0,0))
        self.assertNotIn('unit_ids',other)

    def test_error_logging_extracts_warning_without_forms_or_tokens(self):
        from run_bots import response_error,job_observation
        html=b'<html><div role="alert"><strong>Action not applied.</strong> No room.</div><form><input name="token" value="SECRET"></form></html>'
        self.assertEqual(response_error(html),'Action not applied. No room.')
        self.assertNotIn('SECRET',response_error(html))
        self.assertEqual(response_error(b'No allowance remains'),'No allowance remains')
        hidden=job_observation(dict(job_type='scavenging',inputs_spent='SECRET'))
        self.assertNotIn('inputs_spent',hidden)

    def test_same_seed_is_reproducible_and_nonrunning_market_does_not_act(self):
        self.start();self.home('offensive_drone')
        self.assertEqual(self.decide(),self.decide())
        rows=self.observe();rows['can_trade']=False
        self.assertIsNone(self.decide(rows=rows))

    def test_existing_staffed_factory_is_used_before_equipment_purchase(self):
        self.start();self.home('offensive_drone');state=self.state()
        spec=state['config']['buildings']['drone_factory']['levels'][0]
        bid=self.sql("INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at) VALUES (?,'drone_factory',1,21,18,?,'active',1000,1000) RETURNING building_id",(self.sid,spec['hp']))[0][0]
        citizen=next(c for c in state['citizens'] if c['assignment']=='unassigned')
        self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,?,'production',?,1000)",(citizen['citizen_id'],self.sid,bid))
        self.sql('UPDATE settlement_resources SET metal=30,electronics=10')
        decision=choose_military(self.state(),[],'aggressive',7,action,[],self.observe())
        self.assertEqual(decision['route'],'/manufacturing')
        self.assertEqual(decision['form']['unit_type'],'offensive_drone')

    def test_full_larger_storage_upgrades_when_town_hall_target_grows(self):
        self.start();self.sql('UPDATE buildings SET level=3 WHERE building_type=\'town_hall\'')
        self.sql('UPDATE settlement_resources SET scrap=100,metal=120,electronics=30')
        bid=self.sql("INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at) VALUES (?,'offensive_hangar',1,18,21,600,'active',1000,1000) RETURNING building_id",(self.sid,))[0][0]
        for _ in range(6):
            self.sql("INSERT INTO military_units(settlement_id,unit_type,current_hp,home_building_id,status,created_at) VALUES (?,'offensive_drone',100,?,'available',1000)",(self.sid,bid))
        state=self.state();free=[c for c in state['citizens'] if c['assignment']=='unassigned']
        with patch('game.bot_equipment.desired',return_value=['offensive_drone']):
            decision=choose_military(state,[],'aggressive',7,action,free,self.observe())
        self.assertEqual(decision['form'],dict(action='upgrade',building_id=bid,expected_level=1))

    def test_urgent_funding_preserves_desired_last_unit(self):
        self.start();self.home('offensive_drone');self.trade('reserve_buy')
        self.sql('UPDATE settlement_resources SET credits=0,food=0')
        rates={'food':dict(net=-5,consumption=5)}
        self.assertIsNone(self.decide(rates=rates,sell_only=True))
        sale=self.decide(profile='builder',rates=rates,sell_only=True)
        self.assertEqual(sale['form']['action'],'equipment_sell')
        self.assertEqual(self.submit(sale).status_code,303)

    def test_pending_ammunition_reservation_counts_without_revealing_other_players(self):
        self.start();bid=self.home('missile')
        state=self.state();state['munition_reservations']=[dict(building_id=bid,quantity=2)]
        self.assertEqual(policy.holding(state,'missile'),2)

    def test_paused_manufacturing_can_request_missing_inputs(self):
        self.start();state=self.state()
        self.sql('UPDATE settlement_resources SET metal=0')
        state=self.state()
        state['jobs'].append(dict(job_id=999,job_type='manufacturing',status='paused',output_type='offensive_drone',inputs_spent=json.dumps(dict(remaining=1,paid=False))))
        decision=choose_military(state,[],'aggressive',7,action,[],self.observe())
        self.assertEqual(decision['form']['resource'],'metal')
        self.assertIn(decision['form']['action'],('buy','reserve_buy'))
        self.assertIn('resuming manufacturing',decision['reason'])
