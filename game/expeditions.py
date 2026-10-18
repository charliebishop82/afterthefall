"""Citizen-only provisioned expeditions, settled on the shared game clock."""
from pathlib import Path
from html import escape
import json
import math
from game import social,trading

CONFIG=Path(__file__).resolve().parents[1]/'config/expeditions.json'

def settings():
    rules=json.loads(CONFIG.read_text(encoding='utf-8'))
    if rules['return_minutes']<=0 or rules['max_hours']<=0 or rules['level_bonus']<0:
        raise ValueError('Invalid expedition timing or level bonus.')
    if any(value<0 for value in rules['yield_per_hour'].values()):raise ValueError('Invalid expedition yield.')
    return rules

def exists(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='waste_expeditions'").fetchone())

def prepare(c):
    c.execute('''CREATE TABLE IF NOT EXISTS waste_expeditions (
        expedition_id INTEGER PRIMARY KEY,settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
        season_id INTEGER NOT NULL REFERENCES seasons(season_id),
        status TEXT NOT NULL CHECK(status IN ('exploring','returning','returned')),
        started_at INTEGER NOT NULL,gather_until INTEGER NOT NULL,returns_at INTEGER NOT NULL,
        return_seconds INTEGER NOT NULL,food REAL NOT NULL,water REAL NOT NULL,
        food_rate REAL NOT NULL,water_rate REAL NOT NULL,yields TEXT NOT NULL,
        gathered TEXT NOT NULL DEFAULT '{}',delivered TEXT,discarded TEXT,returned_at INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS waste_expedition_citizens (
        expedition_id INTEGER NOT NULL REFERENCES waste_expeditions(expedition_id),
        citizen_id INTEGER NOT NULL REFERENCES citizens(citizen_id),level INTEGER NOT NULL,
        PRIMARY KEY(expedition_id,citizen_id))''')
    c.execute('CREATE INDEX IF NOT EXISTS expedition_returns ON waste_expeditions(settlement_id,status,returns_at)')

def read(c,sid):
    if not exists(c):return []
    rows=[dict(row) for row in c.execute('SELECT * FROM waste_expeditions WHERE settlement_id=? ORDER BY expedition_id',(sid,))]
    crews={}
    for eid,cid,name,level in c.execute('''SELECT ec.expedition_id,ec.citizen_id,c.name,ec.level
        FROM waste_expedition_citizens ec JOIN citizens c USING(citizen_id)
        JOIN waste_expeditions e USING(expedition_id) WHERE e.settlement_id=? ORDER BY ec.citizen_id''',(sid,)):
        crews.setdefault(eid,[]).append(dict(id=cid,name=name,level=level))
    for row in rows:row['crew']=crews.get(row['expedition_id'],[])
    return rows

def decorate(c,state):
    rows=read(c,state['settlement']['settlement_id']);state['expeditions']=rows
    if not rows:return
    away={cid for cid, in c.execute('''SELECT ec.citizen_id FROM waste_expedition_citizens ec
        JOIN waste_expeditions e USING(expedition_id) WHERE e.settlement_id=? AND e.status!='returned' ''',
        (state['settlement']['settlement_id'],))}
    for citizen in state['citizens']:
        citizen['exploring']=citizen['citizen_id'] in away
        citizen['away']=bool(citizen.get('away') or citizen['exploring'])

def next_boundary(state):
    now=state['settlement']['simulation_processed_at']
    times=[row['gather_until'] if row['status']=='exploring' else row['returns_at']
           for row in state.get('expeditions',[]) if row['status']!='returned']
    return min((t for t in times if t>now),default=None)

def finish(c,state,now):
    if not exists(c):return
    if state['settlement']['status']!='active':
        shift_clock(c,state,max(0,now-state['settlement']['simulation_processed_at']))
    c.execute('''UPDATE waste_expeditions SET gather_until=min(gather_until,?),returns_at=min(returns_at,?)
        WHERE settlement_id=? AND status!='returned' ''',(now,now,state['settlement']['settlement_id']))
    from game.settlement import read_state
    synchronize(c,read_state(c),now)

def live(state):
    now=state['settlement']['simulation_processed_at']
    return [dict(id=row['expedition_id'],status=row['status'],
                 seconds=max(0,row['returns_at']-now),
                 elapsed=max(0,min(now,row['returns_at'])-row['started_at']),
                 haul={r:rate*max(0,min(now,row['gather_until'])-row['started_at'])/3600
                       for r,rate in json.loads(row['yields']).items()})
            for row in display_rows(state)]

def shift_clock(c,state,seconds):
    if seconds and exists(c):
        c.execute('''UPDATE waste_expeditions SET started_at=started_at+?,gather_until=gather_until+?,returns_at=returns_at+?
            WHERE settlement_id=? AND status!='returned' ''',(seconds,seconds,seconds,state['settlement']['settlement_id']))

def synchronize(c,state,now):
    from game.economy import storage
    from game.settlement import read_state
    from game.simulation import _event
    changed=False
    for row in state.get('expeditions',[]):
        if row['status']=='returned' or now<row['gather_until']:continue
        hours=max(0,row['gather_until']-row['started_at'])/3600
        haul={r:rate*hours for r,rate in json.loads(row['yields']).items()}
        c.execute("UPDATE waste_expeditions SET status='returning',gathered=? WHERE expedition_id=?",(json.dumps(haul),row['expedition_id']))
        if now>=row['returns_at']:
            current=read_state(c);caps=storage(current)
            packed_hours=(row['returns_at']-row['started_at'])/3600
            incoming=dict(haul,food=max(0,row['food']-row['food_rate']*packed_hours),
                          water=max(0,row['water']-row['water_rate']*packed_hours))
            delivered={};lost={};material_room=max(0,caps['material']-sum(current['resources'][r] for r in ('scrap','metal','electronics')))
            for r in ('food','water','scrap','metal','electronics'):
                amount=incoming.get(r,0)
                room=max(0,caps[r]-current['resources'][r]) if r in ('food','water') else material_room
                delivered[r]=min(room,amount);lost[r]=max(0,amount-delivered[r])
                if r not in ('food','water'):material_room-=delivered[r]
                c.execute(f'UPDATE settlement_resources SET {r}={r}+?,updated_at=? WHERE settlement_id=?',
                          (delivered[r],now,state['settlement']['settlement_id']))
            c.execute("UPDATE waste_expeditions SET status='returned',delivered=?,discarded=?,returned_at=? WHERE expedition_id=?",
                      (json.dumps(delivered),json.dumps(lost),row['returns_at'],row['expedition_id']))
            c.execute('''UPDATE citizens SET unemployed_since=? WHERE citizen_id IN
                (SELECT citizen_id FROM waste_expedition_citizens WHERE expedition_id=?) AND status='alive' ''',
                (row['returns_at'],row['expedition_id']))
            from game.population import rebalance
            rebalance(c,read_state(c),now)
            _event(c,state,'wastes_expedition_returned',row['returns_at'],dict(expedition_id=row['expedition_id'],delivered=delivered,discarded=lost))
            from game.operation_results import expedition_summary
            from game.social import notify
            title,summary=expedition_summary(dict(gathered=haul,delivered=delivered,discarded=lost))
            notify(c,state['settlement']['account_id'],state['season']['season_id'],'expedition_return',f'Expedition #{row["expedition_id"]}: {title}. {summary}',row['returns_at'],'expedition',row['expedition_id'])
        changed=True
    return changed

def command(path,action,now,*,citizen_ids=None,food=None,water=None,expedition_id=None):
    from game.settlement import read_state
    from game.simulation import _event
    if action not in ('launch','recall'):raise ValueError('Choose Launch or Recall.')
    with social.transaction(path,now,new=action=='launch') as (c,state):
        prepare(c);sid=state['settlement']['settlement_id']
        if action=='recall':
            row=c.execute("SELECT * FROM waste_expeditions WHERE expedition_id=? AND settlement_id=? AND status='exploring'",(expedition_id,sid)).fetchone()
            if not row:raise ValueError('Choose your expedition that is still exploring.')
            at=now if state['settlement']['status']=='active' else state['settlement']['simulation_processed_at']
            c.execute("UPDATE waste_expeditions SET gather_until=?,returns_at=?,status='returning' WHERE expedition_id=?",
                      (at,at+row['return_seconds'],expedition_id))
            # Snapshot accumulated haul for the return panel; no further gathering.
            hours=max(0,at-row['started_at'])/3600
            haul={r:rate*hours for r,rate in json.loads(row['yields']).items()}
            c.execute('UPDATE waste_expeditions SET gathered=? WHERE expedition_id=?',(json.dumps(haul),expedition_id))
            _event(c,state,'wastes_expedition_recalled',now,dict(expedition_id=expedition_id))
            return expedition_id
        if state['settlement']['status']!='active':raise ValueError('Resume the settlement before launching an expedition.')
        ids=citizen_ids or []
        if not ids or any(type(cid) is not int for cid in ids) or len(set(ids))!=len(ids):raise ValueError('Choose distinct available citizens.')
        selected=[citizen for citizen in state['citizens'] if citizen['citizen_id'] in ids]
        if len(selected)!=len(ids) or any(citizen.get('away') or citizen['assignment']!='unassigned' or citizen['current_hp']<=0 or not citizen.get('integrated',True) for citizen in selected):
            raise ValueError('Explorers must be living, integrated, unassigned citizens at home.')
        if len(selected)>=sum(not citizen.get('away') for citizen in state['citizens']):raise ValueError('Keep at least one citizen at home.')
        for resource,value in [('food',food),('water',water)]:
            if type(value) is not int or not 1<=value<=1_000_000:raise ValueError('Pack positive whole Food and Water quantities up to one million.')
            if trading.available(state,resource)+1e-8<value:raise ValueError('Not enough unreserved '+resource.title()+' to pack.')
        config=settings();normal=state['config'].get('simulation')
        if not normal:
            from game.settlement import load_config
            normal=load_config('prototype_v2')['simulation']
        food_rate=len(ids)*normal['food_per_citizen_per_hour'];water_rate=len(ids)*normal['water_per_citizen_per_hour']
        travel=math.ceil(config['return_minutes']*60)
        seconds=min(math.floor(min(food/food_rate,water/water_rate)*3600)-travel,
                    math.floor(config['max_hours']*3600),state['season']['ends_at']-now-travel)
        if seconds<=0:raise ValueError('Pack enough for exploration plus the 15-minute return journey.')
        rates={r:rate*sum(1+(citizen['level']-1)*config['level_bonus'] for citizen in selected)
               for r,rate in config['yield_per_hour'].items()}
        eid=c.execute('''INSERT INTO waste_expeditions(settlement_id,season_id,status,started_at,gather_until,returns_at,
            return_seconds,food,water,food_rate,water_rate,yields) VALUES (?,?,'exploring',?,?,?,?,?,?,?,?,?)''',
            (sid,state['season']['season_id'],now,now+seconds,now+seconds+travel,travel,food,water,food_rate,water_rate,json.dumps(rates))).lastrowid
        for citizen in selected:c.execute('INSERT INTO waste_expedition_citizens VALUES (?,?,?)',(eid,citizen['citizen_id'],citizen['level']))
        c.execute('UPDATE settlement_resources SET food=food-?,water=water-?,updated_at=? WHERE settlement_id=?',(food,water,now,sid))
        _event(c,state,'wastes_expedition_launched',now,dict(expedition_id=eid,citizen_ids=ids,food=food,water=water,returns_at=now+seconds+travel,yield_per_hour=rates))
        return eid

def panel(state,token):
    from datetime import datetime,timezone
    config=settings()
    html='<section class="production-panel" id="expeditions"><h2>Explore the Wastes</h2><p>Send free citizens to gather materials without attacking another player. Pack Food and Water upfront; the scarcer supply sets their time away. Provisions include the 15-minute return trip. Explorers do not consume home supplies or defend/work at home. No expedition combat injuries or death in this prototype.</p>'
    html+=f'<p>Per citizen/hour: 2 Scrap · 0.5 Metal · 0.1 Electronics; +{config["level_bonus"]*100:g}% per level above 1. Maximum {config["max_hours"]:g} hours gathering. Return trips gather nothing; unused provisions come home. Storage overflow is discarded.</p>'
    eligible=[c for c in state['citizens'] if not c.get('away') and c['assignment']=='unassigned' and c['current_hp']>0 and c.get('integrated',True)]
    if eligible and state['season']['status']=='active' and state['settlement']['status']=='active':
        choices=''.join(f'<label><input type="checkbox" name="citizen_id" value="{c["citizen_id"]}">{escape(c["name"])} (level {c["level"]})</label>' for c in eligible)
        html+=social.form(token,'expeditions','launch',choices+'<label>Packed Food <input name="food" type="number" min="1" max="1000000" value="6" required></label><label>Packed Water <input name="water" type="number" min="1" max="1000000" value="6" required></label><button>Launch expedition</button></form>')
    else:html+='<p>Release a worker to make a citizen available. Launches require an active season and settlement.</p>'
    for row in display_rows(state):
        stamp=datetime.fromtimestamp(row['returns_at'],timezone.utc).strftime('%d %b %H:%M UTC')
        eid=row['expedition_id']
        crew=crew_label(row)
        seconds=max(0,row['returns_at']-state['settlement']['simulation_processed_at'])
        elapsed=max(0,min(state['settlement']['simulation_processed_at'],row['returns_at'])-row['started_at'])
        html+=f'<p><strong>{escape(crew)}</strong></p><p id="expedition-elapsed-{eid}">Active time away: {math.floor(elapsed/60)} min</p>'
        html+=f'<div class="building-controls"><h3>Expedition #{eid} · <span id="expedition-status-{eid}">{row["status"].title()}</span></h3><p>Return: {stamp} · <span id="expedition-eta-{eid}">Home in {math.ceil(seconds/60)} min</span></p><p id="expedition-haul-{eid}"></p>'
        if row['status']=='exploring':html+=social.form(token,'expeditions','recall',social.hidden('expedition_id',eid)+f'<button id="expedition-recall-{eid}">Recall — 15-minute return</button></form>')
        if row['status']=='returned':
            html+='<p>Delivered: '+escape(', '.join(f'{v:.1f} {r.title()}' for r,v in json.loads(row['delivered']).items() if v>0) or 'Nothing retained')+'</p>'
            lost=json.loads(row['discarded'])
            if any(lost.values()):html+='<p>Discarded because storage was full: '+escape(', '.join(f'{v:.1f} {r.title()}' for r,v in lost.items() if v>0))+'</p>'
        html+='</div>'
    return html+'</section>'


def display_rows(state):
    rows=state.get('expeditions',[])
    active=sorted((r for r in rows if r['status']!='returned'),key=lambda r:r['expedition_id'],reverse=True)
    history=sorted((r for r in rows if r['status']=='returned'),key=lambda r:r['expedition_id'],reverse=True)[:10]
    return active+history

def crew_label(row):
    return ', '.join(f"{c['name']} (#{c['id']}, level {c['level']} at launch)" for c in row.get('crew',[])) or 'Crew details unavailable'

def summary(state):
    active=[r for r in display_rows(state) if r['status']!='returned']
    if not active:return ''
    now=state['settlement']['simulation_processed_at']
    html='<section class="production-panel" id="expeditions-summary"><h2>Expeditions underway</h2>'
    for row in active:
        eid=row['expedition_id']
        html+=f'<p>{escape(crew_label(row))} · <span id="expedition-summary-{eid}">{row["status"].title()} · home in {math.ceil(max(0,row["returns_at"]-now)/60)} min</span></p>'
    return html+'<a href="#expeditions">Manage expeditions / recall early</a></section>'
