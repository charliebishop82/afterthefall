"""Staffed support effects and citizen defense assignments on the existing schema."""
from html import escape
import math
from game.buildings import spec, productivity, footprint
from game.settlement import read_state


def enabled(state):
    return state['season']['config_version'] in ('prototype_v10','prototype_v11','prototype_v12','prototype_v13')


def enable(connection,state,now):
    if enabled(state):return
    from game.manufacturing import enable as enable_military
    enable_military(connection,state,now)
    connection.execute("UPDATE seasons SET config_version='prototype_v10' WHERE season_id=?",(state['season']['season_id'],))
    from game.simulation import _event
    _event(connection,state,'prototype_config_enabled',now,{'from':state['season']['config_version'],'to':'prototype_v10'})


def factor(state,b,utility):
    status=utility['buildings'].get(b['building_id'])
    if not status or status['reason']:return 0
    return min(1,status['factor']/max(1,spec(state,b)['workers']))


def best(state,key,utility=None):
    if not enabled(state):return 0
    from game.economy import utilities
    utility=utility or utilities(state)
    return max((spec(state,b).get(key,0)*factor(state,b,utility) for b in state['buildings'][1:]),default=0)


def community(state,utility=None):
    if not enabled(state):return 0
    from game.economy import utilities,zone_fraction
    utility=utility or utilities(state);values=[]
    for b in state['buildings'][1:]:
        if b['building_type']!='community_center':continue
        value=spec(state,b)['morale']*factor(state,b,utility)
        if zone_fraction(state,b,utility['zones']['electricity'])>=state['config']['construction']['coverage_fraction']:
            value*=state['config']['support']['community_power_multiplier']
        values.append(value)
    return max(values,default=0)


def treatment(state):
    """Allocate each patient once, best active care first, most injured first."""
    if not enabled(state):return {}
    from game.economy import utilities
    from game.recovery import eligibility,max_hp
    utility=utilities(state);reasons=eligibility(state)
    patients=sorted((c for c in state['citizens'] if not reasons[c['citizen_id']]),key=lambda c:(c['current_hp']/max_hp(state,c),c['citizen_id']))
    facilities=[]
    for b in state['buildings'][1:]:
        s=spec(state,b);f=factor(state,b,utility)
        if s.get('treatment_capacity',0) and f:
            slots=math.floor(s['treatment_capacity']*f+1e-9)
            if slots>0:facilities.append((s['healing_bonus']*f,b['building_id'],slots))
    # Duplicate clinics do not stack their capacity or bonuses; use the best one.
    if not facilities:return {}
    bonus,bid,slots=max(facilities,key=lambda v:(v[0],v[2],-v[1]))
    return {c['citizen_id']:{'bonus':bonus,'building_id':bid} for c in patients[:slots]}


def healing_rates(state):
    care=treatment(state);base=state['config']['recovery']['natural_hp_per_hour']
    return {c['citizen_id']:base*(1+care.get(c['citizen_id'],{}).get('bonus',0)/100) for c in state['citizens']}


def covers_hall(state,post):
    hall=state['buildings'][0];w,h=footprint(state,hall);pw,ph=footprint(state,post)
    x=hall['origin_x']+w/2;y=hall['origin_y']+h/2
    dx=max(post['origin_x']-x,0,x-post['origin_x']-pw)
    dy=max(post['origin_y']-y,0,y-post['origin_y']-ph)
    return dx*dx+dy*dy<=spec(state,post)['defense_radius']**2


def guards(state):
    if not enabled(state):return []
    from game.economy import utilities
    utility=utilities(state)
    active={b['building_id'] for b in state['buildings'][1:] if b['building_type']=='guard_post' and not utility['buildings'][b['building_id']]['reason'] and covers_hall(state,b)}
    return [c for c in state['citizens'] if c['assignment']=='defender' and c['building_id'] in active and not c.get('away')]


def defense_bonus(state):
    if not enabled(state):return 0
    from game.economy import utilities,condition
    from game.combat import rule
    utility=utilities(state);crew=guards(state);total=0
    for b in state['buildings'][1:]:
        count=sum(c['building_id']==b['building_id'] for c in crew)
        if count:
            total+=spec(state,b)['defense_strength']*factor(state,b,utility)+count*rule('guard_post_strength_per_guard')*condition(state,b)
    return total


