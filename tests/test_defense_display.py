import unittest
from unittest.mock import patch
from game.defense_display import local_defense


class DefenseDisplayTests(unittest.TestCase):
    def citizen(self,cid,role,building=None,away=False,hp=100):
        return dict(citizen_id=cid,assignment=role,building_id=building,away=away,current_hp=hp)

    def calculate(self,citizens,structural=False,guard_ids=()):
        state=dict(buildings=[{'building_id':1}],citizens=citizens)
        with patch('game.support.guards',return_value=[c for c in citizens if c['citizen_id'] in guard_ids]), \
             patch('game.support.enabled',return_value=True),patch('game.structural.enabled',return_value=structural), \
             patch('game.combat.strength',return_value=10),patch('game.combat.rule',return_value=15), \
             patch('game.drones.ready',return_value=[]),patch('game.support.defense_bonus',return_value=0), \
             patch('game.structural.turret_strength',return_value=0):
            return local_defense(state)

    def test_patrol_bonus_and_unassigned_defenders(self):
        result=self.calculate([self.citizen(1,'patrol'),self.citizen(2,'unassigned')])
        self.assertAlmostEqual(result['total'],21.5)

    def test_away_incapacitated_and_nondefending_workers_are_excluded(self):
        result=self.calculate([self.citizen(1,'patrol',away=True),self.citizen(2,'patrol',hp=0),self.citizen(3,'production',2)])
        self.assertEqual(result['total'],0)

    def test_structural_hall_occupant_is_counted_once_and_guards_need_functioning_post(self):
        result=self.calculate([self.citizen(1,'administrator',1),self.citizen(2,'unassigned',1),
                               self.citizen(3,'defender',2),self.citizen(4,'defender',3)],True,(3,))
        self.assertEqual(result['total'],30)
