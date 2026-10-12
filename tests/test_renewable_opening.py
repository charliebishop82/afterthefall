"""A playable renewable-economy opening without resource grants."""
from contextlib import closing
from pathlib import Path
import sqlite3,tempfile,unittest
from database.create_database import connect_database
from game import buildings,economy,lobby
from game.settlement import account_scope,read_settlement
from game.simulation import advance_settlement
from tests.fixtures import fixed_map_seed

class RenewableOpeningTests(unittest.TestCase):
 def test_starting_package_can_build_food_water_and_renewable_scrap(self):
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'opening.db';lobby.prepare(path)
   with closing(connect_database(path)) as c,c:
    actor=c.execute("INSERT INTO accounts(username,password_hash,display_name,created_at,is_admin) VALUES ('operator','!','Operator',1000,1)").lastrowid
    player=c.execute("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES ('player','!','Player',1000)").lastrowid
   lobby.enroll(path,player,'Opening',1000)
   with fixed_map_seed():lobby.start(path,actor,1000,'Disposable opening')
   with account_scope(player):
    now=1000
    def state():return read_settlement(path)
    def build(kind):
     nonlocal now
     s=state();citizen=next(c['citizen_id'] for c in s['citizens'] if c['assignment']=='unassigned')
     for x in range(12,26):
      for y in range(12,26):
       candidate=dict(building_type=kind,origin_x=x,origin_y=y,rotation=0,level=1)
       if buildings.coverage(s,candidate)<.75:continue
       try:
        with closing(connect_database(path)) as c:buildings.validate_placement(c,s,candidate)
       except ValueError:continue
       result=buildings.change_building(path,'build',building_type=kind,x=x,y=y,now=now)
       bid=result['buildings'][-1]['building_id']
       buildings.change_building(path,'builder',building_id=bid,citizen_id=citizen,now=now)
       # A conservative real wait accounts for partial productivity/condition.
       now+=int(s['config']['buildings'][kind]['levels'][0]['minutes']*120)
       result=advance_settlement(path,now)
       b=next(b for b in result['buildings'] if b['building_id']==bid)
       self.assertEqual(b['status'],'active')
       return bid,citizen
     self.fail('No safe building site for '+kind)
    bid,cid=build('garden');buildings.change_building(path,'worker',building_id=bid,citizen_id=cid,now=now)
    build('rain_collector');build('rain_collector')
    bid,cid=build('salvage_depot');buildings.change_building(path,'worker',building_id=bid,citizen_id=cid,now=now)
    before=state();rates=economy.rates(before)
    self.assertGreaterEqual(rates['food']['net'],0);self.assertGreaterEqual(rates['water']['net'],0)
    self.assertGreater(rates['scrap']['production'],0)
    after=advance_settlement(path,now+3600)
    self.assertGreater(after['resources']['scrap'],before['resources']['scrap'])
    self.assertEqual(len(after['citizens']),6);self.assertEqual(after['buildings'][0]['level'],1)
    self.assertTrue(all(d['status']=='untouched' for d in after['derelicts']))

if __name__=='__main__':unittest.main()
