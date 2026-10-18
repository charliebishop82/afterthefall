"""Equipment trades use disposable saves and real public transaction services."""
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import equipment_market as market, manufacturing, drones, structural
from game.settlement import account_scope, read_settlement, load_config
from tests.fixtures import EquipmentFixture


class EquipmentMarketTests(EquipmentFixture, unittest.TestCase):
    def test_all_types_can_use_starter_homes_and_trade_without_factories(self):
        self.start()
        for kind in market.KINDS:
            with self.subTest(kind=kind):
                bid=self.home(kind)
                self.trade('reserve_buy',kind)
                self.assertTrue(manufacturing.compatible_home(self.state(),kind,next(b for b in self.state()['buildings'] if b['building_id']==bid)))
                if kind=='offensive_drone':self.assertEqual(len(drones.ready(self.state(),kind)),1)
                if kind=='missile':self.assertEqual(sum(i['quantity'] for i in structural.ammunition(self.state(),kind)),1)
                self.trade('sell',kind)
                self.assertEqual(self.sql('SELECT quantity FROM equipment_market_stock WHERE kind=?',(kind,)),[(1,)])
                self.trade('buy',kind)
                self.assertEqual(self.sql('SELECT quantity FROM equipment_market_stock WHERE kind=?',(kind,)),[(0,)])
                self.assertEqual(self.sql("SELECT sum(amount) FROM credit_transactions WHERE transfer_ref LIKE 'equipment-market:%'"),[(0,)])
        self.assertFalse(any(b['building_type'] in ('drone_factory','munitions_factory') for b in self.state()['buildings']))

    def test_storage_credit_and_stock_failures_leave_no_partial_purchase(self):
        self.start()
        before=self.state()['resources']['credits']
        with self.assertRaisesRegex(ValueError,'storage'):self.trade('reserve_buy')
        self.assertEqual(self.state()['resources']['credits'],before)
        self.home('offensive_drone');self.trade('reserve_buy')
        with self.assertRaises(ValueError):self.trade('buy')
        self.assertEqual(len([u for u in self.state()['units'] if u['status']=='available']),1)
        self.home('air_defense_drone');self.sql('UPDATE settlement_resources SET credits=0')
        with self.assertRaisesRegex(ValueError,'Credits'):self.trade('reserve_buy','air_defense_drone')
        self.assertEqual(self.sql('SELECT count(*) FROM equipment_market_trades'),[(1,)])

    def test_damaged_deployed_repairing_and_already_sold_drones_cannot_be_sold(self):
        self.start();self.home('offensive_drone');self.trade('reserve_buy')
        uid=next(u['unit_id'] for u in self.state()['units'] if u['status']=='available')
        for status,hp in [('available',90),('deployed',100),('repairing',100)]:
            self.sql('UPDATE military_units SET status=?,current_hp=? WHERE unit_id=?',(status,hp,uid))
            with self.assertRaises(ValueError):self.trade('sell')
        self.sql("UPDATE military_units SET status='available',current_hp=100 WHERE unit_id=?",(uid,))
        self.trade('sell')
        with self.assertRaises(ValueError):self.trade('sell')
        self.assertEqual(self.sql("SELECT count(*) FROM equipment_market_trades WHERE action='sell'"),[(1,)])

    def test_deployed_unit_keeps_its_slot_and_inoperative_home_rejects_purchase(self):
        self.start();bid=self.home('offensive_drone');self.trade('reserve_buy')
        self.sql("UPDATE military_units SET status='deployed'")
        season=self.state()['season']['season_id']
        self.sql('INSERT INTO equipment_market_stock VALUES (?,?,1)',(season,'offensive_drone'))
        with self.assertRaisesRegex(ValueError,'storage'):self.trade('buy')
        self.sql("UPDATE military_units SET status='destroyed',current_hp=0")
        self.sql('UPDATE buildings SET current_hp=1 WHERE building_id=?',(bid,))
        with self.assertRaisesRegex(ValueError,'storage'):self.trade('buy')

    def test_reserve_allowance_is_personal_and_does_not_consume_shared_stock(self):
        self.start();self.home('offensive_drone');self.trade('reserve_buy');self.trade('sell')
        second=self.app.test_client();self.player('visitor',client=second)
        other=self.sql("SELECT account_id FROM accounts WHERE username='visitor'")[0][0]
        with account_scope(other):state=read_settlement(self.path)
        with closing(connect_database(self.path)) as c:
            rows,_=market.snapshot(c,state,1000)
        self.assertEqual(rows['offensive_drone']['remaining'],1)
        self.assertEqual(rows['offensive_drone']['stock'],1)

    def test_daily_reserve_independent_of_pool_and_resets_without_accumulating(self):
        self.start();self.home('offensive_drone');self.trade('reserve_buy');self.trade('sell');self.trade('buy')
        with self.assertRaises(ValueError):self.trade('reserve_buy')
        state=self.state()
        with closing(connect_database(self.path)) as c:
            first,_=market.snapshot(c,state,86400)
            later,_=market.snapshot(c,state,86400*5)
        self.assertEqual(first['offensive_drone']['remaining'],1)
        self.assertEqual(later['offensive_drone']['remaining'],1)

    def test_bank_failure_rolls_back_units_pool_and_allowance(self):
        self.start();self.home('offensive_drone')
        before=self.state()['resources']['credits']
        with patch('game.equipment_market.banking.transfer',side_effect=ValueError('ledger unavailable')):
            with self.assertRaises(ValueError):self.trade('reserve_buy')
        self.assertEqual(self.state()['resources']['credits'],before)
        self.assertEqual(len(self.state()['units']),0)
        self.trade('reserve_buy')

    def test_form_route_and_panel_use_existing_market_and_log_safe_fields(self):
        self.start();self.home('offensive_drone')
        response=self.post('/market',dict(token=self.token,action='equipment_reserve_buy',unit_type='offensive_drone',quantity='1'))
        self.assertEqual(response.status_code,303)
        html=self.get().text
        self.assertIn('Military equipment',html)
        self.assertIn('Small Offensive Drone Hangar',html)
        from game.request_logging import safe_parameters,ACTIONS
        self.assertIn('equipment_buy',ACTIONS)
        self.assertEqual(safe_parameters({'action':['equipment_buy'],'unit_type':['missile']}),{'unit_type':'missile'})

    def test_starter_rules_are_small_and_larger_buildings_keep_upgrades(self):
        config=load_config('prototype_v13')
        for kind,unit in config['units'].items():
            info=config['buildings'][unit['starter_storage']]
            self.assertEqual((info['unlock'],info['footprint'],info['max_level']),(1,[1,1],1))
            self.assertEqual(config['buildings'][unit['storage']]['max_level'],3)
            self.assertEqual((info['levels'][0]['scrap'],info['levels'][0]['metal']),(25,10))
            self.assertLess(market.settings()[kind]['sell_price'],market.settings()[kind]['buy_price'])

    def test_paid_manufacturing_reservation_blocks_market_slot(self):
        self.start();bid=self.home('offensive_drone')
        state=self.state()
        state['jobs'].append(dict(job_id=999,job_type='manufacturing',status='paused',
                                 inputs_spent='{"paid": true, "home_id": '+str(bid)+'}'))
        self.assertEqual(sum(n for _,n in market.slots(state,'offensive_drone')),0)

    def test_starter_storage_is_constructible_at_town_hall_one(self):
        self.start()
        from game.buildings import change_building,footprint
        state=self.state();hall=state['buildings'][0];w,h=footprint(state,hall)
        self.sql('DELETE FROM settlement_derelicts');self.sql('DELETE FROM season_derelicts')
        before=state['resources']
        with account_scope(self.a):
            change_building(self.path,'build',now=1000,building_type='starter_offensive_hangar',
                            x=hall['origin_x']+w,y=hall['origin_y'],rotation=0,auto_builder=True)
        after=self.state()
        self.assertEqual(after['buildings'][0]['level'],1)
        self.assertEqual(after['resources']['scrap'],before['scrap']-25)
        self.assertEqual(after['resources']['metal'],before['metal']-10)
        self.assertTrue(any(b['building_type']=='starter_offensive_hangar' and b['status']=='construction' for b in after['buildings']))

    def test_invalid_quantities_and_types_are_rejected(self):
        self.start()
        for quantity in (0,-1,True,1.5,10001):
            with self.assertRaises(ValueError):self.trade('reserve_buy',quantity=quantity)
        with self.assertRaises(ValueError):self.trade('reserve_buy','unknown')
