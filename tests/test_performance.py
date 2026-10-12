"""Read-only summaries tolerate old records, partial logs and unsafe values."""
from pathlib import Path
import json,tempfile,unittest
from game.performance import read,summarize,panel

class PerformanceTests(unittest.TestCase):
    def row(self,duration=100,**extra):
        return dict(event='request_finished',database='fixture.db',method='GET',route='/api/resources',
                    duration_ms=duration,**extra)
    def test_summary_separates_route_actions_and_reports_known_lock_samples(self):
        rows=[self.row(100),self.row(1100,gameplay_lock_wait_ms=900),self.row(200,gameplay_lock_wait_ms=50)]
        result=summarize(rows)[0]
        self.assertEqual(result['count'],3);self.assertEqual(result['slow'],1)
        self.assertEqual(result['p95'],1100);self.assertEqual(result['lock_average'],475)
        self.assertEqual(result['lock_samples'],2)
        self.assertIsNone(summarize([self.row()])[0]['lock_average'])
    def test_reader_filters_save_and_skips_malformed_or_nonfinite_records(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'actions.jsonl'
            path.write_text('\n'.join([json.dumps(self.row()),json.dumps(dict(self.row(),database='other.db')),
                json.dumps(self.row(float('nan'))),'partial{'])+'\n')
            rows,notice=read(path,'fixture.db');self.assertEqual(len(rows),1)
    def test_panel_escapes_metadata_and_links_valid_request_ids_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'actions.jsonl'
            path.write_text(json.dumps(self.row(1200,account_id='<script>',request_id='a'*32)))
            html=panel(path,'fixture.db')
            self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html)
            self.assertIn('/player-logs?request_id='+('a'*32),html)
            self.assertIn('Unknown',html)
    def test_missing_logs_are_reported_without_database_access(self):
        self.assertIn('not configured',panel(None,'fixture.db'))
