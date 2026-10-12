"""Best-effort bot audit writes with a file fallback independent of SQLite."""
from datetime import datetime,timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sqlite3

LOG_PATH=Path(__file__).resolve().parents[1]/'logs/bot-runner-errors.jsonl'

def locked(error):
    code=getattr(error,'sqlite_errorcode',None)
    return isinstance(error,sqlite3.OperationalError) and (
        (code is not None and (code & 255) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED)) or
        'database is locked' in str(error).lower() or 'database table is locked' in str(error).lower())

def fallback(path,aid,phase,payload):
    """Only safe trace payloads/metadata; never credentials or raw forms."""
    row=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
             database=Path(path).name,account_id=aid,phase=phase,payload=payload)
    handler=None
    try:
        LOG_PATH.parent.mkdir(parents=True,exist_ok=True)
        handler=RotatingFileHandler(LOG_PATH,maxBytes=5_000_000,backupCount=3,encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        handler.emit(logging.LogRecord('bot-runtime',logging.ERROR,'',0,
                                      json.dumps(row,allow_nan=False),(),None))
    except (OSError,ValueError,TypeError):
        print(f'Bot audit fallback unavailable: bot #{aid}, phase {phase}.',flush=True)
    finally:
        if handler:handler.close()

def trace(path,aid,phase,payload):
    from game import bots
    try:
        bots.trace(path,aid,phase,payload)
        return True
    except sqlite3.Error as error:
        fallback(path,aid,phase,dict(payload,db_log_error=type(error).__name__,database_locked=locked(error)))
        return False

def record(path,aid,now,decision,status=None,request_id=None,error=None):
    from game import bots
    try:
        bots.record(path,aid,now,decision,status,request_id,error)
        return True
    except sqlite3.Error as failure:
        fallback(path,aid,'decision_record_deferred',dict(decision=decision,status=status,
            request_id=request_id,error=error,db_error=type(failure).__name__,database_locked=locked(failure),
            outcome='No action replay. Controller lease expires normally if recording could not release it.'))
        return False

def fallback_panel(path):
    """Bounded fixed-file tail, escaped and filtered to this save."""
    from html import escape
    rows=[]
    try:
        with LOG_PATH.open('rb') as handle:
            handle.seek(0,2);start=max(0,handle.tell()-256_000);handle.seek(start)
            if start:handle.readline()
            for line in handle:
                try:
                    row=json.loads(line)
                    if isinstance(row,dict) and row.get('database')==Path(path).name:rows.append(row)
                except (ValueError,UnicodeDecodeError):continue
    except OSError:pass
    return ('<section class="operator-card"><h2>Bot runner fallback log</h2>'
            '<p>Database locks and traces that could not be saved to SQLite. Latest 100 entries; '
            'original records remain in logs/bot-runner-errors.jsonl and rotations.</p><pre>'+
            escape('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows[-100:]) or 'No fallback entries for this save.')+
            '</pre></section>')
