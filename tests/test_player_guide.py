"""Published help is readable before launch and cannot mutate gameplay."""
from contextlib import closing
from pathlib import Path
import hashlib,json,sqlite3,tempfile,unittest
from unittest.mock import patch
from database.create_database import connect_database
from flask_app import COOKIE,ROOT,create_app
from game import accounts,web_views
from game.settlement import load_config
from game.expansion import config

class PlayerGuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'playtest.db'
        self.app=create_app(self.path,clock=lambda:1000);self.client=self.app.test_client()
    def get(self,path):
        response=self.client.get(path,base_url='http://127.0.0.1:8767');self.addCleanup(response.close);return response
    def snapshot(self):
        with closing(connect_database(self.path)) as c:
            tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {t:c.execute('SELECT * FROM "'+t.replace('"','""')+'"').fetchall() for t in tables}
    def test_anonymous_help_is_read_only_before_shared_start(self):
        before=self.snapshot()
        with patch('game.simulation.advance_settlement') as advance,patch('game.expansion.refresh') as refresh:
            result=self.get('/help');pdf=self.get('/help.pdf')
            self.assertEqual(result.status_code,200);self.assertEqual(pdf.status_code,200)
            advance.assert_not_called();refresh.assert_not_called()
        self.assertNotIn('Set-Cookie',result.headers);self.assertEqual(before,self.snapshot())
        self.assertIn('href="/help.pdf"',result.text)
    def test_printable_download_matches_published_artifact(self):
        result=self.get('/help.pdf')
        self.assertEqual(result.mimetype,'application/pdf');self.assertTrue(result.data.startswith(b'%PDF-'))
        self.assertIn('attachment',result.headers['Content-Disposition'])
        self.assertEqual(hashlib.sha256(result.data).digest(),hashlib.sha256((ROOT/'docs/player-guide.pdf').read_bytes()).digest())
    def test_public_and_logged_in_navigation_reach_help(self):
        self.assertIn('href="/help"',self.get('/login').text)
        aid=accounts.register(self.path,'learner','learner-password-long',1000)
        token,_=accounts.new_session(self.path,aid,1000)
        self.client.set_cookie(COOKIE,token,domain='127.0.0.1')
        self.assertIn('Help / player guide',self.get('/').text)
        before=self.snapshot();self.assertEqual(self.get('/help').status_code,200)
        self.assertEqual(before,self.snapshot())
    def test_help_has_narrow_policy_and_rejects_writes_and_file_paths(self):
        policy=self.get('/help').headers['Content-Security-Policy']
        self.assertIn("default-src 'none'",policy);self.assertIn('img-src data:',policy)
        self.assertNotIn('script-src',policy)
        html=self.get('/help').text
        self.assertNotIn('<script',html);self.assertNotIn('src="http',html)
        self.assertNotIn("'unsafe-inline'",self.get('/login').headers['Content-Security-Policy'])
        before=self.snapshot()
        self.assertEqual(self.client.post('/help',base_url='http://127.0.0.1:8767').status_code,404)
        for path in ('/help/database/playtest.db','/help/../config/prototype_v13.json','/help.pdf/extra'):
            self.assertEqual(self.get(path).status_code,405)
        self.assertEqual(before,self.snapshot())
    def test_reference_covers_every_current_type_level_and_rule_chapter(self):
        manifest=json.loads((ROOT/'docs/player-guide-manifest.json').read_text())
        catalogue={**load_config('prototype_v13')['buildings'],**config()['buildings']}
        self.assertEqual(manifest['building_types'],len(catalogue))
        self.assertEqual(manifest['building_levels'],sum(len(b['levels']) for b in catalogue.values()))
        self.assertEqual(manifest['hardware_types'],6)
        html=self.get('/help').text
        for kind in catalogue:self.assertIn('data-building="'+kind+'"',html)
        for key in ('opening','resources','map','build','storage','people','rations','scavenge','military','combat','recovery','trade','bank','interface','calendar','trouble'):
            self.assertIn('id="'+key+'"',html)
        self.assertEqual(html.count('data:image/svg+xml;base64,'),8)
        for name,digest in manifest['config_hashes'].items():
            self.assertEqual(hashlib.sha256((ROOT/'config'/name).read_bytes()).hexdigest(),digest)
