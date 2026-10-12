"""Workbook scoring regressions, including ownership and shared ranks."""
import copy
import unittest
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from game.scoring import totals, rank, settings


class ScoringTests(unittest.TestCase):
    def state(self):
        return {'resources': dict(food=10, water=10, scrap=10, metal=10, electronics=10, credits=100),
                'citizens': [dict(level=1,current_hp=1,morale=0)],
                'buildings': [], 'jobs': [], 'units': [], 'inventory': [],
                'config': {'buildings': {}, 'units': {}}}

    def test_workbook_weights_and_values(self):
        r=settings()['Scoring']
        self.assertEqual(sum(r[f'overall_{c}_weight'] for c in ('population','military','wealth','development')),100)
        self.assertEqual(totals(self.state()),dict(population=100,military=8,wealth=190,development=0))

    def test_scoring_values_match_current_source_workbook(self):
        namespace={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        path=Path(__file__).resolve().parents[1]/'sources/Post_Apocalyptic_Game_V1_Building_Settings(1).xlsx'
        with ZipFile(path) as archive:
            sheets=ET.fromstring(archive.read('xl/workbook.xml')).findall('.//s:sheet',namespace)
            index=next(i for i,sheet in enumerate(sheets,1) if sheet.attrib['name']=='Scoring')
            for row in ET.fromstring(archive.read(f'xl/worksheets/sheet{index}.xml')).findall('.//s:row',namespace)[1:]:
                values={''.join(filter(str.isalpha,cell.attrib['r'])):''.join(cell.itertext()) if cell.get('t')=='inlineStr' else cell.findtext('s:v','',namespace) for cell in row}
                key=values.get('A');value=values.get('D')
                if key in settings()['Scoring']:
                    try:value=float(value)
                    except (TypeError,ValueError):pass
                    self.assertEqual(settings()['Scoring'][key],value,key)

    def test_hp_and_morale_do_not_reduce_population(self):
        state=self.state();state['citizens'][0].update(level=3,current_hp=0.1,morale=0)
        self.assertEqual(totals(state)['population'],130)
        state['citizens'][0]['current_hp']=0
        self.assertEqual(totals(state)['population'],0)

    def test_debt_and_only_active_investments(self):
        loans=[dict(status='active',outstanding_balance=200)]
        investments=[dict(status='active',principal=50,accrued_interest=2),dict(status='withdrawn',principal=900,accrued_interest=0)]
        self.assertEqual(totals(self.state(),loans,investments)['wealth'],42)

    def test_owned_deployed_drone_and_hp_scaling(self):
        state=self.state();state['config']['units']['offensive_drone']={'hp':100}
        state['units']=[dict(unit_type='offensive_drone',status='deployed',current_hp=50),dict(unit_type='offensive_drone',status='destroyed',current_hp=0)]
        self.assertEqual(totals(state)['military'],25.5)

    def test_stored_and_committed_ammunition_count_once(self):
        state=self.state();state['inventory']=[dict(unit_type='missile',quantity=2),dict(unit_type='interceptor',quantity=3)]
        state['munition_reservations']=[dict(quantity=1)]
        self.assertEqual(totals(state)['military'],143)

    def test_completed_building_cost_level_and_condition(self):
        state=self.state();state['config']['buildings']['test']={'levels':[dict(scrap=10,metal=5,electronics=2,minutes=1,hp=100),dict(scrap=20,metal=10,electronics=4,minutes=2,hp=200)]}
        state['buildings']=[dict(building_id=1,building_type='test',level=2,status='active',current_hp=100)]
        self.assertAlmostEqual(totals(state)['development'],51.75)
        state['buildings'][0]['status']='ruined'
        self.assertEqual(totals(state)['development'],0)

    def test_construction_progress_scored_once(self):
        state=self.state();state['config']['buildings']['test']={'levels':[dict(scrap=100,metal=0,electronics=0,minutes=1,hp=100)]}
        state['buildings']=[dict(building_id=1,building_type='test',level=1,status='construction',current_hp=0)]
        state['jobs']=[dict(target_building_id=1,job_type='construction',status='active',work_completed=30,work_required=60,inputs_spent='{"scrap":100}')]
        self.assertEqual(totals(state)['development'],50)

    def test_shared_rank_and_competition_gap(self):
        a=dict(population=100,military=100,wealth=100,development=100)
        rows=rank([dict(a,name='A'),dict(a,name='B'),dict(population=0,military=0,wealth=0,development=0,name='C')])
        self.assertEqual([r['rank'] for r in rows],[1,1,3])
        self.assertEqual(rows[0]['overall'],100)

    def test_negative_wealth_remains_negative(self):
        row=rank([dict(population=0,military=0,wealth=-50,development=0)])[0]
        self.assertEqual(row['overall'],-25)

    def test_ranking_does_not_mutate_inputs(self):
        players=[dict(population=1,military=1,wealth=1,development=1)]
        old=copy.deepcopy(players);rank(players)
        self.assertEqual(players,old)
