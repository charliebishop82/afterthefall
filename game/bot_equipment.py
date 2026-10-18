"""Equipment strategy from own state and the normal public market snapshot."""
import json
import random
from game.trading import available

PROFILES={
    'aggressive':dict(offensive_drone=3,missile=3,air_defense_drone=2,ground_defense_drone=2,interceptor=2,repair_drone=1),
    'defensive':dict(offensive_drone=0,missile=0,air_defense_drone=3,ground_defense_drone=3,interceptor=3,repair_drone=1),
    'balanced':dict(offensive_drone=2,missile=2,air_defense_drone=2,ground_defense_drone=2,interceptor=2,repair_drone=1),
    'builder':dict(offensive_drone=0,missile=0,air_defense_drone=1,ground_defense_drone=1,interceptor=1,repair_drone=2),
    'scavenger':dict(offensive_drone=1,missile=0,air_defense_drone=1,ground_defense_drone=1,interceptor=1,repair_drone=1),
}
BUFFERS={'aggressive':100,'defensive':100,'balanced':150,'builder':200,'scavenger':200}


def profile(personality,state=None):
    level=min(3,max(1,state.get('buildings',[{}])[0].get('level',1))) if state and state.get('buildings') else 1
    return {kind:n*level for kind,n in PROFILES.get(personality,PROFILES['balanced']).items()}


def holding(state,kind,*,pending=True):
    count=sum(u['unit_type']==kind and u['status']!='destroyed' for u in state.get('units',[]))
    count+=sum(i['quantity'] for i in state.get('inventory',[]) if i['unit_type']==kind)
    from game.manufacturing import compatible_home
    homes={b['building_id'] for b in state.get('buildings',[]) if compatible_home(state,kind,b)}
    count+=sum(i['quantity'] for i in state.get('munition_reservations',[]) if i['building_id'] in homes)
    if pending:
        for job in state.get('jobs',[]):
            if job['job_type']=='manufacturing' and job['status'] in ('queued','active','paused') and job.get('output_type')==kind:
                count+=max(0,json.loads(job['inputs_spent']).get('remaining',0))
    return count


def desired(personality,seed,state=None):
    goals=profile(personality,state)
    kinds=[k for k,n in goals.items() if n>0]
    random.Random(seed).shuffle(kinds)
    return sorted(kinds,key=lambda k:-goals[k])


def choose_equipment(state,rates,market,personality,seed,action,*,sell_only=False):
    rows=(market or {}).get('equipment',{})
    if not rows or not market.get('can_trade') or state['season']['status']!='active':return None
    if state['settlement']['simulation_processed_at']>=state['season']['finalization_at']:return None
    goals=profile(personality,state);credits=available(state,'credits')
    urgent=any(rates.get(r,{}).get('net',0)<0 and available(state,r)<max(5,rates.get(r,{}).get('consumption',0)*2) for r in ('food','water'))
    kinds=list(rows);random.Random(seed).shuffle(kinds)
    for kind in kinds:
        row=rows[kind];owned=holding(state,kind,pending=False)
        # Emergency fundraising can reduce toward a one-unit safety floor,
        # never sell deployed/repairing/actively ordered hardware to do so.
        floor=min(1,goals.get(kind,0))
        keep=floor if urgent and credits<50 else goals.get(kind,0)
        surplus=min(row.get('sellable',0),max(0,owned-keep))
        if surplus>0:
            return action('/market',f'{personality.title()} equipment sale: {kind}; own {owned}, keep {keep}, saleable {row["sellable"]}; '+('fund urgent supplies.' if urgent else 'free surplus storage and recover Credits.'),
                          action='equipment_sell',unit_type=kind,quantity=1)
    if sell_only or urgent or any(rates.get(r,{}).get('net',0)<0 for r in ('food','water')):return None
    # Retain a Credit cushion plus a six-hour normal supply purchasing buffer.
    food_budget=sum(max(0,rates.get(r,{}).get('consumption',0)*6-available(state,r))*market.get('resources',{}).get(r,{}).get('buy_price',2) for r in ('food','water'))
    budget=max(0,credits-BUFFERS.get(personality,150)-food_budget)
    if any(state['resources'][r]<=0 for r in ('food','water')):return None
    for kind in desired(personality,seed,state):
        if kind not in rows or holding(state,kind)>=goals[kind]:continue
        row=rows[kind]
        if row.get('free_slots',0)<1:continue
        choices=[(row['buy_price'],'equipment_buy','shared stock')] if row['stock']>0 else []
        if row['remaining']>0:choices.append((row['reserve_price'],'equipment_reserve_buy','daily personal reserve'))
        choices=[choice for choice in choices if choice[0]<=budget]
        if choices:
            price,operation,source=min(choices,key=lambda choice:(choice[0],choice[1]!='equipment_buy'))
            return action('/market',f'{personality.title()} equipment purchase: {kind} from {source} at {price} Credits; hold {holding(state,kind)}/{goals[kind]}, free slots {row["free_slots"]}, spending budget {int(budget)}.',
                          action=operation,unit_type=kind,quantity=1)
    return None


def maintenance_decision(state,action):
    if 'maintenance' not in state['config']:return None
    from game import maintenance
    from game.economy import utilities
    status=utilities(state)['buildings']
    shops=[b for b in state['buildings'] if b['building_type'] in ('engineering_workshop','starter_engineering_workshop') and b['status']=='active' and not status[b['building_id']]['reason']]
    for unit in state.get('units',[]):
        if unit['status']!='available' or unit['current_hp']<=0:continue
        if unit['current_hp']<state['config']['units'][unit['unit_type']]['hp']:
            if any(j.get('target_unit_id')==unit['unit_id'] and j['status'] in ('queued','active','paused') for j in state['jobs']):continue
            shop=next((b for b in shops if not any(j['job_type']=='drone_repair' and j['production_building_id']==b['building_id'] and j['status'] in ('active','paused') for j in state['jobs'])),None)
            if shop and all(available(state,r)>=n for r,n in maintenance.repair_cost(state,unit).items()):
                return action('/buildings','Service damaged stored drone using a staffed workshop and normal repair materials.',action='service_drone',unit_id=unit['unit_id'],building_id=shop['building_id'])
        elif unit['unit_type']=='repair_drone' and any(b['building_id']==unit['home_building_id'] for b in shops) and maintenance.orders(state).get(str(unit['unit_id']),{}).get('mode')!='auto':
            return action('/buildings','Enable automatic paid building repairs for a healthy Repair Drone in its functioning workshop.',action='repair_drone_auto',unit_id=unit['unit_id'])
    return None
