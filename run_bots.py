"""Run enabled economy bots through the local player server; Ctrl+C stops runner."""
import argparse
import sqlite3
from contextlib import closing
import json
import hashlib
import uuid
from pathlib import Path
import time
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,HTTPRedirectHandler,build_opener
from html.parser import HTMLParser

from database.create_database import connect_database
from game import accounts,bots,bot_runtime
from game.bot_policy import choose,POLICY_VERSION
from game.operator_views import snapshot
from game.settlement import account_scope,read_state


def game_origin(value):
    parts=urlsplit(value)
    if parts.scheme!='http' or parts.hostname not in ('127.0.0.1','localhost') or parts.username or parts.password or parts.path not in ('','/') or parts.query or parts.fragment:
        raise ValueError('Use a local player origin such as http://127.0.0.1:8767.')
    return value.rstrip('/')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None


def request(origin,route,cookie,form=None):
    data=urlencode(form,doseq=True).encode() if form is not None else None
    req=Request(origin+route,data=data,headers={'Cookie':'playtest_session='+cookie})
    try:
        with build_opener(NoRedirect).open(req,timeout=30) as response:
            return response.status,response.read(2_000_000),response.headers.get('X-Request-ID')
    except HTTPError as error:
        with error:return error.code,error.read(4096),error.headers.get('X-Request-ID')


def response_error(body):
    """Keep an actionable warning without copying game HTML or hidden tokens."""
    value=body.decode('utf-8',errors='replace')
    if not value.lstrip().startswith('<'):return value[:500]
    class Alert(HTMLParser):
        def __init__(self):super().__init__();self.depth=0;self.done=False;self.parts=[]
        def handle_starttag(self,tag,attrs):
            if self.done:return
            if self.depth:self.depth+=1
            elif dict(attrs).get('role')=='alert':self.depth=1
        def handle_endtag(self,tag):
            if self.depth:
                self.depth-=1
                if not self.depth:self.done=True
        def handle_data(self,text):
            if self.depth:self.parts.append(text)
    parsed=Alert();parsed.feed(value)
    return ' '.join(' '.join(parsed.parts).split())[:500] or 'HTML error response; inspect the player request log using its request ID.'


def job_observation(job):
    result={k:job.get(k) for k in ('job_id','job_type','status','target_building_id','target_derelict_id','work_completed','work_required','pause_reason','output_type','output_quantity','production_building_id','target_unit_id')}
    if job['job_type']=='manufacturing':
        inputs=json.loads(job['inputs_spent'])
        result['manufacturing']={k:inputs.get(k) for k in ('paid','remaining','produced','home_id')}
    return result


def observations(state,rates=None):
    if not state:return {'settlement_ready':False}
    from game.economy import storage
    return dict(settlement_ready=True,clock=state['settlement']['simulation_processed_at'],
        season_status=state['season']['status'],settlement_status=state['settlement']['status'],
        resources={k:v for k,v in state['resources'].items() if k in ('food','water','scrap','metal','electronics','credits')},
        reserved=state.get('reserved',{}),storage=storage(state),rates=rates,
        citizens=[{k:c.get(k) for k in ('citizen_id','level','current_hp','effective_morale','assignment','building_id','job_id','away')} for c in state['citizens']],
        buildings=[{k:b.get(k) for k in ('building_id','building_type','level','status','current_hp','origin_x','origin_y','rotation')} for b in state['buildings']],
        units=[{k:u.get(k) for k in ('unit_id','unit_type','status','current_hp','home_building_id')} for u in state.get('units',[])],
        inventory=state.get('inventory',[]),
        expeditions=[{k:r.get(k) for k in ('expedition_id','status','started_at','gather_until','returns_at','food','water','food_rate','water_rate','yields','delivered','discarded')} for r in state.get('expeditions',[])],
        munition_reservations=state.get('munition_reservations',[]),
        jobs=[job_observation(j) for j in state['jobs']],
        sites=[{k:d.get(k) for k in ('settlement_derelict_id','derelict_type','status','recovered_loot')} for d in state['derelicts']])
        # Private loot rolls/nonces, cookies, passwords and CSRF tokens are excluded.