def command(connection,state,action,bid,cid,now,exposed=False):
    if action=='enable_support':enable(connection,state,now);return
    if not enabled(state):raise ValueError('Enable support and defense first.')
    c=next((c for c in state['citizens'] if c['citizen_id']==cid),None)
    if not c or c['current_hp']<=0 or c.get('away'):raise ValueError('Choose a living citizen at home from your settlement.')
    if action=='release_defense':
        if c['assignment'] not in ('defender','patrol'):raise ValueError('This citizen is not assigned to defense.')
        connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='released' WHERE assignment_id=?",(now,c['assignment_id']))
        connection.execute('UPDATE citizens SET unemployed_since=? WHERE citizen_id=?',(now,cid))
        return
    kind='defender' if action=='guard' else 'patrol'
    if kind=='defender':
        b=next((b for b in state['buildings'] if b['building_id']==bid),None)
        if not b or b['building_type']!='guard_post' or b['status']!='active':raise ValueError('Choose a completed Guard Post in your settlement.')
        if c['assignment']==kind and c['building_id']==bid:return
        if sum(c['assignment']=='defender' and c['building_id']==bid for c in state['citizens'])>=spec(state,b)['workers']:raise ValueError('All guard slots are filled.')
    else:
        bid=None
        if c['assignment']=='patrol':return
    if c['assignment']!='unassigned':raise ValueError('Release this citizen from their current assignment first.')
    from game.buildings import coverage
    if bid and 'consequences' in state['config'] and coverage(state,b)<state['config']['construction']['coverage_fraction'] and not exposed:raise ValueError('Confirm dangerous Oxygen exposure before assigning this guard.')
    aid=connection.execute('INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,?,?,?,?)',(cid,state['settlement']['settlement_id'],kind,bid,now)).lastrowid
    if exposed and bid and 'consequences' in state['config'] and coverage(state,b)<state['config']['construction']['coverage_fraction']:
        from game.consequences import authorize
        authorize(connection,state,aid,now)
    connection.execute('UPDATE citizens SET unemployed_since=NULL WHERE citizen_id=?',(cid,))


def panel(state,token):
    from game.building_views import form
    if not enabled(state):return '<section class="production-panel" id="support"><h2>Support and defense</h2>'+form(token,'enable_support','<p>Add medical care, engineering, salvage, community morale, Trading Posts, Guard Posts and patrol assignments.</p><button>Enable support and defense</button>')+'</section>'
    from game.economy import utilities
    utility=utilities(state)
    html='<section class="production-panel" id="support"><h2>Support and defense</h2><p>Bonuses scale with condition and effective staffing. Only the strongest active support building applies; duplicates do not stack.</p>'
    html+=f'<p>Construction/crew repair: +{best(state,"construction_bonus",utility):.2f}%. Scavenging speed: +{best(state,"scavenge_bonus",utility):.2f}%. Material salvage yield: +{best(state,"salvage_bonus",utility):.2f}%. Current community morale: +{community(state,utility):.2f}.</p>'
    html+='<p>Medical care automatically serves the most injured eligible citizens, within the best facility’s treatment capacity. Trading Post reduces public market fees in account mode; private trades remain fee-free. Enable maintenance and building management for Repair Drone actions.</p>'
    html+=f'<p>Ready local guards: {len(guards(state))}. Patrols respond settlement-wide. Guard Posts contribute only while staffed, operational and covering the Town Hall; their defense radii are shown on the map.</p>'
    free=[c for c in state['citizens'] if c['assignment']=='unassigned' and not c.get('away') and c['current_hp']>0]
    if free:
        choices=''.join(f'<option value="{c["citizen_id"]}">{escape(c["name"])}</option>' for c in free)
        html+=form(token,'patrol','<label>Patrol citizen <select name="citizen_id">'+choices+'</select></label><button>Assign patrol</button>')
    for c in state['citizens']:
        if c['assignment'] in ('defender','patrol'):
            html+=form(token,'release_defense',f'<span>{escape(c["name"])} · {"Guard" if c["assignment"]=="defender" else "Patrol"}</span><button>Release defense assignment</button>',citizen_id=c['citizen_id'])
    return html+'</section>'
