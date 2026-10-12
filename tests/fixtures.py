"""Shared disposable worlds; helpers contain no discoverable test cases.

Every world registers its cleanup with the owning test and gets a fresh save.
Building/player shortcuts prepare fixtures; assertions stay in feature tests.
"""
from contextlib import closing
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import urlencode

from accounts_app import AccountServer
from database.create_database import connect_database
from game import accounts, combat
from game.buildings import change_building
from game.settlement import account_scope, read_settlement, load_config
from game.simulation import advance_settlement


def fixed_map_seed():
    """Deterministic map/loot during setup; no patch remains in player code."""
    return patch('game.accounts.secrets.token_hex', side_effect=lambda size:'1'.zfill(size*2))

class SupportFixture:
    def setup_support(self):
     self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'game.db';accounts.prepare(self.path)
     self.a,self.sa=self.player('alpha');self.b,self.sb=self.player('bravo')
     self.sql('DELETE FROM settlement_derelicts');self.sql('DELETE FROM season_derelicts');self.sql('UPDATE settlements SET protection_until=1000')
     self.change('enable_support');self.config=load_config('prototype_v10')
     self.sql("UPDATE buildings SET level=3,current_hp=? WHERE building_type='town_hall'",(self.config['buildings']['town_hall']['levels'][2]['hp'],))
     self.sql('UPDATE settlement_resources SET food=300,water=300,scrap=300,metal=100,electronics=50')
     self.build('wind_turbine',sid=self.sa,x=21,y=15,level=3);self.build('wind_turbine',sid=self.sb,x=21,y=15,level=3)

    def sql(self,q,args=()):
     with closing(connect_database(self.path)) as c,c:return c.execute(q,args).fetchall()

    def player(self,name):
     a=self.sql("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES (?,'!',?,1000) RETURNING account_id",(name,name))[0][0]
     return a,accounts.join(self.path,a,name,1000)

    def state(self,account=None):
     with account_scope(account or self.a):return read_settlement(self.path)

    def advance(self,now,account=None):
     with account_scope(account or self.a):return advance_settlement(self.path,now)

    def change(self,action,now=1000,account=None,**args):
     with account_scope(account or self.a):return change_building(self.path,action,now=now,**args)

    def build(self,kind,sid=None,x=21,y=18,level=1):
     s=load_config('prototype_v10')['buildings'][kind]['levels'][level-1]
     return self.sql("INSERT INTO buildings(settlement_id,building_type,origin_x,origin_y,level,current_hp,status,created_at,completed_at) VALUES (?,?,?,?,?,?,'active',1000,1000) RETURNING building_id",(sid or self.sa,kind,x,y,level,s['hp']))[0][0]

    def staff(self,bid,count=1,account=None):
     ids=[c['citizen_id'] for c in self.state(account)['citizens'] if c['assignment']=='unassigned'][:count]
     for cid in ids:self.change('worker',building_id=bid,citizen_id=cid,account=account)
     return ids

    def unit(self,kind='offensive_drone',sid=None,hp=None,home=None):
     sid=sid or self.sa;storage=self.config['units'][kind]['storage']
     home=home or self.build(storage,sid=sid)
     return self.sql("INSERT INTO military_units(settlement_id,unit_type,current_hp,home_building_id,status,created_at) VALUES (?,?,?,?,'available',1000) RETURNING unit_id",(sid,kind,hp if hp is not None else self.config['units'][kind]['hp'],home))[0][0]

    def raid(self,citizens=None,units=None,now=4600):
     with account_scope(self.a):
      if not self.sql("SELECT 1 FROM treaties WHERE treaty_type='war'"):combat.command(self.path,'declare',1000,target_id=self.sb)
      return combat.command(self.path,'launch',now,target_id=self.sb,citizen_ids=citizens or [],drone_ids=units or [],objective='scrap')

    def extra(self,count=1):
     return [self.sql("INSERT INTO citizens(settlement_id,original_settlement_id,name,sex,current_hp,morale,status,created_at) VALUES (?,?,'Raider','unknown',100,60,'alive',1000) RETURNING citizen_id",(self.sa,self.sa))[0][0] for _ in range(count)]

    def weak(self):
     for c in self.state(self.b)['citizens']:
      if c['assignment']=='unassigned':self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,assigned_at) VALUES (?,?,'production',1000)",(c['citizen_id'],self.sb))

    def report(self):return json.loads(self.sql('SELECT report_data FROM battle_reports ORDER BY report_id LIMIT 1')[0][0])



