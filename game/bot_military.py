"""Military choices use own equipment and ordinary public target information."""
from contextlib import closing
import random
import sqlite3
from database.create_database import connect_database
from game.buildings import rules,spec,footprint,coverage
from game.trading import available


def public_targets(path,state,now):
    from game import combat,diplomacy
    sid=state['settlement']['settlement_id'];season=state['season']['season_id']
    with closing(connect_database(path)) as c:
        c.row_factory=sqlite3.Row
        result=[]
        for row in c.execute('''SELECT s.settlement_id,s.settlement_name,s.protection_until FROM settlements s
            JOIN accounts a USING(account_id) WHERE s.season_id=? AND s.settlement_id!=? AND s.status='active'
            AND a.is_active=1 ORDER BY s.settlement_id''',(season,sid)):
            other={'settlement':{'settlement_id':row['settlement_id']}}
            war=combat.war(c,state,other,now)
            result.append(dict(row,blocked=combat.blocked(c,state,other,now) or diplomacy.war_cooldown(c,sid,row['settlement_id'],now),
                               war_effective_at=war['effective_at'] if war else None,
                               raid_in_flight=bool(c.execute("SELECT 1 FROM attacks WHERE attacker_settlement_id=? AND defender_settlement_id=? AND status='in_flight'",(sid,row['settlement_id'])).fetchone())))
        return result


def build_plan(state,kind,*,ignore_cost=False):
    catalog=rules(state)['buildings'];hall=state['buildings'][0]
    if kind not in catalog or hall['level']<catalog[kind]['unlock']:return None
    costs=catalog[kind]['levels'][0]
    if not ignore_cost and any(available(state,r)<costs[r] for r in ('scrap','metal','electronics')):return None
    occupied=[(b['origin_x'],b['origin_y'],*footprint(state,b)) for b in state['buildings'] if b['status'] not in ('cleared','demolished')]
    occupied += [(d['origin_x'],d['origin_y'],*state['config']['derelicts'][d['derelict_type']]['footprint']) for d in state['derelicts'] if d['status']!='cleared']
    for rotation in (0,90):
        w,h=catalog[kind]['footprint'];w,h=(h,w) if rotation else (w,h)
        positions=sorted(((x,y) for x in range(state['config']['map_width']-w+1) for y in range(state['config']['map_height']-h+1)),key=lambda p:(p[0]-hall['origin_x'])**2+(p[1]-hall['origin_y'])**2)
        for x,y in positions:
            if any(x<ox+ow and x+w>ox and y<oy+oh and y+h>oy for ox,oy,ow,oh in occupied):continue
            candidate=dict(building_type=kind,origin_x=x,origin_y=y,rotation=rotation,level=1)
            if coverage(state,candidate)>=rules(state)['construction']['coverage_fraction']:
                return dict(building_type=kind,x=x,y=y,rotation=rotation)
    return None


def combat_decision(state,targets,personality,seed,action):
    from game import combat,drones,structural
    if personality=='defensive' or state['season']['status']!='active' or state['settlement']['simulation_processed_at']>=state['season']['finalization_at']:return None
    if state['settlement']['attacks_remaining']<=0:return None
    home=combat.home(state);limit=max(0,len(home)-int(combat.rule('raid_home_population_min')))
    citizens=[c['citizen_id'] for c in home if c['assignment']=='unassigned' and c.get('integrated',True) and c['current_hp']/combat.maximum_hp(state,c)>=combat.rule('citizen_low_hp_raid_threshold')/100][:min(2,limit)]
    units=[u['unit_id'] for u in drones.ready(state,'offensive_drone')][:3]
    missiles=min(2,sum(i['quantity'] for i in structural.ammunition(state,'missile')))
    if not citizens and not units and not missiles:return None
    if len(home)<combat.rule('raid_home_population_min'):return None
    now=state['settlement']['simulation_processed_at'];rng=random.Random(seed)
    candidates=[t for t in targets if not t['blocked'] and not t['raid_in_flight'] and (t['protection_until'] or 0)<=now]
    rng.shuffle(candidates)
    for target in candidates:
        if target['war_effective_at'] is None:
            return action('/conflict','Declare war on an eligible public target; normal warning applies.',action='declare',target_id=target['settlement_id'])
        if target['war_effective_at']>now:continue
        objectives=list(combat.OBJECTIVES)
        if state.get('expansion'):
            objectives+=['credits']
            if citizens:objectives+=['population']
        if structural.enabled(state):objectives+=['infrastructure']
        return action('/conflict','Launch a raid after warning; keep six home and preserve workers/Administrator.',
            action='launch',target_id=target['settlement_id'],objective=rng.choice(objectives),
            citizen_id=citizens,drone_id=units,missile_count=missiles)
    return None


