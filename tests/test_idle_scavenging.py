"""Only genuinely inert scavenging jobs may stop blocking bulk processing."""
from copy import deepcopy
import json
import unittest
from game.quiet import job_blocks_bulk


class IdleScavengingTests(unittest.TestCase):
    def fixture(self):
        job=dict(job_id=7,job_type='scavenging',status='paused',target_derelict_id=1,
                 work_required=1000,work_completed=100)
        state={'citizens':[{'job_id':None}],
               'derelicts':[{'settlement_derelict_id':1,'status':'scavenging',
                             'random_result':json.dumps({'scrap':20})}]}
        return state,job

    def test_unstaffed_unfinished_paused_scavenging_is_inert_and_does_not_mutate_state(self):
        state,job=self.fixture();before=deepcopy((state,job))
        self.assertFalse(job_blocks_bulk(state,job))
        self.assertEqual((state,job),before)

    def test_status_alone_does_not_allow_workers_or_other_work_to_skip_detail(self):
        state,job=self.fixture()
        state['citizens'][0]['job_id']=job['job_id']
        self.assertTrue(job_blocks_bulk(state,job))
        state['citizens'][0]['job_id']=None
        for status in ('active','queued'):
            job['status']=status
            self.assertTrue(job_blocks_bulk(state,job))
        job.update(status='paused',job_type='construction')
        self.assertTrue(job_blocks_bulk(state,job))

    def test_due_completion_and_missing_or_cleared_sites_keep_detail(self):
        state,job=self.fixture()
        job['work_completed']=1000-1e-8
        self.assertTrue(job_blocks_bulk(state,job))
        job['work_completed']=100
        state['derelicts'][0]['status']='cleared'
        self.assertTrue(job_blocks_bulk(state,job))
        state['derelicts']=[]
        self.assertTrue(job_blocks_bulk(state,job))

    def test_survivor_discovery_that_is_already_due_cannot_be_delayed(self):
        state,job=self.fixture()
        event={'resolved':False,'at_fraction':0.1}
        state['derelicts'][0]['random_result']=json.dumps({'_survivor':event})
        self.assertTrue(job_blocks_bulk(state,job))
        event['at_fraction']=0.5
        state['derelicts'][0]['random_result']=json.dumps({'_survivor':event})
        self.assertFalse(job_blocks_bulk(state,job))
        event.update(at_fraction=0.1,resolved=True)
        state['derelicts'][0]['random_result']=json.dumps({'_survivor':event})
        self.assertFalse(job_blocks_bulk(state,job))
