"""Shared disposable worlds; helpers contain no discoverable test cases.

Every world registers its cleanup with the owning test and gets a fresh save.
Building/player shortcuts prepare fixtures; assertions stay in feature tests.
"""
from contextlib import closing, contextmanager
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


@contextmanager
def database_baseline(path):
    """Snapshot a disposable test save once; restore before independent cases.

    Use SQLite backup rather than copying files, so committed WAL content is
    included. Call restore only with all other fixture connections closed.
    The baseline is private to this context, never shared across tests/workers.
    No production rules or command functions are patched.
    """
    with closing(sqlite3.connect(':memory:')) as baseline:
        with closing(connect_database(path)) as source:
            source.backup(baseline)

        def restore():
            with closing(connect_database(path)) as target:
                baseline.backup(target)

        yield restore


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
        # Real feature cases clone the class baseline; its factory uses a plain owner.
        import unittest
        if isinstance(owner,unittest.TestCase):
            world=baseline_world(owner,'support',SupportWorld)
            self.__dict__.update(vars(world))
            return
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
        import unittest
        if isinstance(owner,unittest.TestCase):
            world=baseline_world(owner,'combat',CombatWorld)
            self.__dict__.update(vars(world))
            return
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
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.01},daemon=True);self.thread.start()
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



class FlaskFixture:
    """Disposable Flask world with real account registration for auth coverage."""
    def setUp(self):
        from flask_app import create_app
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'playtest.db'; self.now = 1000
        self.app = create_app(self.path, clock=lambda:self.now)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def get(self, client=None, path='/', **kwargs):
        return (client or self.client).get(path, base_url='http://127.0.0.1:8767', **kwargs)

    def post(self, path, fields, client=None, **kwargs):
        return (client or self.client).post(path, data=fields, base_url='http://127.0.0.1:8767', **kwargs)

    def console_post(self, path, fields):
        from flask_app import COOKIE
        from admin_suite import create_app as console_app, COOKIE as console_cookie
        client = console_app(self.path, clock=lambda:self.now).test_client()
        player_token = self.client.get_cookie(COOKIE, domain='127.0.0.1').value
        actor = accounts.session(self.path, player_token, self.now)
        token, session = accounts.new_session(self.path, actor['account_id'], self.now)
        client.set_cookie(console_cookie, token, domain='127.0.0.1')
        return client.post(path, data={**fields, 'token':session['csrf']}, base_url='http://127.0.0.1:8768')

    def player(self, name, client=None, enroll=True):
        import re
        client = client or self.client
        response = self.get(client)
        token = re.search('name="token" value="([^"]+)"', response.text)[1]
        result = self.post('/register', {'username':name, 'password':'test-password-long', 'token':token, 'is_admin':'1'}, client)
        self.assertEqual(result.status_code, 303)
        token = re.search('name="token" value="([^"]+)"', self.get(client).text)[1]
        if enroll:self.assertEqual(self.post('/settlement', {'name':name, 'token':token}, client).status_code, 303)
        return token

    def launch(self):
        from game import admin
        token = self.player('owner'); admin.grant(self.path, 'owner', self.now)
        self.assertEqual(self.console_post('/lobby', {'action':'start', 'reason':'ready', 'token':token}).status_code, 303)
        return token



