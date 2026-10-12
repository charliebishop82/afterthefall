"""ETA and gross scavenging summaries use current conditions, without mutations."""
import copy
import json
import unittest
from unittest.mock import patch
from game.building_views import job_eta, scavenging_summary


class WorkOverviewTests(unittest.TestCase):
    def state(self):
        return dict(season={'status':'active'},settlement={'status':'active'},
            citizens=[dict(building_id=None,job_id=4)],
            jobs=[dict(job_id=4,job_type='scavenging',status='active',target_building_id=None,
                       target_derelict_id=2,work_required=3600,work_completed=900)],
            derelicts=[dict(settlement_derelict_id=2,derelict_type='small',status='scavenging',
                           random_result=json.dumps(dict(food=10,water=20,scrap=40)),
                           recovered_loot=json.dumps(dict(food=2.5,scrap=12)))],
            config={'derelicts':{'small':{'name':'Ruined house','loot':dict(food=[4,14],water=[2,20],scrap=[12,40])}}})

    def test_eta_uses_effective_speed_and_compact_time(self):
        state=self.state();job=state['jobs'][0]
        self.assertEqual(job_eta(state,job,1),'45m')
        self.assertEqual(job_eta(state,job,.5),'1h 30m')
        self.assertEqual(job_eta(state,job,0),'Waiting')
        self.assertEqual(job_eta(state,job,1000),'1m')

    def test_paused_frozen_finished_and_complete_work_have_no_false_eta(self):
        state=self.state();job=state['jobs'][0]
        state['season']['status']='paused';self.assertEqual(job_eta(state,job,1),'Paused')
        state['season']['status']='finished';self.assertEqual(job_eta(state,job,1),'Ended')
        state['season']['status']='active';state['settlement']['status']='suspended'
        self.assertEqual(job_eta(state,job,1),'Frozen')
        state['settlement']['status']='active';job['work_completed']=3600
        self.assertEqual(job_eta(state,job,1),'Done')

    def test_summary_rates_include_material_bonus_and_preserve_recovery(self):
        state=self.state();before=copy.deepcopy(state)
        with patch('game.building_views.job_speed',return_value=2), patch('game.support.best',return_value=20):
            row=scavenging_summary(state)[0]
        self.assertEqual(row['rates']['food'],20)
        self.assertEqual(row['rates']['water'],40)
        self.assertEqual(row['rates']['scrap'],96)
        self.assertEqual(row['recovered']['scrap'],12)
        self.assertEqual(row['workers'],1)
        self.assertEqual(row['percent'],25)
        self.assertEqual(state,before)

    def test_paused_summary_and_unstaffed_work_have_zero_current_yield(self):
        state=self.state()
        with patch('game.support.best',return_value=0):
            with patch('game.building_views.job_speed',return_value=2):
                state['season']['status']='paused'
                row=scavenging_summary(state)[0]
                self.assertEqual(sum(row['rates'].values()),0)
                self.assertEqual(row['eta'],'Paused')
            with patch('game.building_views.job_speed',return_value=0):
                state['season']['status']='active'
                row=scavenging_summary(state)[0]
                self.assertEqual(sum(row['rates'].values()),0)
                self.assertEqual(row['eta'],'Waiting')
