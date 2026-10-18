"""Opening upgrade balance without world setup or simulation."""
import json
from pathlib import Path
import unittest

class TownHallBalanceTests(unittest.TestCase):
    def test_first_upgrade_costs_and_work_time_across_supported_configs(self):
        root=Path(__file__).resolve().parents[1]/'config'
        for path in root.glob('prototype_v*.json'):
            hall=json.loads(path.read_text(encoding='utf-8')).get('buildings',{}).get('town_hall')
            if not hall:continue
            with self.subTest(version=path.stem):
                level=hall['levels'][1]
                self.assertEqual([level[k] for k in ('scrap','metal','electronics')],[150,50,5])
                self.assertEqual(level['minutes'],120)

    def test_later_upgrade_cost_and_time_are_preserved(self):
        path=Path(__file__).resolve().parents[1]/'config/prototype_v13.json'
        level=json.loads(path.read_text(encoding='utf-8'))['buildings']['town_hall']['levels'][2]
        self.assertEqual({k:level[k] for k in ('scrap','metal','electronics','minutes')},{'scrap': 450.0, 'metal': 250.0, 'electronics': 25.0, 'minutes': 240.0})
