"""Read-only save checks and bounded event history for local operators."""
from contextlib import closing
from pathlib import Path
import sqlite3
import json


def inspect(path):
    findings = []
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as c:
        c.execute('PRAGMA query_only=ON')
        c.execute('BEGIN')  # All checks see the same committed snapshot.
        integrity = c.execute('PRAGMA integrity_check').fetchall()
        if integrity != [('ok',)]: findings.append(('error', 'SQLite integrity', str(integrity)))
        for row in c.execute('PRAGMA foreign_key_check'):
            findings.append(('error', 'Foreign key', str(row)))
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'accounts','auth_sessions','settlements','settlement_resources','admin_actions','resource_reservations','market_listings','trade_proposals'}
        if not required <= tables:
            findings.append(('error','Schema','Missing tables: '+', '.join(sorted(required-tables))))
        else:
            for sid, in c.execute('SELECT settlement_id FROM settlements WHERE settlement_id NOT IN (SELECT settlement_id FROM settlement_resources)'):
                findings.append(('error','Missing resources',f'Settlement #{sid} has no resource row.'))
            for sid, resource, total in c.execute('SELECT settlement_id,resource_type,SUM(quantity) FROM resource_reservations WHERE released_at IS NULL GROUP BY settlement_id,resource_type'):
                if resource not in ('food','water','scrap','metal','electronics','credits'): continue
                stock = c.execute(f'SELECT {resource} FROM settlement_resources WHERE settlement_id=?',(sid,)).fetchone()
                if not stock or total > stock[0]+1e-7:
                    findings.append(('error','Reserved stock',f'Settlement #{sid}: reserved {total:g} {resource} exceeds stock.'))
            for rid, in c.execute("""SELECT r.reservation_id FROM resource_reservations r
                LEFT JOIN market_listings m ON m.listing_id=r.market_listing_id
                LEFT JOIN trade_proposals t ON t.trade_id=r.trade_proposal_id
                WHERE r.released_at IS NULL AND ((r.market_listing_id IS NOT NULL AND m.status!='open')
                OR (r.trade_proposal_id IS NOT NULL AND t.status!='pending'))"""):
                findings.append(('error','Stale reservation',f'Reservation #{rid} remains on a closed offer.'))
            if 'admin_freezes' in tables:
                for sid, in c.execute("SELECT f.settlement_id FROM admin_freezes f JOIN settlements s USING(settlement_id) WHERE s.status NOT IN ('suspended','archived')"):
                    findings.append(('error','Freeze mismatch',f'Settlement #{sid} is frozen but not suspended.'))
        if 'market_pool_stock' in tables:
            for season,resource,quantity in c.execute('SELECT season_id,resource,quantity FROM market_pool_stock'):
                if type(quantity) is not int or quantity<0 or resource not in ('food','water','scrap','metal','electronics'):
                    findings.append(('error','Shared market',f'Season #{season}: invalid stock for {resource}.'))
            for lid, in c.execute("SELECT listing_id FROM market_listings WHERE status='open'"):
                findings.append(('error','Legacy listing',f'Listing #{lid} is still open after pooled-market migration.'))
        if 'equipment_market_stock' in tables:
            from game.equipment_market import KINDS
            for season,kind,quantity in c.execute('SELECT season_id,kind,quantity FROM equipment_market_stock'):
                if kind not in KINDS or type(quantity) is not int or quantity<0:
                    findings.append(('error','Equipment market',f'Season #{season}: invalid stock for {kind}.'))
        if 'equipment_market_trades' in tables:
            for trade,quantity,price,credits in c.execute('SELECT trade_id,quantity,unit_price,credit_amount FROM equipment_market_trades'):
                if quantity<=0 or price<=0 or credits<0:
                    findings.append(('error','Equipment transaction',f'Trade #{trade}: invalid quantity or Credits.'))
        semantics(c,tables,findings)
        counts = {t:c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('accounts','settlements','game_events','admin_actions') if t in tables}
        return {'findings':findings,'counts':counts,'ok':not any(f[0]=='error' for f in findings)}


