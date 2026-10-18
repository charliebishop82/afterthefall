"""Own mission summaries and visibility on a minimal disposable report store."""
from contextlib import closing
import json,sqlite3,tempfile,unittest
from pathlib import Path
from game.operation_results import raid_summary,expedition_summary,snapshot

class OperationResultTests(unittest.TestCase):
    def test_raid_summary_distinguishes_delivered_loot_from_overflow_and_defender_loss(self):
        report={'result':'attacker_win','loot':{'taken':{'scrap':12},'deposited':{'scrap':7},'lost':{'scrap':5}},'credits_taken':8,'attackers':[{'hp_before':100,'hp_after':90}]}
        title,text=raid_summary(report,True)
        self.assertEqual(title,'Raid succeeded');self.assertIn('Delivered: 7.00 Scrap',text);self.assertIn('Storage overflow: 5.00 Scrap',text);self.assertIn('1 injured',text)
        title,text=raid_summary(report,False);self.assertEqual(title,'Settlement raided');self.assertIn('12.00 Scrap',text);self.assertIn('lost: 8',text)

    def test_expedition_summary_includes_gathered_delivered_and_overflow(self):
        _,text=expedition_summary({'gathered':'{"scrap":5}','delivered':'{"scrap":3,"food":2}','discarded':'{"scrap":2}'})
        self.assertIn('Gathered: 5.00 Scrap',text);self.assertIn('3.00 Scrap',text);self.assertIn('2.00 Food',text);self.assertIn('Storage overflow: 2.00 Scrap',text)

    def test_feed_is_scoped_to_settlement_and_season_and_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'reports.db'
            with closing(sqlite3.connect(path)) as c,c:
                c.execute('CREATE TABLE attacks (attack_id INTEGER PRIMARY KEY,season_id INTEGER,attacker_settlement_id INTEGER)')
                c.execute('CREATE TABLE battle_reports (report_id INTEGER PRIMARY KEY,attack_id INTEGER,recipient_settlement_id INTEGER,created_at INTEGER,report_data TEXT)')
                report=json.dumps({'result':'defender_win','loot':{}})
                c.executemany('INSERT INTO attacks VALUES (?,?,?)',[(1,1,10),(2,1,20),(3,2,10)])
                c.executemany('INSERT INTO battle_reports VALUES (?,?,?,?,?)',[(1,1,10,100,report),(2,2,20,101,report),(3,3,10,102,report)])
            before=path.read_bytes();result=snapshot(path,{'settlement':{'settlement_id':10},'season':{'season_id':1}})
            self.assertEqual([r['id'] for r in result['results']],['raid-1']);self.assertEqual(path.read_bytes(),before)
