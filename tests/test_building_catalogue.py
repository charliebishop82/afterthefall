"""Whole catalogue progression contracts, using disposable upgraded fixtures."""
from contextlib import closing
import copy,json,re,sqlite3,unittest
from unittest.mock import patch
from database.create_database import connect_database
from game import buildings,expansion
from game.settlement import account_scope,read_state
from tests.fixtures import SupportWorld,fixed_map_seed,database_baseline,baseline_world

def catalogue_baseline(owner):
 with fixed_map_seed():world=SupportWorld(owner)
 world.change('enable_consequences')
 with account_scope(world.a):expansion.transact(world.path,'enable',1000)
 return world

class BuildingCatalogueTests(unittest.TestCase):
 @property
 def w(self):
  # Build a fresh per-test world only when the case actually needs it.
  if not hasattr(self,'_world'):
   self._world=baseline_world(self,'catalogue',catalogue_baseline)
  return self._world

 def test_cached_catalogue_load_returns_independent_nested_rules(self):
  from game.settlement import load_config
  first=load_config('prototype_v13');original=first['buildings']['garden']['levels'][0]['hp']
  first['buildings']['garden']['levels'][0]['hp']=1
  self.assertEqual(load_config('prototype_v13')['buildings']['garden']['levels'][0]['hp'],original)

 def test_renewable_overlay_does_not_break_earlier_activation_steps(self):
  from game.settlement import load_config
  with closing(connect_database(self.w.path)) as c:
   result,active=expansion.overlay(c,self.w.state()['season']['season_id'],load_config('prototype_v5'))
  self.assertTrue(active);self.assertNotIn('salvage_depot',result['buildings'])

 def test_overlay_isolates_source_and_cached_nested_rules(self):
  w=self.w;s=w.state();source=copy.deepcopy(s['config']);saved=copy.deepcopy(source);cached=copy.deepcopy(expansion.config())
  with closing(connect_database(w.path)) as c:
   result,active=expansion.overlay(c,s['season']['season_id'],source)
  self.assertTrue(active);result['buildings']['town_hall']['levels'][0]['hp']=1;result['buildings']['vault']['levels'][0]['hp']=1
  self.assertEqual(source,saved);self.assertEqual(expansion.config(),cached)

 def test_every_upgrade_spends_destination_cost_and_completes_once(self):
  w=self.w;catalog=w.state()['config']['buildings'];now=1000
  # Each building/level starts from the same private, committed fixture.
  # Do not accumulate cleared sites and completed jobs across catalogue cases.
  with database_baseline(w.path) as restore:
   for kind,info in catalog.items():
    for old in range(1,info['max_level']):
     with self.subTest(building=kind,level=old+1):
      restore()
      target=info['levels'][old];previous=info['levels'][old-1]
      with closing(connect_database(w.path)) as c,c:
       c.execute('DELETE FROM citizen_assignments WHERE assignment_type<>\'administrator\'')
       c.execute("UPDATE buildings SET status='cleared' WHERE building_type<>'town_hall'")
       c.execute('UPDATE settlement_resources SET scrap=2000,metal=2000,electronics=2000')
       c.execute("INSERT INTO buildings(settlement_id,building_type,origin_x,origin_y,level,current_hp,status,created_at,completed_at) VALUES (?,'warehouse',0,0,3,1000,'active',?,?)",(w.sa,now,now))
       if kind=='town_hall':
        bid=c.execute("SELECT building_id FROM buildings WHERE settlement_id=? AND building_type='town_hall'",(w.sa,)).fetchone()[0]
        c.execute('UPDATE buildings SET level=?,current_hp=? WHERE building_id=?',(old,previous['hp']*.8,bid))
       else:
        c.execute("UPDATE buildings SET level=3,current_hp=2200 WHERE building_type='town_hall'")
        bid=c.execute("INSERT INTO buildings(settlement_id,building_type,origin_x,origin_y,level,current_hp,status,created_at,completed_at) VALUES (?,?,21,18,?,?,'active',?,?)",(w.sa,kind,old,previous['hp']*.8,now,now)).lastrowid
      before=dict(zip(('scrap','metal','electronics'),w.sql('SELECT scrap,metal,electronics FROM settlement_resources WHERE settlement_id=?',(w.sa,))[0]));after=w.change('upgrade',now=now,building_id=bid,expected_level=old)
      for r in ('scrap','metal','electronics'):self.assertAlmostEqual(before[r]-after['resources'][r],target[r])
      job=next(j for j in after['jobs'] if j['target_building_id']==bid and j['status'] in ('active','paused'))
      self.assertEqual(job['work_required'],target['minutes']*60)
      cid=next(c['citizen_id'] for c in after['citizens'] if c['assignment']=='unassigned')
      staffed=w.change('builder',now=now,building_id=bid,citizen_id=cid)
      with closing(connect_database(w.path)) as c,c,account_scope(w.a):
       c.row_factory=sqlite3.Row;buildings.progress_jobs(c,staffed,job['work_required']*10,now+1)
       completed=read_state(c);b=next(b for b in completed['buildings'] if b['building_id']==bid)
       self.assertEqual(b['level'],old+1);self.assertEqual(b['status'],'active');self.assertAlmostEqual(b['current_hp']/target['hp'],.8)
       self.assertEqual(next(x for x in completed['citizens'] if x['citizen_id']==cid)['assignment'],'unassigned')
       buildings.progress_jobs(c,completed,job['work_required'],now+2)
       self.assertEqual(read_state(c)['resources'],completed['resources'])
      # Keep the fixture clock fixed; elapsed production is tested elsewhere.

 def test_upgrade_controls_exclude_reserved_materials(self):
  from game.building_views import panels
  bid=self.w.build('greenhouse');s=self.w.state()
  s['resources'].update(scrap=1000,metal=1000,electronics=1000)
  s['reserved']={'scrap':1000}
  html=''.join(panels(s,'token'))
  forms=re.findall(r'<form.*?</form>',html,re.S)
  upgrade=next(f for f in forms if 'name="action" value="upgrade"' in f and f'name="building_id" value="{bid}"' in f)
  self.assertIn('disabled',upgrade)
  s['reserved']={};html=''.join(panels(s,'token'))
  upgrade=next(f for f in re.findall(r'<form.*?</form>',html,re.S) if 'name="action" value="upgrade"' in f and f'name="building_id" value="{bid}"' in f)
  self.assertNotIn('disabled',upgrade)

 def test_catalogue_has_valid_levels_workers_and_positive_upgrade_times(self):
  catalog=self.w.state()['config']['buildings'];self.assertEqual(len(catalog),48)
  starters={k for k in catalog if k.startswith('starter_')}
  self.assertEqual(starters,{'starter_offensive_hangar','starter_air_defense_bay','starter_ground_defense_bay','starter_engineering_workshop','starter_missile_silo','starter_interceptor_battery'})
  self.assertTrue(all(catalog[k]['unlock']==1 and catalog[k]['max_level']==1 for k in starters))
  for kind,b in catalog.items():
   with self.subTest(building=kind):
    self.assertEqual(len(b['levels']),b['max_level']);self.assertIn(b['unlock'],(1,2,3))
    for l in b['levels']:
     self.assertGreaterEqual(l['workers'],b['workers_min']);self.assertGreater(l['hp'],0)
     self.assertTrue(all(l[r]>=0 for r in ('scrap','metal','electronics')))
    for previous,target in zip(b['levels'],b['levels'][1:]):
     self.assertGreater(target['minutes'],0)
     for r in ('hp','workers','food_storage','water_storage','material_storage'):
      self.assertGreaterEqual(target[r],previous[r])