class SupportWorld(SupportFixture):
    def __init__(self, owner):
        self.addCleanup = owner.addCleanup
        self.setup_support()



class CombatFixture:
    def setup_combat(self):
        seed=patch('game.scavenging.secrets.token_hex',return_value='ab'*32);seed.start();self.addCleanup(seed.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'combat.db';accounts.prepare(self.path)
        self.a,self.sa=self.player('alpha');self.b,self.sb=self.player('bravo')
        self.now=1000
        # Fixture opponents have already passed their normal beginner protection.
        self.sql('UPDATE settlements SET protection_until=1000')

    def sql(self,query,args=()):
        with closing(connect_database(self.path)) as c,c:return c.execute(query,args).fetchall()

    def player(self,name):
        aid=self.sql('INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES (?,\'!\',?,1000) RETURNING account_id',(name,name))[0][0]
        sid=accounts.join(self.path,aid,name,1000);return aid,sid

    def state(self,aid):
        with account_scope(aid):return read_settlement(self.path)

    def advance(self,aid,now):
        with account_scope(aid):return advance_settlement(self.path,now)

    def action(self,aid,action,now=1000,**kwargs):
        with account_scope(aid):return combat.command(self.path,action,now,**kwargs)

    def extra(self,sid,count=1,level=1,hp=100):
        result=[]
        for i in range(count):
            cid=self.sql("INSERT INTO citizens(settlement_id,original_settlement_id,name,sex,level,current_hp,morale,status,unemployed_since,created_at) VALUES (?,?,'Test raider','unknown',?, ?,60,'alive',1000,1000) RETURNING citizen_id",(sid,sid,level,hp))[0][0]
            self.sql("INSERT INTO citizen_settlement_history(citizen_id,settlement_id,joined_at,arrival_reason) VALUES (?,?,1000,'test_fixture')",(cid,sid))
            self.sql('INSERT INTO citizen_level_history(citizen_id,level,xp_total,reached_at) VALUES (?,?,0,1000)',(cid,level))
            result.append(cid)
        return result

    def launch(self,count=1,objective='scrap',level=1):
        ids=self.extra(self.sa,count,level=level,hp=100+(level-1)*8)
        self.action(self.a,'declare',target_id=self.sb)
        aid=self.action(self.a,'launch',now=4600,target_id=self.sb,citizen_ids=ids,objective=objective)
        return aid,ids

    def reports(self):return [json.loads(row[0]) for row in self.sql('SELECT report_data FROM battle_reports ORDER BY report_id')]

    def weak_defense(self):
        # Working citizens elsewhere do not join this resource-only defense.
        for c in self.state(self.b)['citizens']:
            if c['assignment']=='unassigned':self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,assigned_at) VALUES (?,?,'production',1000)",(c['citizen_id'],self.sb))



class CombatWorld(CombatFixture):
    def __init__(self, owner):
        self.addCleanup = owner.addCleanup
        self.setup_combat()



class HTTPFixture:
    def setup_http(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'http.db';accounts.prepare(self.path)
        self.players=[]
        for name in ('alpha','bravo'):
            with closing(connect_database(self.path)) as c,c:
                aid=c.execute("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES (?,'!',?,1000)",(name,name)).lastrowid
            accounts.join(self.path,aid,name,1000)
            token,session=accounts.new_session(self.path,aid,1000)
            self.players.append((aid,token,session['csrf']))
        self.server=AccountServer(('127.0.0.1',0),self.path,clock=lambda:1000)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,path='/',fields=None,player=0,origin=None):
        aid,token,csrf=self.players[player]
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1])
        headers={'Cookie':'settlement_session='+token}
        if fields is not None:
            headers['Content-Type']='application/x-www-form-urlencoded'
            if origin:headers['Origin']=origin
        c.request('POST' if fields is not None else 'GET',path,urlencode(fields,doseq=True) if fields is not None else None,headers)
        response=c.getresponse();body=response.read();status=response.status;c.close();return status,body

    def state(self,player=0):
        with account_scope(self.players[player][0]):return read_settlement(self.path)



class HTTPWorld(HTTPFixture):
    def __init__(self, owner):
        self.addCleanup = owner.addCleanup
        self.setup_http()

