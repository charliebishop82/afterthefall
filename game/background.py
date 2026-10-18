"""One fair background coordinator, sharing the player server's write gate.

This is concurrent with HTTP service, not parallel SQLite writers. Each pass
commits one existing catch-up batch and yields before choosing another player.
"""
from contextlib import closing
from datetime import datetime, timezone
from html import escape
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sqlite3
from threading import Event, Thread
import time
import traceback

from database.create_database import connect_database
from game import catchup, offline
from game.background_progress import Progress, message

ROOT=Path(__file__).resolve().parents[1]
LOG_PATH=ROOT/'logs/background-simulation.jsonl'


def pending(path,now):
    """Snapshot eligible latest settlements; pause/freeze controls still win."""
    with closing(connect_database(path)) as c:
        c.row_factory=sqlite3.Row
        rows=c.execute('''SELECT s.*,se.status AS season_status,se.ends_at,se.config_version
            FROM settlements s JOIN seasons se USING(season_id) JOIN accounts a USING(account_id)
            WHERE s.status='active' AND a.is_active=1 AND se.status IN ('active','finalizing')
            AND s.season_id=(SELECT max(s2.season_id) FROM settlements s2 WHERE s2.account_id=s.account_id)
            ORDER BY s.account_id''').fetchall()
        from game.admin_controls import frozen
        result=[]
        for row in rows:
            if frozen(c,{'season':{'status':row['season_status']},'settlement':row}):continue
            goal=min(now,row['ends_at'])
            interval=15
            offline_until=None
            if row['config_version']=='prototype_v13' and offline.settings()['enabled'] and offline.exists(c):
                active=c.execute('SELECT last_active_at FROM settlement_activity WHERE settlement_id=?',
                                 (row['settlement_id'],)).fetchone()
                offline_until=(active[0] if active else row['simulation_processed_at'])+offline.settings()['max_hours']*3600
                if row['simulation_processed_at']>=offline_until:
                    interval=300  # Frozen local activity only needs occasional shared-clock upkeep.
            if now>=row['ends_at'] or goal-row['simulation_processed_at']>=interval:
                behind=max(0,goal-row['simulation_processed_at'])
                simulation=max(0,min(goal,offline_until if offline_until is not None else goal)-row['simulation_processed_at'])
                result.append(dict(account_id=row['account_id'],settlement_id=row['settlement_id'],
                                   behind=behind,simulation_seconds=simulation,skip_seconds=behind-simulation))
        return result


class Coordinator:
    def __init__(self,path,gate,*,clock=time.time,log_path=LOG_PATH):
        self.path=Path(path);self.gate=gate;self.clock=clock;self.log_path=Path(log_path)
        self.stopping=Event();self.thread=None;self.last_account=0;self.last_report=0
        self.progress=Progress()
        self.latest_limits={}
        self.latest_blockers={}

    def record(self,event,**data):
        handler=None
        try:
            self.log_path.parent.mkdir(parents=True,exist_ok=True)
            handler=RotatingFileHandler(self.log_path,maxBytes=5_000_000,backupCount=3,encoding='utf-8')
            row=dict(event=event,timestamp_utc=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                     database=self.path.name,**data)
            handler.emit(logging.LogRecord('background-simulation',logging.INFO,'',0,
                                           json.dumps(row,allow_nan=False),(),None))
        except (OSError,ValueError,TypeError):
            print('Background simulation log unavailable.',flush=True)
        finally:
            if handler:
                try:handler.close()
                except OSError:pass

    def run_once(self):
        # Never queue background work ahead of an in-progress player request.
        if not self.gate.acquire(blocking=False):return None
        try:
            now=int(self.clock())  # Sample time after acquiring the same gate as HTTP.
            rows=pending(self.path,now)
            if not rows:return None
            player=next((r for r in rows if r['account_id']>self.last_account),rows[0])
            self.last_account=player['account_id']
            result=catchup.step(self.path,player['account_id'],now)
            sid=result.get('processed_settlement_id')
            if sid is not None:self.latest_limits[sid]=result.get('step_limits',{})
            if sid is not None:self.latest_blockers[sid]=result.get('bulk_blockers',[])
            self.record('background_batch',requested_account_id=player['account_id'],
                        pending_settlements=len(rows),**result)
            if time.monotonic()-self.last_report>=15:
                self.last_report=time.monotonic()
                stats=self.progress.sample(rows,self.last_report)
                print(message(len(rows),stats),flush=True)
                details=[]
                for row in rows:
                    limits=self.latest_limits.get(row['settlement_id'],{})
                    reason=', '.join(f'{name} ({count})' for name,count in sorted(limits.items(),key=lambda pair:-pair[1])) or 'awaiting first batch sample'
                    blockers=self.latest_blockers.get(row['settlement_id'],[])
                    guard=', '.join(blockers) or 'none identified; rate/storage boundaries may still apply'
                    print(f"  Settlement #{row['settlement_id']}: {row['simulation_seconds']/3600:.1f}h to simulate; {row['skip_seconds']/3600:.1f}h to skip; last batch limits: {reason}; bulk guards: {guard}.",flush=True)
                    details.append(dict(row,step_limits=limits,bulk_blockers=blockers))
                self.record('background_progress',pending_settlements=len(rows),settlements=details,**stats)
            return result
        finally:
            self.gate.release()

    def _run(self):
        self.record('background_started')
        try:
            while not self.stopping.is_set():
                try:
                    result=self.run_once()
                    delay=0.15 if result is not None else 2
                except Exception as error:
                    # The failed transaction has rolled back. Retry fresh state;
                    # a single broken settlement does not kill other updates.
                    self.record('background_error',account_id=self.last_account,
                                error_type=type(error).__name__,
                                frames=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name)
                                        for f in traceback.extract_tb(error.__traceback__)[-10:]])
                    if time.monotonic()-self.last_report>=15:
                        self.last_report=time.monotonic()
                        print(f'Background simulation deferred: {type(error).__name__}; see {self.log_path}',flush=True)
                    delay=3
                self.stopping.wait(delay)
        finally:
            self.record('background_stopped')

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stopping.clear()
        self.thread=Thread(target=self._run,name='settlement-coordinator',daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread:self.thread.join(timeout=5)
        if self.thread and self.thread.is_alive():
            print('Background simulation is finishing its current atomic batch; uncommitted work is recoverable on restart.',flush=True)


def panel(database,log_path=LOG_PATH):
    """Small read-only admin tail; no simulation or credentials in this view."""
    rows=[]
    try:
        with Path(log_path).open('rb') as stream:
            stream.seek(0,2);offset=max(0,stream.tell()-65536);stream.seek(offset)
            if offset:stream.readline()
            for line in stream.read(65536).decode('utf-8',errors='replace').splitlines():
                try:row=json.loads(line)
                except ValueError:continue
                if isinstance(row,dict) and row.get('database')==Path(database).name:rows.append(row)
    except OSError:pass
    html='<h2>Background settlement simulation</h2><p>Starts with the player server and shares its write gate. Latest batch records; refresh to inspect progress. Idle periods need no batch records.</p>'
    if not rows:return html+'<p>No background records found for this save.</p>'
    for row in reversed(rows[-20:]):
        html+='<details><summary>'+escape(str(row.get('timestamp_utc',''))+' · '+str(row.get('event','')))+' </summary><pre>'+escape(json.dumps(row,indent=2))+'</pre></details>'
    return html