def step(path,origin,bot):
    now=int(time.time());aid=bot['account_id']
    attempt=uuid.uuid4().hex
    context=dict(attempt=attempt,step=bot['steps'],seed=bot['seed']+bot['steps'],
                 personality=bot.get('personality','balanced'),policy_version=POLICY_VERSION,
                 scheduled_next_at=bot.get('scheduled_next_at'),decision_delay_seconds=bot.get('decision_delay_seconds'))
    bot_runtime.trace(path,aid,'step_started',context)
    decision=dict(route=None,reason='Waiting for settlement launch or resume.',form={})
    # Before refreshing, only enrollment matters; do not load the whole world.
    with snapshot(path) as c:
        enrolled=c.execute('SELECT 1 FROM settlements WHERE account_id=? LIMIT 1',(aid,)).fetchone()
    if not enrolled:
        bot_runtime.trace(path,aid,'waiting_for_settlement',context)
        bot_runtime.record(path,aid,now,decision);return decision['reason']
    cookie,session=accounts.new_session(path,aid,now)
    try:
        status,body,request_id=request(origin,'/api/resources',cookie)
        if status==202:
            # Cooperate with the same bounded catch-up used by human players.
            # Never choose or submit an action against a partially updated world.
            catch_status,_,catch_id=request(origin,'/api/catchup',cookie)
            decision=dict(route=None,reason='World catch-up in progress; completed batches are saved.',form={})
            bot_runtime.trace(path,aid,'catchup_deferred',dict(context,status=catch_status,request_id=catch_id))
            bot_runtime.record(path,aid,now,decision,catch_status,catch_id)
            return decision['reason']
        if status!=200:
            bot_runtime.trace(path,aid,'refresh_rejected',dict(context,status=status,request_id=request_id,response=response_error(body)))
            bot_runtime.record(path,aid,now,dict(route=None,reason='Could not refresh player snapshot.',form={}),status,request_id,'Refresh rejected');return 'Refresh rejected'
        values=json.loads(body)
        with snapshot(path) as c,account_scope(aid):state=read_state(c)
        if not state:raise ValueError('Bot settlement disappeared during refresh.')
        if any(values.get(key)!=state[table][field] for key,table,field in
               [('account_id','settlement','account_id'),('settlement_id','settlement','settlement_id'),('season_id','season','season_id'),('map_seed','season','map_seed')]):
            raise ValueError('Player server does not match the selected bot save.')
        bot_runtime.trace(path,aid,'observed',dict(context,observation=observations(state,values['rates']),public_targets=values.get('targets',[]),market=values.get('market')))
        decision=choose(state,values['rates'],bot['seed']+bot['steps'],bot.get('personality','balanced'),values.get('targets',[]),values.get('market'))
        bot_runtime.trace(path,aid,'decided',dict(context,decision=decision))
        # Pause may have been requested while snapshot refresh was in flight.
        with closing(connect_database(path)) as c:
            running=c.execute('SELECT state FROM bot_controllers WHERE account_id=?',(aid,)).fetchone()[0]=='running'
        if not running:decision=dict(route=None,reason='Controller paused before action.',form={})
        if decision['route']:
            bot_runtime.trace(path,aid,'action_started',dict(context,decision=decision))
            status,body,request_id=request(origin,decision['route'],cookie,dict(token=session['csrf'],**decision['form']))
            error=response_error(body) if status>=400 else None
            # Redirects are not followed: successful player actions normally return 303.
            with snapshot(path) as c,account_scope(aid):after=read_state(c)
            bot_runtime.trace(path,aid,'action_rejected' if status>=400 else 'action_completed',
                       dict(context,decision=decision,status=status,request_id=request_id,response_error=error,after=observations(after)))
            bot_runtime.record(path,aid,now,decision,status,request_id,error)
        else:
            bot_runtime.trace(path,aid,'wait',dict(context,decision=decision))
            bot_runtime.record(path,aid,now,decision)
        return decision['reason']
    except (ValueError,KeyError,URLError,OSError,sqlite3.Error) as error:
        bot_runtime.trace(path,aid,'controller_error',dict(context,decision=decision,error_type=type(error).__name__,error=str(error)[:300],
                                                  outcome='Unknown if transport failed after sending; inspect request/game logs before assuming rejection.'))
        bot_runtime.record(path,aid,now,decision,error=type(error).__name__+': '+str(error)[:300])
        return 'Controller error: '+type(error).__name__
    finally:
        cleanup_session(path,aid,cookie)


