import unittest
from game.building_views import staffing_hint


class StaffingHighlightTests(unittest.TestCase):
    def test_production_warning_clears_only_for_present_assigned_worker(self):
        building={'building_id':2,'status':'active'}
        state={'jobs':[],'citizens':[]}
        self.assertTrue(staffing_hint(state,building,2)['unstaffed'])
        state['citizens']=[dict(building_id=2,job_id=None,assignment='production',away=True)]
        self.assertTrue(staffing_hint(state,building,2)['unstaffed'])
        state['citizens'][0]['away']=False
        self.assertFalse(staffing_hint(state,building,2)['unstaffed'])

    def test_passive_buildings_are_not_falsely_unstaffed(self):
        self.assertEqual(staffing_hint({'jobs':[],'citizens':[]},
                                      {'building_id':2,'status':'active'},0),
                         {'unstaffed':False,'label':''})

    def test_project_needs_its_own_crew_even_with_production_worker(self):
        state={'jobs':[dict(job_id=7,target_building_id=2,job_type='upgrade',status='paused')],
               'citizens':[dict(building_id=2,job_id=None,assignment='production')]}
        building={'building_id':2,'status':'upgrading'}
        self.assertEqual(staffing_hint(state,building,2),{'unstaffed':True,'label':'Needs builders'})
        state['citizens'].append(dict(building_id=2,job_id=7,assignment='construction'))
        self.assertFalse(staffing_hint(state,building,2)['unstaffed'])
