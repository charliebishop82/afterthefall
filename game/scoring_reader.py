"""Lean saved standings; use the existing formulas without full game-state loading."""
from collections import defaultdict
from game import scoring, expansion
from game.read_queries import read_connection
from game.settlement import load_config

# Preserve the existing participant order and latest-settlement selection. A
# historical season view previously resolved each account through read_state.
PARTICIPANTS = """WITH score_settlements AS (
    SELECT current.* FROM settlements selected JOIN settlements current
    ON current.settlement_id=(SELECT s.settlement_id FROM settlements s
        WHERE s.account_id=selected.account_id ORDER BY s.season_id DESC LIMIT 1)
    WHERE selected.season_id=?) """


def saved_scores(connection, season_id):
    with read_connection(None,connection,rows=True) as c:
        settlements=[dict(r) for r in c.execute(PARTICIPANTS+'SELECT * FROM score_settlements',(season_id,))]
        # Explicitly retain the original selected-season order, including ties.
        order=[r[0] for r in c.execute('SELECT account_id FROM settlements WHERE season_id=? ORDER BY settlement_id',(season_id,))]
        by_account={s['account_id']:s for s in settlements}
        settlements=[by_account[aid] for aid in order]
        if not settlements:return []
        seasons={r['season_id']:dict(r) for r in c.execute(PARTICIPANTS+
            'SELECT se.* FROM seasons se WHERE se.season_id IN (SELECT season_id FROM score_settlements)',(season_id,))}
        # Rules are read-only during scoring. Prepare once per season in this
        # call; no state/config object is retained in the returned scalar rows.
        configs={sid:expansion.overlay(c,sid,load_config(se['config_version']))[0] for sid,se in seasons.items()}

        def rows(table,fields,where='',order_by=''):
            grouped=defaultdict(list)
            sql=PARTICIPANTS+f'SELECT t.settlement_id,{fields} FROM {table} t JOIN score_settlements s ON s.settlement_id=t.settlement_id '+where
            if order_by:sql+=' ORDER BY '+order_by
            for row in c.execute(sql,(season_id,)):grouped[row['settlement_id']].append(dict(row))
            return grouped

        resources=rows('settlement_resources','t.food,t.water,t.scrap,t.metal,t.electronics,t.credits')
        buildings=rows('buildings','t.building_id,t.building_type,t.level,t.current_hp,t.status',order_by='t.building_id')
        citizens=rows('citizens','t.level,t.current_hp',"WHERE t.status='alive'",'t.citizen_id')
        jobs=rows('settlement_jobs','t.target_building_id,t.job_type,t.status,t.work_completed,t.work_required,t.inputs_spent',
                  "WHERE t.job_type IN ('construction','upgrade') AND t.status IN ('completed','active','paused')",'t.job_id')
        units=rows('military_units','t.unit_type,t.current_hp,t.status',order_by='t.unit_id')
        inventory=rows('military_inventory','t.unit_type,t.quantity',order_by='t.inventory_id')
        loans=rows('bank_loans','t.outstanding_balance,t.status',
                   "WHERE t.status IN ('active','liquidating') OR (t.status='settled' AND t.outstanding_balance>0)",'t.loan_id')
        investments=rows('bank_investments','t.principal,t.accrued_interest,t.status',"WHERE t.status='active'",'t.investment_id')
        munitions=defaultdict(list)
        for row in c.execute(PARTICIPANTS+"""SELECT am.participant_settlement_id AS settlement_id,
            am.quantity-am.consumed_quantity AS quantity FROM attack_munitions am
            JOIN score_settlements s ON s.settlement_id=am.participant_settlement_id
            JOIN attacks a USING(attack_id) JOIN military_inventory i USING(inventory_id)
            WHERE am.role='attacker' AND a.status='in_flight'""",(season_id,)):
            munitions[row['settlement_id']].append(dict(row))
        players=[]
        for settlement in settlements:
            sid=settlement['settlement_id']
            if not resources[sid] or not buildings[sid] or buildings[sid][0]['building_type']!='town_hall':
                raise ValueError('This save is incomplete. No data was changed.')
            state=dict(settlement=settlement,season=seasons[settlement['season_id']],
                       config=configs[settlement['season_id']],resources=resources[sid][0],
                       buildings=buildings[sid],citizens=citizens[sid],jobs=jobs[sid],
                       units=units[sid],inventory=inventory[sid],munition_reservations=munitions[sid])
            result=scoring.totals(state,loans[sid],investments[sid])
            players.append(dict(result,settlement_id=sid,name=settlement['settlement_name'],
                                processed_at=settlement['simulation_processed_at']))
        return scoring.rank(players)