def cleanup_session(path,aid,cookie):
    try:
        with closing(connect_database(path)) as c,c:
            c.execute('DELETE FROM auth_sessions WHERE token_hash=?',(hashlib.sha256(cookie.encode()).hexdigest(),))
    except sqlite3.Error as error:
        bot_runtime.fallback(path,aid,'session_cleanup_deferred',dict(error_type=type(error).__name__,
            database_locked=bot_runtime.locked(error),outcome='Session expires normally; no credentials logged.'))


def run_iteration(path,origin,*,min_interval=60,jitter=60):
    # Claim once, attempt once. A sent action is never automatically replayed.
    bot=bots.claim(path,int(time.time()),min_interval=min_interval,jitter=jitter)
    if not bot:return False
    try:result=step(path,origin,bot)
    except Exception as error:
        contention=bot_runtime.locked(error)
        bot_runtime.trace(path,bot['account_id'],'unexpected_error',dict(error_type=type(error).__name__,
            step=bot['steps'],database_locked=contention,
            outcome='No replay; inspect request logs if a POST may already have completed.'))
        bot_runtime.record(path,bot['account_id'],int(time.time()),
            dict(route=None,reason='Controller step interrupted; no automatic replay.',form={}),error=type(error).__name__)
        result='Database busy; step deferred.' if contention else 'Unexpected controller failure: '+type(error).__name__
    print(f"Bot #{bot['account_id']}: {result}",flush=True)
    return True


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--game-url',default='http://127.0.0.1:8767')
    parser.add_argument('--min-interval',type=int,default=60,help='Minimum seconds between each bot decision (default: 60; at least 10).')
    parser.add_argument('--jitter',type=int,default=60,help='Add 0 to this many seconds to each bot interval (default: 60).')
    parser.add_argument('--action-gap',type=float,default=5,help='Seconds to pause after each bot turn before checking another (default: 5; at least 1).')
    args=parser.parse_args(argv)
    if args.min_interval<10:parser.error('--min-interval must be at least 10.')
    if args.jitter<0:parser.error('--jitter must be nonnegative.')
    if not 1<=args.action_gap<=3600:parser.error('--action-gap must be between 1 and 3600 seconds.')
    if not args.database.is_file():parser.error('Choose an existing playtest save.')
    try:origin=game_origin(args.game_url)
    except ValueError as error:parser.error(str(error))
    ready=False
    print('Bot runner ready. Only enabled controllers act. Database locks are deferred; Ctrl+C stops.',flush=True)
    print(f'Bot pacing: at least {args.min_interval}s per bot plus 0–{args.jitter}s stagger; {args.action_gap:g}s between turns. Longer configured bot intervals are retained.',flush=True)
    print(f'Fallback audit log: {bot_runtime.LOG_PATH}',flush=True)
    try:
        while True:
            try:
                if not ready:
                    bots.prepare(args.database);ready=True
                acted=run_iteration(args.database,origin,min_interval=args.min_interval,jitter=args.jitter)
                time.sleep(args.action_gap if acted else 2)
            except sqlite3.Error as error:
                bot_runtime.fallback(args.database,None,'runner_database_error',dict(error_type=type(error).__name__,database_locked=bot_runtime.locked(error)))
                if not bot_runtime.locked(error):
                    print('Database error; inspect the fallback log before restarting.',flush=True)
                    return 1
                print('Database busy; waiting 3 seconds before checking again.',flush=True)
                time.sleep(3)
    except KeyboardInterrupt:print('\nBot runner stopped; game servers remain running.',flush=True)


if __name__=='__main__':raise SystemExit(main())