class EquipmentFixture(FlaskFixture):
    """Seed accounts for equipment tests; real gameplay forms stay unchanged.

    Registration/hashing/login have dedicated real Flask/security coverage.
    Each equipment test still creates its own database and normal sessions.
    """
    def player(self, name, client=None, enroll=True):
        from flask_app import COOKIE
        client=client or self.client
        with closing(connect_database(self.path)) as c,c:
            aid=c.execute("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES (?,'!',?,?)",(name,name,self.now)).lastrowid
        token,session=accounts.new_session(self.path,aid,self.now)
        client.set_cookie(COOKIE,token,domain='127.0.0.1')
        if enroll:
            self.assertEqual(self.post('/settlement',{'name':name,'token':session['csrf']},client).status_code,303)
        return session['csrf']

    def start(self):
        self.token=self.launch()
        self.a=self.sql("SELECT account_id FROM accounts WHERE username='owner'")[0][0]
        self.sid=self.sql('SELECT settlement_id FROM settlements WHERE account_id=?',(self.a,))[0][0]
        self.sql('UPDATE settlement_resources SET credits=100000 WHERE settlement_id=?',(self.sid,))

    def sql(self,query,args=()):
        with closing(connect_database(self.path)) as c,c:return c.execute(query,args).fetchall()

    def state(self):
        with account_scope(self.a):return read_settlement(self.path)

    def home(self,kind):
        state=self.state();key=state['config']['units'][kind]['starter_storage']
        bid=self.sql("INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at) VALUES (?,?,1,18,21,150,'active',1000,1000) RETURNING building_id",(self.sid,key))[0][0]
        if kind=='repair_drone':
            citizen=next(c for c in state['citizens'] if c['assignment']=='unassigned')
            self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,?,'production',?,1000)",(citizen['citizen_id'],self.sid,bid))
        return bid

    def trade(self,action,kind='offensive_drone',quantity=1):
        from game import equipment_market as market
        with account_scope(self.a):return market.transact(self.path,'equipment_'+action,1000,unit_type=kind,quantity=quantity)



class WorldBaseline:
    """Prepare once, then give each test its own SQLite backup and attributes.

    Baselines belong to one test class/process and never touch player saves.
    Use only for fixture setup, not tests of initialization or migrations.
    """
    def __init__(self, owner, factory):
        from types import SimpleNamespace
        self.world=factory(SimpleNamespace(addCleanup=owner.addClassCleanup))
        self.saved=sqlite3.connect(':memory:')
        owner.addClassCleanup(self.saved.close)
        with closing(connect_database(self.world.path)) as source:
            source.backup(self.saved)

    def restore(self, owner):
        from copy import deepcopy
        # Allocate via the fixture type: built-in containers reject object.__new__.
        # Do not invoke __init__, which would rebuild the world.
        fixture_type=type(self.world)
        world=fixture_type.__new__(fixture_type)
        for name,value in vars(self.world).items():
            if not name.startswith('_') and name not in ('tmp','temp','path','addCleanup'):
                setattr(world,name,deepcopy(value))
        world.addCleanup=owner.addCleanup
        world.tmp=tempfile.TemporaryDirectory();owner.addCleanup(world.tmp.cleanup)
        if hasattr(self.world,'temp'):world.temp=world.tmp
        world.path=Path(world.tmp.name)/'baseline-copy.db'
        # This path is new: the production connector deliberately requires an existing file.
        # SQLite backup creates the private test database before normal game connections open it.
        with closing(sqlite3.connect(world.path)) as target:
            self.saved.backup(target)
        return world


def baseline_world(owner,key,factory):
    """Lazy per-class fixture baseline; restored saves are never shared."""
    cls=type(owner)
    if '_world_baselines' not in cls.__dict__:
        cls._world_baselines={}
        cls.addClassCleanup(cls._world_baselines.clear)
    if key not in cls._world_baselines:
        cls._world_baselines[key]=WorldBaseline(cls,factory)
    return cls._world_baselines[key].restore(owner)


def restore_case_baseline(case,key,prepare='prepare_world'):
    """Restore public fixture fields without sharing TestCase runtime state."""
    def factory(owner):
        world=type(case)()
        world.addCleanup=owner.addCleanup
        if callable(prepare):prepare(world)
        else:getattr(world,prepare)()
        return world
    world=baseline_world(case,key,factory)
    case.__dict__.update({k:v for k,v in vars(world).items()
                         if not k.startswith('_') and k!='addCleanup'})


def versioned_support_world(owner,action,version):
    def factory(preparer):
        world=SupportWorld(preparer)
        world.change(action)
        world.config=load_config(version)
        return world
    return baseline_world(owner,action,factory)
