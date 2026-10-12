"""Small rules-based advisor using server snapshots; no external service."""
from contextlib import closing
from html import escape
import json
from database.create_database import connect_database
from game import social

NAME='Ash'
HISTORY_LIMIT=10

def report(state):
    from game.economy import rates,storage,utilities
    flow=rates(state);capacity=storage(state);status=utilities(state)['buildings'];messages=[]
    for resource in ('food','water'):
        stock=state['resources'][resource];net=flow[resource]['net']
        if stock<=0:messages.append(f'{resource.title()} is empty; assign production workers and check rations.')
        elif net<0:
            hours=flow[resource]['hours_to_empty']
            messages.append(f'{resource.title()} is falling: approximately {hours:.1f} hours of stock at current rates.')
        if stock>=capacity[resource]*.9 and capacity[resource]>0:messages.append(f'{resource.title()} storage is nearly full.')
    materials=sum(state['resources'][r] for r in ('scrap','metal','electronics'))
    if capacity['material']>0 and materials>=capacity['material']*.9:messages.append('Material storage is nearly full; production may pause.')
    home=[c for c in state['citizens'] if not c.get('away')]
    homeless=sum(c.get('homeless_since') is not None for c in home)
    if homeless:messages.append(f'{homeless} citizens need usable Oxygen-covered housing.')
    if home and sum(c['effective_morale'] for c in home)/len(home)<35:messages.append('Home morale is low; desertion is possible at midnight UTC.')
    # Snapshots store catalogue HP separately from the building row.
    from game.buildings import spec
    damaged=sum(b['current_hp']<spec(state,b)['hp'] for b in state['buildings'] if b['status']=='active')
    if damaged:messages.append(f'{damaged} completed buildings need repairs.')
    idle=sum(c['assignment']=='unassigned' for c in home)
    if not any(c['assignment']=='administrator' for c in home):messages.append('The Town Hall has no Administrator; assign an available citizen.')
    if idle:messages.append(f'{idle} citizens are unassigned; prolonged unemployment lowers morale.')
    stalled=sum(j['status']=='paused' for j in state['jobs'])
    if stalled:messages.append(f'{stalled} work projects are paused; check staffing, utilities and inputs.')
    blocked=sum(bool(v['reason']) for bid,v in status.items() if any(b['building_id']==bid and b['status']=='active' and b['building_type']!='town_hall' for b in state['buildings']))
    if blocked:messages.append(f'{blocked} completed buildings are not operating; check their management panels.')
    if state.get('debt_morale_modifier',0)<0:messages.append('Outstanding debt is reducing morale; review the Bank before interest grows.')
    return messages or ['Supplies and settlement operations have no warnings at current rates.']

def request_report(path,now):
    with social.transaction(path,now,gameplay=False) as (c,state):
        if state['season']['status']=='finished' or now>=state['season']['ends_at']:raise ValueError('This season is a read-only archive.')
        from game.simulation import _advance
        from game.settlement import read_state
        _advance(c,state,now);state=read_state(c)
        latest=c.execute("SELECT occurred_at FROM game_events WHERE settlement_id=? AND event_type='advisor_report' ORDER BY event_id DESC LIMIT 1",(state['settlement']['settlement_id'],)).fetchone()
        if latest and now-latest[0]<60:raise ValueError('Please wait one minute before requesting another report.')
        from game.simulation import _event
        _event(c,state,'advisor_report',now,{'advisor':NAME,'messages':report(state)})

def panel(path,state,token,now):
    html='<section class="production-panel" id="advisor"><h2>Ash — settlement advisor</h2><p>Keep the supplies moving. These estimates use current staffing and conditions.</p><ul>'
    html+=''.join('<li>'+escape(message)+'</li>' for message in report(state))+'</ul>'
    if state['season']['status']!='finished' and now<state['season']['ends_at']:
        html+=social.form(token,'advisor','report','<button>Save status report</button></form>')
    with closing(connect_database(path)) as c:
        rows=c.execute("SELECT occurred_at,event_data FROM game_events WHERE settlement_id=? AND event_type='advisor_report' ORDER BY event_id DESC LIMIT ?",(state['settlement']['settlement_id'],HISTORY_LIMIT)).fetchall()
    if rows:
        html+='<details><summary>Recent saved reports</summary>'
        for stamp,data in rows:html+='<p>UTC timestamp '+str(stamp)+': '+escape(' '.join(json.loads(data)['messages']))+'</p>'
        html+='</details>'
    return html+'</section>'
