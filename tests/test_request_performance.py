"""Timing is attached to normal logged requests without exposing credentials."""
import unittest
from tests import test_player_logging as fixtures

class RequestPerformanceTests(unittest.TestCase):
    setUp=fixtures.PlayerLoggingTests.setUp
    records=fixtures.PlayerLoggingTests.records
    get=fixtures.PlayerLoggingTests.get
    def test_completed_request_has_valid_timing_and_server_timing_header(self):
        response=self.get('/')
        record=[r for r in self.records() if r['event']=='request_finished'][-1]
        for key in ('duration_ms','processing_ms','gameplay_lock_wait_ms','gameplay_processing_ms'):
            self.assertGreaterEqual(record[key],0)
        self.assertAlmostEqual(record['duration_ms'],record['processing_ms']+record['gameplay_lock_wait_ms'],places=2)
        self.assertEqual(record['slow_request'],record['duration_ms']>=1000)
        self.assertIn('game_lock;dur=',response.headers['Server-Timing'])