def events(path, *, settlement=None, kind=None, before=None, limit=100):
    """Bounded, keyset-paged investigation; filters are bound SQL parameters."""
    if type(limit) is not int or not 1<=limit<=500:
        raise ValueError('Choose 1-500 events.')
    filters=[];values=[]
    for column,value in (('settlement_id',settlement),('event_id',before)):
        if value is not None:
            if type(value) is not int or not 1<=value<=9223372036854775807:
                raise ValueError('Use positive SQLite integer event/settlement IDs.')
            filters.append(column+(' <?' if column=='event_id' else '=?'));values.append(value)
    if kind is not None:
        if not isinstance(kind,str) or not 1<=len(kind)<=80:raise ValueError('Use an event type of 1-80 characters.')
        filters.append('event_type=?');values.append(kind)
    query='SELECT event_id,occurred_at,settlement_id,event_type,event_data FROM game_events'
    if filters:query+=' WHERE '+' AND '.join(filters)
    query+=' ORDER BY event_id DESC LIMIT ?';values.append(limit)
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as c:
        return c.execute(query,values).fetchall()


def semantics(c,tables,findings):
    """Check saved invariants without running simulation or changing old names."""
    if not {'citizens','seasons','buildings','citizen_assignments'}<=tables:return
    from game.settlement import load_config
    from game.expansion import overlay
    configs={}
    for season,version in c.execute('SELECT season_id,config_version FROM seasons'):
        try:configs[season]=overlay(c,season,load_config(version))[0]
        except (ValueError,KeyError,IndexError) as error:
            findings.append(('error','Configuration',f'Season #{season}: {error}'))
    for cid,sid,level,hp,status,season in c.execute('SELECT citizen_id,settlement_id,level,current_hp,c.status,s.season_id FROM citizens c JOIN settlements s USING(settlement_id)'):
        config=configs.get(season)
        if config:
            maximum=config['citizen_hp']+(level-1)*config.get('simulation',{}).get('hp_per_level',0)
            if hp>maximum+1e-7 or (status=='alive' and hp<=0) or (status=='dead' and hp!=0):
                findings.append(('error','Citizen health',f'Citizen #{cid}: {status}, HP {hp:g}, maximum {maximum:g}.'))
    for bid,kind,level,hp,status,season in c.execute('SELECT building_id,building_type,level,current_hp,b.status,s.season_id FROM buildings b JOIN settlements s USING(settlement_id)'):
        config=configs.get(season)
        if not config:continue
        definition=config.get('buildings',{}).get(kind)
        if not config.get('buildings') and kind=='town_hall' and level==1:
            definition={'levels':[config['town_hall']]}
        if not definition or not 1<=level<=len(definition['levels']):
            findings.append(('error','Building catalogue',f'Building #{bid}: unknown type or level {kind} {level}.'));continue
        maximum=definition['levels'][level-1]['hp']
        if hp>maximum+1e-7 or (status in ('ruined','demolished') and hp!=0):
            findings.append(('error','Building health',f'Building #{bid}: {status}, HP {hp:g}, maximum {maximum:g}.'))
    for aid,cid in c.execute("SELECT assignment_id,citizen_id FROM citizen_assignments a JOIN citizens c USING(citizen_id) WHERE ended_at IS NULL AND (a.settlement_id!=c.settlement_id OR c.status!='alive')"):
        findings.append(('error','Citizen assignment',f'Assignment #{aid} belongs to a departed/dead citizen or another settlement (citizen #{cid}).'))
    for sid,name,count in c.execute("SELECT settlement_id,name,count(*) FROM citizens WHERE status='alive' GROUP BY settlement_id,name HAVING count(*)>1"):
        findings.append(('warning','Legacy citizen names',f'Settlement #{sid}: {count} citizens named {name!r}; use citizen IDs, preserve their names.'))
    if 'military_units' in tables:
        for uid,kind,hp,status,season in c.execute('SELECT unit_id,unit_type,current_hp,u.status,s.season_id FROM military_units u JOIN settlements s USING(settlement_id)'):
            config=configs.get(season);unit=config.get('units',{}).get(kind) if config else None
            if not unit:continue
            if hp>unit['hp']+1e-7 or (status=='destroyed' and hp!=0) or (status!='destroyed' and hp<=0):
                findings.append(('error','Drone health',f'Drone #{uid}: {status}, HP {hp:g}, maximum {unit["hp"]:g}.'))
