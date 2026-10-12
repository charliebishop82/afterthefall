"""Workbook scoring from persisted ownership; public output contains totals only."""
from functools import lru_cache
from pathlib import Path
import json

from game.buildings import spec
from game.ruins import invested


@lru_cache(maxsize=1)
def settings():
    path = Path(__file__).resolve().parents[1] / 'config' / 'expansion_v1.json'
    return json.loads(path.read_text(encoding='utf-8'))['settings']


def resources_value(state, prefix='wealth'):
    rules = settings()['Scoring']
    return sum(state['resources'][key] * rules[f'{prefix}_{key}_value']
               for key in ('food', 'water', 'scrap', 'metal', 'electronics'))


def buildings_value(state, development=False):
    rules = settings()['Scoring']
    value = 0
    for building in state['buildings']:
        if building['status'] not in ('active', 'upgrading', 'construction'):
            continue
        costs, _ = invested(state, building)
        base = sum(costs[key] * rules[f'settlement_building_{key}_value']
                   for key in ('scrap', 'metal', 'electronics'))
        # invested() already scales construction cost by completed work. Apply
        # recorded hostile damage relative to that work, without scaling twice.
        condition = min(1, max(0, building['current_hp'] / spec(state, building)['hp']))
        if building['status']=='construction':
            job=next((j for j in state['jobs'] if j['target_building_id']==building['building_id']
                      and j['job_type']=='construction' and j['status'] in ('active','paused')),None)
            completed_hp=spec(state,building)['hp']*job['work_completed']/job['work_required'] if job else 0
            damage=json.loads(job['inputs_spent']).get('_damage',0) if job else 0
            condition=max(0,1-damage/completed_hp) if completed_hp else 0
        bonus = 1 + rules['development_level_bonus'] / 100 * (building['level'] - 1) if development else 1
        value += base * condition * bonus
    return value


def totals(state, loans=(), investments=()):
    rules = settings()['Scoring']
    living = [c for c in state['citizens'] if c['current_hp'] > 0]
    population = sum(rules['population_count_value'] + (c['level']-1) * rules['population_level_value'] for c in living)
    military = sum(c['level'] * rules['military_citizen_level_value'] for c in living)
    keys = {'offensive_drone': 'offensive', 'air_defense_drone': 'air',
            'ground_defense_drone': 'ground', 'repair_drone': 'repair'}
    for unit in state.get('units', ()):
        if unit['status'] == 'destroyed' or unit['current_hp'] <= 0:
            continue
        maximum = state['config']['units'][unit['unit_type']]['hp']
        military += rules[f'military_{keys[unit["unit_type"]]}_drone_value'] * min(1, unit['current_hp'] / maximum)
    for inventory in state.get('inventory', ()):
        military += inventory['quantity'] * rules[f'military_{inventory["unit_type"]}_value']
    # Launched ammunition remains owned until consumed. Inventory has already
    # been debited at launch, so include it exactly once here.
    for reservation in state.get('munition_reservations', ()):
        military += reservation['quantity'] * rules['military_missile_value']
    for building in state['buildings']:
        if building['status'] in ('active', 'upgrading'):
            definition = spec(state, building)
            military += definition.get('defense_strength', 0) * rules['military_defense_strength_value'] * min(1, building['current_hp']/definition['hp'])
    debt = sum(row['outstanding_balance'] for row in loans if row['status'] in ('active', 'liquidating', 'settled'))
    invested_credits = sum(row['principal'] + row['accrued_interest'] for row in investments if row['status'] == 'active')
    wealth = resources_value(state) + state['resources']['credits'] + invested_credits - debt
    return dict(population=population, military=military, wealth=wealth,
                development=buildings_value(state, development=True))


def rank(players):
    """Competition ranks with the workbook's visible, shared tie handling."""
    categories = ('population', 'military', 'wealth', 'development')
    rules = settings()['Scoring']
    denominators = {}
    for category in categories:
        values = [p[category] for p in players]
        leader = max(values, default=0)
        denominators[category] = leader if leader > 0 else max([abs(v) for v in values] + [1])
    rows = []
    for player in players:
        row = dict(player)
        row['overall'] = sum(player[c] / denominators[c] * rules[f'overall_{c}_weight'] for c in categories)
        rows.append(row)
    key = lambda row: tuple(row[c] for c in ('overall', 'development', 'population', 'wealth', 'military'))
    rows.sort(key=key, reverse=True)
    previous = None
    for index, row in enumerate(rows, 1):
        signature = key(row)
        position = index if signature != previous else position
        row['rank'] = position
        previous = signature
    return rows