def choose_military(state,targets,personality,seed,action,free,market=None):
    from game import manufacturing,structural
    rng=random.Random(seed)
    # Combat uses idle eligible citizens and ready hardware; no privileged targeting.
    if rng.random()<({'aggressive':.85,'balanced':.3,'builder':.15,'scavenger':.1}.get(personality,0)):
        raid=combat_decision(state,targets,personality,seed,action)
        if raid:return raid
    projects=any(j['job_type'] in ('construction','upgrade','repair') and j['status'] in ('active','paused') for j in state['jobs'])
    if state['season']['status']!='active' or state['settlement']['simulation_processed_at']>=state['season']['finalization_at']:return None
    factories=[b for b in state['buildings'] if b['status']=='active' and b['building_type'] in ('drone_factory','munitions_factory','engineering_workshop')]
    for building in factories:
        if spec(state,building)['workers'] and not any(c['building_id']==building['building_id'] and c['assignment']=='production' for c in state['citizens']) and free and coverage(state,building)>=rules(state)['construction']['coverage_fraction']:
            return action('/buildings','Assign military factory/workshop staff.',action='worker',building_id=building['building_id'],citizen_id=free[0]['citizen_id'])
    if free and personality=='defensive' and not any(c['assignment']=='patrol' for c in state['citizens']):
        return action('/buildings','Assign one citizen to settlement patrol defense.',action='patrol',citizen_id=free[0]['citizen_id'])
    for post in state['buildings']:
        if post['building_type']=='guard_post' and post['status']=='active' and free and not any(c['building_id']==post['building_id'] and c['assignment']=='defender' for c in state['citizens']) and coverage(state,post)>=rules(state)['construction']['coverage_fraction']:
            return action('/buildings','Staff a Guard Post.',action='guard',building_id=post['building_id'],citizen_id=free[0]['citizen_id'])
    desired=['air_defense_drone','ground_defense_drone','interceptor'] if personality=='defensive' else ['offensive_drone','ground_defense_drone','air_defense_drone','missile','interceptor']
    rng.shuffle(desired)
    for kind in desired:
        unit=state['config']['units'].get(kind)
        if not unit:continue
        count=sum(u['unit_type']==kind and u['status']!='destroyed' for u in state.get('units',[]))+sum(i['quantity'] for i in state.get('inventory',[]) if i['unit_type']==kind)
        quota=3 if personality=='aggressive' and kind in ('offensive_drone','missile') else 2
        if count>=quota:continue
        for factory in factories:
            if factory['building_type']!=unit['factory'] or any(j['job_type']=='manufacturing' and j['production_building_id']==factory['building_id'] and j['status'] in ('queued','active','paused') for j in state['jobs']):continue
            if not any(c['building_id']==factory['building_id'] and c['assignment']=='production' for c in state['citizens']):continue
            if not manufacturing.home_for(state,kind):continue
            if any(available(state,r)<unit[r] for r in ('metal','electronics')):
                from game.bot_market import choose_market
                supplies=choose_market(state,{},seed,action,market,costs={r:unit[r] for r in ('metal','electronics')},purpose='manufacturing '+kind)
                if supplies:return supplies
                continue
            return action('/manufacturing','Produce one affordable '+kind+' with compatible free storage.',action='queue',building_id=factory['building_id'],unit_type=kind,quantity=1,repeat='0')
    if not projects and free:
        from game.repairs import costs
        for b in state['buildings']:
            if b['status']=='active' and b['building_type'] not in ('pup_tent','upgraded_tent') and 0<b['current_hp']<spec(state,b)['hp']*.75 and all(available(state,r)>=v for r,v in costs(state,b).items()):
                return action('/buildings','Start an affordable paid repair for a damaged building.',action='repair',building_id=b['building_id'])
        owned={b['building_type'] for b in state['buildings'] if b['status'] not in ('ruined','cleared','demolished')}
        goals=[]
        for kind in desired:
            if kind in state['config']['units']:
                unit=state['config']['units'][kind];goals += [unit['storage'],unit['factory']]
        if personality=='defensive':goals+=['guard_post','automated_turret','anti_air_turret']
        for kind in dict.fromkeys(goals):
            if kind in owned:continue
            plan=build_plan(state,kind)
            if plan:return action('/buildings','Build military infrastructure: '+kind+'.',action='build',**plan)
            if market and build_plan(state,kind,ignore_cost=True):
                from game.bot_market import choose_market
                costs=rules(state)['buildings'][kind]['levels'][0]
                supplies=choose_market(state,{},seed,action,market,costs=costs,purpose='building military infrastructure '+kind)
                if supplies:return supplies
    return None
