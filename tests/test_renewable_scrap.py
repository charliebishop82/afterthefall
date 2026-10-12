"""Approved renewable Scrap uses normal storage, work and utility contracts."""
from contextlib import closing
import sqlite3,unittest
from database.create_database import connect_database
from game import economy,expansion,progression
from game.settlement import account_scope,read_state
from tests.fixtures import SupportWorld,fixed_map_seed

class RenewableScrapTests(unittest.TestCase):
 def setUp(self):
  with fixed_map_seed():self.w=SupportWorld(self)
  self.w.change('enable_consequences')
  with account_scope(self.w.a):expansion.transact(self.w.path,'enable',1000)
  self.bid=self.w.build('salvage_depot');self.w.staff(self.bid)
  self.w.sql('UPDATE settlement_resources SET scrap=0,metal=0,electronics=0')

 def test_each_level_produces_configured_scrap_without_consuming_ruins(self):
  w=self.w
  for level,expected in enumerate((8,12,18),1):
   with self.subTest(level=level):
    hp=w.state()['config']['buildings']['salvage_depot']['levels'][level-1]['hp']
    w.sql('UPDATE buildings SET level=?,current_hp=? WHERE building_id=?',(level,hp,self.bid))
    s=w.state();self.assertAlmostEqual(economy.rates(s,seconds=3600)['scrap']['production'],expected)
    with closing(connect_database(w.path)) as c,c,account_scope(w.a):
     c.row_factory=sqlite3.Row;economy.advance_resources(c,read_state(c),3600,4600)
    self.assertAlmostEqual(w.state()['resources']['scrap'],expected)
    w.sql('UPDATE settlement_resources SET scrap=0,metal=0,electronics=0')

 def test_unstaffed_damaged_and_uncovered_depot_produce_nothing(self):
  w=self.w
  for sql in ("UPDATE citizen_assignments SET ended_at=1000 WHERE building_id=?","UPDATE buildings SET current_hp=1 WHERE building_id=?","UPDATE buildings SET origin_x=0,origin_y=0 WHERE building_id=?"):
   with self.subTest(sql=sql):
    w.sql(sql,(self.bid,));self.assertEqual(economy.rates(w.state())['scrap']['production'],0)
    # Restore the active staffed source for the next boundary.
    w.sql('UPDATE buildings SET current_hp=500,origin_x=21,origin_y=18 WHERE building_id=?',(self.bid,))
    if not any(c['building_id']==self.bid for c in w.state()['citizens']):w.staff(self.bid)

 def test_full_storage_stops_output_and_production_xp(self):
  w=self.w;s=w.state();capacity=economy.storage(s)['material'];w.sql('UPDATE settlement_resources SET metal=?',(capacity,))
  s=w.state();self.assertEqual(economy.rates(s,seconds=3600)['scrap']['production'],0)
  worker=next(c for c in s['citizens'] if c['building_id']==self.bid)
  self.assertNotIn(worker['citizen_id'],progression.hourly_rates(s,seconds=3600))

 def test_output_is_limited_to_storage_room(self):
  w=self.w;capacity=economy.storage(w.state())['material'];w.sql('UPDATE settlement_resources SET metal=?',(capacity-2,))
  s=w.state();flow=economy.rates(s,seconds=3600);self.assertAlmostEqual(flow['scrap']['production'],2)
  worker=next(c for c in s['citizens'] if c['building_id']==self.bid)
  self.assertAlmostEqual(progression.hourly_rates(s,seconds=3600)[worker['citizen_id']],s['config']['progression']['work_xp_per_hour']*.25)

 def test_new_scrap_feeds_an_older_recycler_with_empty_input_stock(self):
  w=self.w;recycler=w.build('recycler');w.staff(recycler)
  worker=next(c['citizen_id'] for c in w.state()['citizens'] if c['building_id']==self.bid)
  w.change('release',building_id=self.bid,citizen_id=worker)
  w.sql("UPDATE buildings SET status='cleared' WHERE building_id=?",(self.bid,))
  newer=w.build('salvage_depot');w.staff(newer)
  self.assertGreater(newer,recycler)
  flow=economy.rates(w.state(),seconds=3600)
  self.assertAlmostEqual(flow['scrap']['production'],8);self.assertAlmostEqual(flow['scrap']['consumption'],8)
  self.assertAlmostEqual(flow['metal']['production'],5.6)

 def test_unchanged_finance_boundary_does_not_reload_the_catalogue(self):
  from unittest.mock import patch
  w=self.w
  with closing(connect_database(w.path)) as c,c,account_scope(w.a):
   c.row_factory=sqlite3.Row;expansion.boundary(c,read_state(c),1000)
   state=read_state(c);before=c.total_changes
   with patch('game.expansion.read_state',wraps=read_state) as snapshots:
    self.assertFalse(expansion.boundary(c,state,1000))
    self.assertEqual(snapshots.call_count,0)
   self.assertEqual(c.total_changes,before)

 def test_shared_refresh_skips_players_already_at_the_requested_time(self):
  from unittest.mock import patch
  from game.trading import player_state
  w=self.w
  with account_scope(w.a),patch('game.trading.player_state',wraps=player_state) as advance:
   expansion.refresh(w.path,1005);self.assertEqual(advance.call_count,2)
   before=w.state();advance.reset_mock();expansion.refresh(w.path,1005)
   self.assertEqual(advance.call_count,0);self.assertEqual(w.state(),before)
   self.assertEqual(w.state(w.b)['settlement']['simulation_processed_at'],1005)

 def test_latest_clock_lookup_has_an_index_on_new_and_existing_accounts_saves(self):
  w=self.w
  from game.accounts import prepare
  w.sql('DROP INDEX events_latest');prepare(w.path)
  with closing(connect_database(w.path)) as c:
   plan=c.execute("EXPLAIN QUERY PLAN SELECT event_data FROM game_events WHERE settlement_id=? AND event_type='prototype_xp_clock' ORDER BY event_id DESC LIMIT 1",(w.sa,)).fetchall()
   self.assertTrue(any('events_latest' in str(row) for row in plan),plan)

if __name__=='__main__':unittest.main()
