"""Finite allied contributions through real missile and drone resolution."""
import unittest
from tests.fixtures import SupportWorld
from game import combat,expansion
from game.settlement import account_scope


class AlliedExpansionTests(unittest.TestCase):
    def setUp(self):
        self.w=SupportWorld(self)
        w=self.w
        with account_scope(w.a):expansion.transact(w.path,'enable',1000)
        self.c,self.sc=w.player('charlie');w.config=w.state()['config']
        w.sql("UPDATE buildings SET level=3,current_hp=? WHERE settlement_id=? AND building_type='town_hall'",(w.config['buildings']['town_hall']['levels'][2]['hp'],self.sc))
        w.build('wind_turbine',sid=self.sc,x=21,y=15,level=3)
        a,b=sorted((w.sb,self.sc))
        w.sql("INSERT INTO treaties(season_id,settlement_a_id,settlement_b_id,treaty_type,status,proposer_settlement_id,proposed_at,effective_at) VALUES (1,?,?,'full_defense','active',?,1000,1000)",(a,b,a))

    def test_allied_air_drone_is_limited_and_damage_is_saved_to_ally(self):
        w=self.w;home=w.build('air_defense_bay',sid=self.sc)
        units=[w.unit('air_defense_drone',sid=self.sc,home=home) for _ in range(4)]
        attacker=w.unit();aid=w.raid(units=[attacker]);w.advance(8200)
        report=w.report();losses=report['air_battle']['allies']
        self.assertEqual(len(losses),1)
        self.assertEqual(losses[0]['settlement_id'],self.sc)
        self.assertEqual(w.sql("SELECT count(*) FROM attack_drones WHERE attack_id=? AND role='ally'",(aid,))[0][0],1)
        self.assertEqual(w.sql('SELECT count(*) FROM military_units WHERE settlement_id=? AND current_hp<100',(self.sc,))[0][0],1)
        self.assertEqual(w.sql('SELECT count(*) FROM battle_reports WHERE recipient_settlement_id=?',(self.sc,))[0][0],0)

    def test_local_air_defense_is_used_without_unneeded_allied_losses(self):
        w=self.w;home=w.build('air_defense_bay',sid=self.sc)
        for _ in range(4):w.unit('air_defense_drone',sid=self.sc,home=home)
        local=w.build('air_defense_bay',sid=w.sb)
        for _ in range(3):w.unit('air_defense_drone',sid=w.sb,home=local)
        attacker=w.unit();w.raid(units=[attacker]);w.advance(8200)
        self.assertEqual(w.report()['air_battle']['allies'],[])
        self.assertEqual(w.sql('SELECT count(*) FROM military_units WHERE settlement_id=? AND current_hp<100',(self.sc,))[0][0],0)

    def test_interceptors_local_first_then_only_one_quarter_allied_stock(self):
        w=self.w
        def stock(sid,kind,quantity):
            bid=w.build(w.config['units'][kind]['storage'],sid=sid)
            return w.sql('INSERT INTO military_inventory(settlement_id,building_id,unit_type,quantity,updated_at) VALUES (?,?,?,?,1000) RETURNING inventory_id',(sid,bid,kind,quantity))[0][0]
        stock(w.sa,'missile',3);local=stock(w.sb,'interceptor',1);ally=stock(self.sc,'interceptor',4)
        with account_scope(w.a):
            combat.command(w.path,'declare',1000,target_id=w.sb)
            combat.command(w.path,'launch',4600,target_id=w.sb,missile_count=3,objective='infrastructure')
        w.advance(8200)
        attempts=w.report()['missiles']['interceptors']
        self.assertEqual([i['settlement_id'] for i in attempts],[w.sb,self.sc])
        self.assertEqual(w.sql('SELECT quantity FROM military_inventory WHERE inventory_id=?',(local,))[0][0],0)
        self.assertEqual(w.sql('SELECT quantity FROM military_inventory WHERE inventory_id=?',(ally,))[0][0],3)
