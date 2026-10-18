"""Shared settlement presentation for the Flask account application."""
from contextlib import closing
from html import escape
import hashlib
import json
import re

from database.create_database import connect_database
from game import trading, combat, market, diplomacy, communication, expansion_views, banking


def revision(path, state, now):
    value = trading.revision(path,state)+combat.revision(path,state,now)+communication.revision(path,state,now)
    if state.get('expansion'):
        with closing(connect_database(path)) as c:
            import sqlite3
            c.row_factory=sqlite3.Row
            sid=state['settlement']['settlement_id']
            scores=expansion_views.scores(c,state)
            signature=[[(r['settlement_id'],r['rank']) for r in scores],
                       [(r['loan_id'],r['outstanding_balance'],r['status']) for r in banking.loans(c,sid)],
                       [(r['investment_id'],r['principal'],r['accrued_interest']) for r in banking.investments(c,sid)]]
            value+=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:16]
    from game.equipment_market import revision as equipment_revision
    return value+equipment_revision(path,state,now)


def scores(path,state):
    if not state.get('expansion'):return []
    with closing(connect_database(path)) as c:
        import sqlite3
        c.row_factory=sqlite3.Row
        return expansion_views.scores(c,state)


def navigation(actor,token):
    return (f'<div class="building-controls"><span>Logged in as {escape(actor["username"])}</span>'
            f'<form method="post" action="/logout"><input type="hidden" name="token" value="{escape(token,quote=True)}"><button class="secondary">Log out</button></form></div>'
            '<nav><a href="/">Settlement / lobby</a> · <a href="/account">Account settings</a> · <a href="/help">Help / player guide</a>'
            +(' · <a href="/admin">Administration</a>' if actor['is_admin'] else '')+'</nav>')


def settlement(path,state,actor,token,now):
    from game.views import render_page
    html=render_page(state,token).decode()
    from game.offline import notice
    html=html.replace('<main id="main">','<main id="main">'+notice(path,state),1)
    html=html.replace('Assign builders after placing the site, then Start time.','New sites automatically receive one available unassigned citizen when Oxygen coverage is safe. Add more builders if needed.')
    html=re.sub(r'<form method="post" action="/clock">.*?</form>','',html,flags=re.S)
    bar=navigation(actor,token)
    board=scores(path,state)
    if board:
        own=next(r for r in board if r['settlement_id']==state['settlement']['settlement_id'])
        bar+=f'<p>Overall score: <span id="overall-score">{own["overall"]:.2f}</span> · Season rank: {own["rank"]}</p>'
    bar+='<nav aria-label="Player interaction"><a href="#advisor">Advisor</a> · <a href="#bank">Bank</a> · <a href="#rankings">Rankings</a> · <a href="#market">Market</a> · <a href="#diplomacy">Diplomacy</a> · <a href="#messages">Messages</a> · <a href="#board">Board</a></nav>'
    html=html.replace('Pause time to freeze your settlement.','Season time is shared by all players.')
    html=html.replace('Your settlement starts paused. Place a Garden, assign builders, then start time. Completed Food buildings need Food workers to produce.','Season time runs automatically. Place a Garden and assign builders. Completed production buildings need workers to produce.')
    if state['settlement']['status']=='suspended':
        html=html.replace('data-status="active"','data-status="suspended"').replace('data-status="finalizing"','data-status="suspended"').replace('Time is running.','Your settlement is frozen.')
        with closing(connect_database(path)) as c:
            from game.trading import supply_frozen
            supply=supply_frozen(c,state)
        explanation='Replenish Food and Water through trading to resume.' if supply else 'The administrator must reactivate your account.'
        bar+='<p class="error">Your settlement is frozen. '+explanation+'</p>'
    if state['season']['status']=='paused':
        bar+='<p class="error">The season is paused. Game progress and gameplay actions are frozen until the administrator resumes it. Messages remain available.</p>'
        html=re.sub(r'(<form\b[^>]*action="/(?:buildings|scavenging|needs|manufacturing|administrator)"[^>]*>)(.*?)(</form>)', r'\1<fieldset disabled>\2</fieldset>\3', html, flags=re.S)
    extra=revision(path,state,now)
    html=re.sub(r'data-revision="([^"]*)"',lambda m:f'data-revision="{m[1]}{extra}"',html)
    from game.advisor import panel as advisor_panel
    from game.resource_alerts import alerts as resource_alerts, panel as attention_panel
    from game.simulation import resource_rates
    panels=attention_panel(resource_alerts(state,resource_rates(state)))+advisor_panel(path,state,token,now)+trading.panel(path,state,token)
    for module in (combat,market,diplomacy,communication,expansion_views):
        panels+=module.panel(path,state,token,now)
    from game.expeditions import panel as expedition_panel
    from game.expeditions import summary as expedition_summary
    panels+=expedition_panel(state,token)+expedition_summary(state)
    from game.military_portal import payload as military_portal_payload
    import json
    overview=military_portal_payload(state);overview['raid_timers']=combat.timers(path,state,now)
    panels+='<div id="military-portal-data" hidden data-dashboard="'+escape(json.dumps(overview),quote=True)+'"></div>'
    from game.operation_results import snapshot as operation_snapshot
    panels+='<div id="operation-results-data" hidden data-results="'+escape(json.dumps(operation_snapshot(path,state)),quote=True)+'"></div>'
    return html.replace('<main id="main">','<main id="main">'+bar).replace('</main>',panels+'</main>')


