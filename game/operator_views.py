"""Read-only admin dashboard and settlement inspection; no simulation advances."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
import sqlite3


@contextmanager
def snapshot(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
        yield c


def utc(stamp):
    return datetime.fromtimestamp(stamp,timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC') if stamp is not None else '—'


def dashboard(path,now):
    with snapshot(path) as c:
        season=c.execute('SELECT * FROM seasons ORDER BY season_id DESC LIMIT 1').fetchone()
        counts={name:c.execute('SELECT count(*) FROM '+name).fetchone()[0]
                for name in ('accounts','settlements')}
        events=c.execute('SELECT occurred_at,event_type,settlement_id FROM game_events ORDER BY event_id DESC LIMIT 8').fetchall()
    cards=[('Accounts',counts['accounts'],'/controls?section=accounts'),
           ('Settlements',counts['settlements'],'/players'),
           ('Season',season['status'] if season else 'Waiting for launch','/controls?section=season')]
    html='<h2>Dashboard</h2><div class="operator-metrics">'
    html+=''.join(f'<a class="operator-card" href="{link}"><span>{label}</span><strong>{escape(str(value))}</strong></a>' for label,value,link in cards)+'</div>'
    html+='<div class="operator-grid"><section class="operator-card"><h3>Investigate</h3><p>Choose a player to inspect its committed map, supplies and assignments. Viewing does not advance time.</p><div class="operator-links"><a href="/players">Inspect players</a><a href="/player-logs?errors=1">Request errors</a><a href="/diagnostics">Check save</a></div></section>'
    html+='<section class="operator-card"><h3>Operate</h3><p>Use season controls for launch, pause and resume. Pause or suspend before corrections; the existing audited safeguards remain.</p><div class="operator-links"><a href="/controls?section=season">Season controls</a><a href="/controls?section=corrections">Corrections</a><a href="/controls?section=audit">Audit history</a></div></section></div>'
    if season: html+=f'<p>Season end: {utc(season["ends_at"])} · Finalization: {utc(season["finalization_at"])}</p>'
    html+='<section class="operator-card"><h3>Recent game events</h3><ul>'
    html+=''.join(f'<li>{utc(r["occurred_at"])} · {escape(r["event_type"])} · settlement #{r["settlement_id"]}</li>' for r in events)+'</ul><a href="/logs">Search and export events</a></section>'
    return html


def control_sections(html,section):
    wanted={'season':['Season controls'],'accounts':['Accounts'],'corrections':['Corrections'],
            'moderation':['Announcement','Board moderation — latest 100 posts'],
            'audit':['Audit log — latest 100 actions']}
    if section not in wanted: raise ValueError('Choose a control section from the menu.')
    pieces=re.split(r'(<h2>.*?</h2>)',html)
    result=[]
    for index in range(1,len(pieces)-1,2):
        title=re.sub('<.*?>','',pieces[index])
        if title in wanted[section]:result.extend(pieces[index:index+2])
    return '<div class="operator-controls">'+''.join(result)+'</div>'


def players(path):
    with snapshot(path) as c:
        rows=c.execute('''SELECT s.*,a.username FROM settlements s JOIN accounts a USING(account_id)
            ORDER BY s.season_id DESC,s.settlement_id''').fetchall()
    html='<h2>Players & settlement maps</h2><p>Read-only inspection. Choose a settlement; use Accounts for suspension or password resets.</p><div class="table-scroll"><table><thead><tr><th>Settlement</th><th>Account</th><th>Season</th><th>Status</th><th>Last simulation</th><th>Inspect</th></tr></thead><tbody>'
    html+=''.join(f'<tr><td>#{r["settlement_id"]} {escape(r["settlement_name"])}</td><td>{escape(r["username"])}</td><td>{r["season_id"]}</td><td>{escape(r["status"])}</td><td>{utc(r["simulation_processed_at"])}</td><td><a href="/players/{r["settlement_id"]}">Map & details</a></td></tr>' for r in rows)
    return html+'</tbody></table></div>'+('' if rows else '<p>No settlements yet. Reserve players and launch from Season controls.</p>')


def inspect_player(path,sid):
    from game.settlement import account_scope,read_state
    from game.views import render_page
    from game.ui_counts import citizen_counts
    with snapshot(path) as c:
        row=c.execute('SELECT * FROM settlements WHERE settlement_id=?',(sid,)).fetchone()
        if not row: raise ValueError('Settlement not found.')
        with account_scope(row['account_id']):state=read_state(c)
        if not state or state['settlement']['settlement_id']!=sid:
            raise ValueError('Only the current settlement for this account can be inspected.')
    rendered=render_page(state,'').decode('utf-8')
    match=re.search(r'<svg\b.*?</svg>',rendered,re.S)
    svg=match[0] if match else ''
    # No links to player controls and no player polling or action forms.
    svg=re.sub(r'<a\b[^>]*href="#town-hall"[^>]*>','<g data-inspection-hall>',svg)
    svg=svg.replace('<svg ',f'<svg data-inspection-id="{sid}" ',1)
    svg=re.sub(r'<a\b[^>]*>','<g>',svg).replace('</a>','</g>')
    counts=citizen_counts(state)
    html=f'<h2>{escape(row["settlement_name"])} · #{sid}</h2><p>Read-only committed snapshot at {utc(row["simulation_processed_at"])}. This page does not advance or impersonate the player.</p>'
    html+='<div class="operator-metrics">'+''.join(f'<div class="operator-card"><span>{escape(r.title())}</span><strong>{v:.2f}</strong></div>' for r,v in state['resources'].items() if r in ('food','water','scrap','metal','electronics','credits'))+'</div>'
    html+=f'<p>{counts["total"]} citizens · {counts["free"]} available · {escape(row["status"])}</p><section class="map-panel"><div class="map-scroll" tabindex="0" aria-label="Read-only player map">{svg}</div></section>'
    html+='<div class="operator-grid"><section class="operator-card"><h3>Citizens</h3><ul>'
    html+=''.join(f'<li>#{r["citizen_id"]} {escape(r["name"])} · {r["current_hp"]:g} HP · {escape("Away" if r.get("away") else r["assignment"].replace("_"," "))}</li>' for r in state['citizens'])+'</ul></section>'
    html+='<section class="operator-card"><h3>Buildings</h3><ul>'
    html+=''.join(f'<li>#{b["building_id"]} {escape(b["building_type"].replace("_"," "))} · level {b["level"]} · {escape(b["status"])} · {b["current_hp"]:g} HP</li>' for b in state['buildings'])+'</ul></section></div>'
    html+=f'<div class="operator-links"><a href="/logs?settlement={sid}">Game events</a><a href="/player-logs?account={row["account_id"]}">Player requests</a><a href="/controls?section=corrections">Corrections</a></div>'
    return html+'<script src="/static/map-zoom.js" defer></script>'


def request_table(records):
    html='<div class="table-scroll"><table><thead><tr><th>UTC time</th><th>Player</th><th>Request / action</th><th>Result</th><th>Details</th></tr></thead><tbody>'
    for r in records:
        details=escape(json.dumps(r,indent=2))
        html+=f'<tr><td>{escape(str(r.get("timestamp_utc","—")))}</td><td>{escape(str(r.get("account_id","—")))}</td><td>{escape(str(r.get("method","")))} {escape(str(r.get("route","")))}<br>{escape(str(r.get("action") or r.get("event","")))}</td><td>{escape(str(r.get("status","Started")))}<br>{escape(str(r.get("error_code") or r.get("outcome","")))}</td><td><details><summary>{escape(str(r.get("request_id",""))[:12])}…</summary><pre>{details}</pre></details></td></tr>'
    return html+'</tbody></table></div>'+('' if records else '<p>No matching requests in this file.</p>')
