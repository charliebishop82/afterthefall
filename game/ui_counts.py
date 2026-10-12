"""Read-only resident totals shared by initial rendering and live updates."""


def citizen_counts(state):
    citizens=state['citizens']
    return dict(total=len(citizens),free=sum(c['assignment']=='unassigned' and
                c['current_hp']>0 and not c.get('away',False) for c in citizens))