def live_values(state):
    """Small read-only values for existing DOM elements; no forms or HTML."""
    from game.building_views import map_staff
    from game.progression import enabled
    from game.ui_counts import citizen_counts
    return {
        'citizen_counts':citizen_counts(state),
        'credits': state['resources']['credits'],
        'citizens': [{'id':c['citizen_id'], 'level':c['level'], 'xp':c['xp'],
                     'show_xp':enabled(state), 'hp':c['current_hp'],
                     'morale':c.get('effective_morale',c['morale']),
                     'housing_modifier':c.get('housing_morale_modifier',0),
                     'assignment':'Exploring the Wastes' if c.get('exploring') else 'Raiding' if c.get('away') else c['assignment'].replace('_',' ').title()}
                    for c in state['citizens']],
        'map_staff': {**{'town-hall' if b['building_type']=='town_hall' else
                        ('ruin-' if b['status']=='ruined' else 'building-')+str(b['building_id']):
                        map_staff(state,building=b['building_id']) for b in state['buildings']
                        if b['status'] not in ('cleared','demolished')},
                      **{'derelict-'+str(d['settlement_derelict_id']):
                         map_staff(state,derelict=d['settlement_derelict_id']) for d in state['derelicts']
                         if d['status']!='cleared'}},
        'completed_jobs':[str(j['job_id']) for j in state['jobs'] if j['status']=='completed'],
        'build_locked':state['season']['status'] in ('finished','finalizing') or
                       state['settlement']['status']!='active' or
                       state['settlement']['simulation_processed_at']>=state['season']['finalization_at'],
        'hall_level':state['buildings'][0]['level']
    }


def resources(path,state,now):
    from game.simulation import resource_rates
    from game.building_views import live_payload, map_occupancy, scavenging_summary, staffing_payload, map_requires_staff, map_filter_flags
    payload={'account_id':state['settlement']['account_id'],'settlement_id':state['settlement']['settlement_id'],'season_id':state['season']['season_id'],'map_seed':state['season']['map_seed'],'status':state['season']['status'],'food':state['resources']['food'],
             'water':state['resources']['water'],'rates':resource_rates(state)}
    from game.resource_alerts import alerts as resource_alerts
    payload['resource_alerts']=resource_alerts(state,payload['rates'])
    from game.storage_display import storage_status
    payload['storage_status']=storage_status(state,payload['rates'])
    payload.update(live_payload(state))
    payload.update(live_values(state))
    payload['map_occupied']=map_occupancy(state)
    payload['building_staffing']=staffing_payload(state)
    payload['map_filters']=map_filter_flags(state)
    from game.defense_display import local_defense, description
    payload['defense']=local_defense(state)
    payload['defense']['description']=description(payload['defense'])
    from game.buildings import spec
    payload['map_staff_required']={'town-hall' if b['building_type']=='town_hall' else ('ruin-' if b['status']=='ruined' else 'building-')+str(b['building_id']):
                                  map_requires_staff(state,b,spec(state,b)['workers']) for b in state['buildings']
                                  if b['status'] not in ('cleared','demolished')}
    payload['scavenging']=scavenging_summary(state,include_completed=True)
    payload['materials']={r:state['resources'][r] for r in ('scrap','metal','electronics')}
    if state['settlement']['status']=='suspended':payload['status']='suspended'
    payload['revision']+=revision(path,state,now)
    payload['trade_available']={r:trading.available(state,r) for r in trading.RESOURCES}
    payload['trade_reserved']=state['reserved']
    from game.bot_military import public_targets
    payload['targets']=public_targets(path,state,now)
    payload['market']=market.public_snapshot(path,state,now)
    from game.expeditions import live as expedition_live
    payload['expeditions']=expedition_live(state)
    from game.citizen_portal import payload as citizen_portal_payload
    payload['citizen_portal']=citizen_portal_payload(state)
    from game.military_portal import payload as military_portal_payload
    payload['military_portal']=military_portal_payload(state)
    payload['military_portal']['raid_timers']=payload['raid_timers'] if 'raid_timers' in payload else {}
    payload['raid_timers']=combat.timers(path,state,now)
    payload['military_portal']['raid_timers']=payload['raid_timers']
    payload['war_timers']=combat.war_timers(path,state,now)
    from game.operation_results import snapshot as operation_snapshot
    payload['operation_results']=operation_snapshot(path,state)
    if state.get('expansion'):
        payload['scores']=scores(path,state)
        payload['own_score']=next(r['overall'] for r in payload['scores'] if r['settlement_id']==state['settlement']['settlement_id'])
    return payload
