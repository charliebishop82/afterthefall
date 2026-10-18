"""Own-settlement mission summaries from persisted reports; no simulation writes."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3


def goods(values):
    return ', '.join(f'{float(v):.2f} {k.title()}' for k,v in values.items() if isinstance(v,(int,float)) and v>0) or 'none'


def raid_summary(report,attacking):
    result=report['result']
    title=('Raid succeeded' if attacking else 'Settlement raided') if result=='attacker_win' else ('Raid repelled' if attacking else 'Defense succeeded') if result=='defender_win' else 'Contested battle'
    loot=report.get('loot',{})
    if attacking:
        text='Delivered: '+goods(loot.get('deposited',{}))+'. Storage overflow: '+goods(loot.get('lost',{}))+'.'
    else:text='Resources taken from your settlement: '+goods(loot.get('taken',{}))+'.'
    credits=report.get('credits_taken',0)
    if credits:text+=f' Credits {"gained" if attacking else "lost"}: {credits:g}.'
    people=report.get('attackers' if attacking else 'defenders',[])
    injured=sum(p.get('hp_after',0)>0 and p.get('hp_after',0)<p.get('hp_before',0) for p in people)
    dead=sum(p.get('hp_after',1)<=0 for p in people)
    text+=f' Your participating citizens: {injured} injured, {dead} dead. Open the battle report for captures, hardware and building damage.'
    return title,text


def expedition_summary(row):
    delivered=row.get('delivered') or {};discarded=row.get('discarded') or {};gathered=row.get('gathered') or {}
    if isinstance(delivered,str):delivered=json.loads(delivered)
    if isinstance(discarded,str):discarded=json.loads(discarded)
    if isinstance(gathered,str):gathered=json.loads(gathered)
    return 'Explorers returned','Gathered: '+goods(gathered)+'. Delivered (including unused provisions): '+goods(delivered)+'. Storage overflow: '+goods(discarded)+'.'


def snapshot(path,state):
    sid=state['settlement']['settlement_id'];season=state['season']['season_id'];rows=[]
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
        for row in c.execute('''SELECT b.report_id,b.attack_id,b.created_at,b.report_data,a.attacker_settlement_id FROM battle_reports b JOIN attacks a USING(attack_id) WHERE b.recipient_settlement_id=? AND a.season_id=? ORDER BY b.report_id DESC LIMIT 10''',(sid,season)):
            title,text=raid_summary(json.loads(row['report_data']),row['attacker_settlement_id']==sid)
            rows.append(dict(id='raid-'+str(row['report_id']),at=row['created_at'],title=f'Raid #{row["attack_id"]} · '+title,text=text,href='#conflict'))
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='waste_expeditions'").fetchone():
            for row in c.execute("SELECT * FROM waste_expeditions WHERE settlement_id=? AND season_id=? AND status='returned' ORDER BY expedition_id DESC LIMIT 10",(sid,season)):
                title,text=expedition_summary(dict(row));rows.append(dict(id='expedition-'+str(row['expedition_id']),at=row['returned_at'],title=f'Expedition #{row["expedition_id"]} · '+title,text=text,href='#expeditions'))
    return dict(settlement_id=sid,results=sorted(rows,key=lambda r:(r['at'],r['id']),reverse=True)[:20])
