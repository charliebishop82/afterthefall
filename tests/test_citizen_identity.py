"""Citizen identities and current roster behavior on disposable saves."""
from contextlib import closing
import random
import sqlite3
import unittest

from database.create_database import connect_database
from game import combat, consequences
from game.population import generated_name
from game.settlement import account_scope, read_state
from game.views import render_page
from tests.fixtures import SupportWorld, fixed_map_seed


class CitizenIdentityTests(unittest.TestCase):
    def setUp(self):
        with fixed_map_seed():
            self.w = SupportWorld(self)
        self.w.change('enable_consequences')

    def test_starting_names_are_unique_across_players_and_survive_reload(self):
        w = self.w
        first = [c['name'] for c in w.state()['citizens']]
        second = [c['name'] for c in w.state(w.b)['citizens']]
        self.assertEqual(len(set(first + second)), 12)
        self.assertEqual(first, [c['name'] for c in w.state()['citizens']])

    def test_generated_name_avoids_another_players_existing_identity(self):
        w = self.w
        with closing(connect_database(w.path)) as c, c:
            proposed = generated_name(c, w.sa, random.Random(7))
            c.execute('UPDATE citizens SET name=? WHERE citizen_id=?',
                      (proposed, w.state(w.b)['citizens'][0]['citizen_id']))
            self.assertNotEqual(generated_name(c, w.sa, random.Random(7)), proposed)

    def test_population_recovery_creates_named_birth_eligible_survivors(self):
        w = self.w
        w.sql("UPDATE citizens SET current_hp=0,status='dead' WHERE settlement_id=?", (w.sa,))
        with closing(connect_database(w.path)) as c, c, account_scope(w.a):
            c.row_factory = sqlite3.Row
            consequences.daily(c, read_state(c), 86400)
            state = read_state(c)
            self.assertEqual(len(state['citizens']), 6)
            self.assertTrue(all(citizen['sex'] in ('male', 'female') for citizen in state['citizens']))
            self.assertTrue(all(not citizen['name'].startswith('Survivor ') for citizen in state['citizens']))
            # This fixed seed produces both sexes; no mixed-sex guarantee is added.
            self.assertEqual({citizen['sex'] for citizen in state['citizens']}, {'male', 'female'})
            self.assertGreater(consequences.birth_chance(state), 0)
            consequences.daily(c, read_state(c), 86400)
            self.assertEqual(len(read_state(c)['citizens']), 6)

    def test_older_combat_floor_also_creates_known_demographics(self):
        w = self.w
        w.sql("UPDATE citizens SET current_hp=0,status='dead' WHERE settlement_id=?", (w.sa,))
        with closing(connect_database(w.path)) as c, c, account_scope(w.a):
            c.row_factory = sqlite3.Row
            combat.daily(c, read_state(c), 86400)
            self.assertTrue(all(citizen['sex'] in ('male', 'female') for citizen in read_state(c)['citizens']))

    def test_current_roster_shows_xp_sex_and_distinguishes_legacy_duplicates(self):
        w = self.w
        ids = [c['citizen_id'] for c in w.state()['citizens'][:2]]
        for cid in ids:
            w.sql('UPDATE citizens SET name=?,xp=2.5 WHERE citizen_id=?', ('Legacy Name', cid))
        page = render_page(w.state(), 'test-token').decode()
        self.assertIn('2.50 XP', page)
        self.assertIn('<th scope="col">Sex</th>', page)
        self.assertIn('<td>Female</td>', page)
        for cid in ids:
            self.assertIn(f'Legacy Name <small>#{cid}</small>', page)
        self.assertEqual([c['name'] for c in w.state()['citizens'][:2]], ['Legacy Name', 'Legacy Name'])
