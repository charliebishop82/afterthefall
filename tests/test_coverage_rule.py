"""Shared coverage threshold and tile-centre boundaries; no game world needed."""
import json
from pathlib import Path
import unittest
from game.economy import _coverage

class CoverageRuleTests(unittest.TestCase):
    def test_supported_building_configurations_use_fifty_percent(self):
        root=Path(__file__).resolve().parents[1]/'config'
        for path in root.glob('prototype_v*.json'):
            config=json.loads(path.read_text(encoding='utf-8'))
            if 'construction' not in config:continue
            with self.subTest(version=path.stem):
                self.assertEqual(config['construction']['coverage_fraction'],.5)

    def test_exactly_half_a_footprint_is_covered_and_qualifies(self):
        threshold=.5
        fraction=_coverage((0,0,2,2),((0,0,1,2,0),))
        self.assertEqual(fraction,.5);self.assertGreaterEqual(fraction,threshold)
        below=_coverage((0,0,2,2),((0,0,1,1,0),))
        self.assertEqual(below,.25);self.assertLess(below,threshold)

    def test_overlapping_sources_do_not_count_the_same_tile_twice(self):
        self.assertEqual(_coverage((0,0,2,2),((0,0,1,1,0),(0,0,1,1,0))),.25)
