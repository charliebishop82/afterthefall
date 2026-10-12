"""Bounded read-only route timing summaries from existing safe request logs."""
from pathlib import Path
from html import escape
import json
import math

def number(row,key):
    value=row.get(key)
    return float(value) if type(value) in (int,float) and math.isfinite(value) and 0<=value<=86400000 else None

def read(log_path,database):
    if log_path is None:return [],'Player request logging is not configured.'
    source=Path(log_path);rows=[]
    for rotation in range(6):
        path=source if rotation==0 else source.with_name(source.name+'.'+str(rotation))
        try:
            with path.open('rb') as stream:
                stream.seek(0,2);offset=max(0,stream.tell()-524288);stream.seek(offset)
                if offset:stream.readline()
                lines=stream.read(524288).decode('utf-8',errors='replace').splitlines()
        except OSError:continue
        for line in reversed(lines):
            try:row=json.loads(line)
            except (ValueError,RecursionError):continue
            if not isinstance(row,dict) or row.get('event')!='request_finished' or row.get('database')!=Path(database).name:continue
            if number(row,'duration_ms') is None:continue
            rows.append(row)
            if len(rows)>=2000:return rows,''
    return rows,'' if rows else 'No completed timed requests found for this save yet.'

def summarize(rows):
    groups={}
    for row in rows:
        key=(str(row.get('method','?')),str(row.get('route','?')),str(row.get('action') or ''))
        groups.setdefault(key,[]).append(row)
    result=[]
    for key,items in groups.items():
        durations=sorted(number(r,'duration_ms') for r in items if number(r,'duration_ms') is not None)
        if not durations:continue
        waits=[number(r,'gameplay_lock_wait_ms') for r in items if number(r,'gameplay_lock_wait_ms') is not None]
        result.append(dict(method=key[0],route=key[1],action=key[2],count=len(durations),
            average=sum(durations)/len(durations),p95=durations[math.ceil(.95*len(durations))-1],maximum=durations[-1],
            lock_average=sum(waits)/len(waits) if waits else None,lock_samples=len(waits),
            slow=sum(d>=1000 for d in durations)))
    return sorted(result,key=lambda r:r['p95'],reverse=True)

def panel(log_path,database):
    rows,notice=read(log_path,database);groups=summarize(rows)
    html='<h1>Request performance</h1><p>Recent bounded sample from player request logs. Slow: at least 1 second; lock contention: at least 250 ms. Refresh this page after observing play.</p>'
    html+='<p>Application time includes database waits. Waitress queue time, final log write and network delivery are not measured. Lock wait is the shared gameplay lock, not SQLite locks.</p>'
    if notice:html+='<p>'+escape(notice)+'</p>'
    html+=f'<p>{len(rows)} timed completed requests · {len(groups)} route/action groups.</p><div class="table-scroll"><table><thead><tr><th>Route / action</th><th>Requests</th><th>Average ms</th><th>p95 ms</th><th>Max ms</th><th>Lock wait ms</th><th>Slow</th></tr></thead><tbody>'
    for row in groups:
        lock='Unknown' if row['lock_average'] is None else f'{row["lock_average"]:.1f} ({row["lock_samples"]} measured)'
        label=' '.join((row['method'],row['route'],row['action']))
        html+=f'<tr><th>{escape(label)}</th><td>{row["count"]}</td><td>{row["average"]:.1f}</td><td>{row["p95"]:.1f}</td><td>{row["maximum"]:.1f}</td><td>{lock}</td><td>{row["slow"]}</td></tr>'
    html+='</tbody></table></div><h2>Latest slow requests</h2>'
    slow=sorted((r for r in rows if number(r,'duration_ms')>=1000),key=lambda r:str(r.get('timestamp_utc','')),reverse=True)[:20]
    for row in slow:
        rid=str(row.get('request_id',''));link=''
        if len(rid)==32 and all(c in '0123456789abcdef' for c in rid):link=f' <a href="/player-logs?request_id={rid}">Request trace</a>'
        html+='<p>'+escape(f'{row.get("timestamp_utc","")} · account {row.get("account_id")} · {row.get("route")} · {number(row,"duration_ms"):.1f} ms · status {row.get("status")}')+link+'</p>'
    if not slow:html+='<p>No slow requests in this sample.</p>'
    return html
