"""Bank routes use existing account isolation and CSRF protections."""
import json
import re
import unittest
from tests import test_social as fixtures


class ExpansionHTTPTests(unittest.TestCase):
    def setUp(self):
        self.w=fixtures.SocialHTTPTests('runTest');self.w.setUp();self.addCleanup(self.w.doCleanups)

    def test_bank_opt_in_actions_and_public_score_privacy(self):
        w=self.w
        self.assertEqual(w.request('POST','/bank',{'token':w.ta,'action':'enable'},w.a)[0],303)
        self.assertEqual(w.request('POST','/bank',{'token':w.ta,'action':'borrow','amount':100},w.a)[0],303)
        html=w.request(cookie=w.a)[2]
        self.assertNotIn('Capture remains deferred.',html);self.assertIn('Citizen capture, focused population raids',html);self.assertIn('Season rankings',html);self.assertIn('100 Credits outstanding',html)
        revision=re.search(r'data-revision="([^"]+)"',html).group(1)
        self.assertEqual(json.loads(w.request(path='/api/resources',cookie=w.a)[2])['revision'],revision)
        status,_,body=w.request(path='/api/resources',cookie=w.b)
        self.assertEqual(status,200)
        scores=json.loads(body)['scores']
        self.assertEqual(len(scores),2)
        self.assertEqual(set(scores[0]),{'settlement_id','name','rank','overall','population','military','wealth','development','processed_at'})
        self.assertIsInstance(scores[0]['processed_at'],int)
        self.assertNotIn('Loan #1:',w.request(cookie=w.b)[2])

    def test_bank_rejects_wrong_csrf_duplicate_fields_and_foreign_loan(self):
        w=self.w
        self.assertEqual(w.request('POST','/bank',{'token':'wrong','action':'enable'},w.a)[0],403)
        self.assertEqual(w.request('POST','/bank',{'token':w.ta,'action':'enable'},w.a)[0],303)
        self.assertEqual(w.request('POST','/bank',{'token':w.ta,'action':'borrow','amount':100},w.a)[0],303)
        self.assertEqual(w.request('POST','/bank',{'token':w.tb,'action':'repay','amount':100,'loan_id':1},w.b)[0],400)
        self.assertEqual(w.request('POST','/bank',{'token':w.ta,'action':'borrow','amount':0},w.a)[0],400)
        self.assertEqual(w.request('POST','/bank',{'token':w.ta,'action':'invest','amount':100,'days':2},w.a)[0],400)
