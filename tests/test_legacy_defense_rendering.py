"""Reproduce the defense header's crash on pre-simulation saves."""
from pathlib import Path
import copy
import tempfile
import unittest
from game.settlement import prepare_database,create_settlement,read_settlement,load_config
from game.combat import maximum_hp
from game.defense_display import local_defense
from game.views import render_page

class LegacyDefenseRenderingTests(unittest.TestCase):
    def test_legacy_page_renders_without_mutating_or_upgrading_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'legacy.db';prepare_database(path)
            create_settlement(path,'Legacy settlement',now=1000)
            state=read_settlement(path);before=copy.deepcopy(state)
            self.assertNotIn('simulation',state['config'])
            html=render_page(state,'fixture-token').decode()
            self.assertIn('Ground defense',html)
            self.assertEqual(state,before)
            self.assertEqual(read_settlement(path),before)
            self.assertGreaterEqual(local_defense(state)['total'],0)

    def test_legacy_hp_matches_existing_v2_fallback(self):
        state=dict(config=load_config('prototype_v1'))
        self.assertEqual(maximum_hp(state,dict(level=1)),100)
        self.assertEqual(maximum_hp(state,dict(level=3)),116)

    def test_current_profile_uses_its_own_configured_hp_increment(self):
        state=dict(config=dict(citizen_hp=100,simulation=dict(hp_per_level=12)))
        self.assertEqual(maximum_hp(state,dict(level=3)),124)
