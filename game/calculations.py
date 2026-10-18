"""Bounded, operation-local reuse of pure utility allocations.

Only authoritative simulation opts in. Cache keys include every building and
citizen value read by economy.utilities. Configuration objects are retained with
entries (preventing object-ID reuse); rules are fixed during a simulation call.
Every caller receives its own mutable allocation: production_flow throttles it.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
from time import perf_counter

CURRENT = ContextVar('simulation_calculations', default=None)
BUILDING_FIELDS = ('building_id','building_type','level','origin_x','origin_y',
                   'rotation','current_hp','status','completed_at','created_at')
CITIZEN_FIELDS = ('citizen_id','building_id','assignment','away','current_hp',
                  'level','morale','effective_morale')


@contextmanager
def scope():
    current = CURRENT.get()
    if current is not None:
        yield current
        return
    current = {'cache': OrderedDict(), 'utility_calls': 0, 'utility_hits': 0,
               'utility_compute_ms': 0.0, 'state_reads': 0, 'state_read_ms': 0.0,
               'simulation_intervals': 0, 'long_intervals': 0, 'long_interval_seconds': 0,
               'rule_snapshots': {}, 'rule_snapshot_hits': 0, 'step_limits': {}}
    token = CURRENT.set(current)
    try:
        yield current
    finally:
        CURRENT.reset(token)


def simulated(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with scope():
            return function(*args, **kwargs)
    return wrapped


def utility_allocation(function):
    @wraps(function)
    def wrapped(state):
        current = CURRENT.get()
        if current is None:
            return function(state)
        current['utility_calls'] += 1
        key = (id(state['config']), state['season']['config_version'],
               tuple(tuple(b.get(k) for k in BUILDING_FIELDS) for b in state['buildings']),
               tuple(tuple(c.get(k) for k in CITIZEN_FIELDS) for c in state['citizens']))
        cache = current['cache']
        if key in cache:
            current['utility_hits'] += 1
            cache.move_to_end(key)
            return deepcopy(cache[key][1])
        started = perf_counter()
        result = function(state)
        current['utility_compute_ms'] += (perf_counter()-started)*1000
        cache[key] = (state['config'], deepcopy(result))
        if len(cache) > 8:
            cache.popitem(last=False)
        return result
    return wrapped


def state_reads(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        current=CURRENT.get()
        if current is None:
            return function(*args, **kwargs)
        started=perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            current['state_reads']+=1
            current['state_read_ms']+=(perf_counter()-started)*1000
    return wrapped


def record_limits(start,target,boundaries):
    """Record actual chosen boundaries, including ties, without extra queries."""
    current=CURRENT.get()
    if current is None:return
    labels=[label for label,at in boundaries if at is not None and abs(at-target)<1e-7]
    if not labels:labels=['XP minute alignment']
    counts=current['step_limits']
    for label in set(labels):counts[label]=counts.get(label,0)+1
