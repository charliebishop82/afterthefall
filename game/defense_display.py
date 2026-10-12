"""Baseline citizen-raid defense display, using existing combat helpers."""


def local_defense(state):
    from game import combat,drones,structural,support
    hall=state['buildings'][0]
    guard_ids={c['citizen_id'] for c in support.guards(state)}
    defenders=[c for c in combat.home(state) if c['current_hp']>0 and
               (c['assignment'] in ('unassigned','patrol') or
                c['assignment']=='defender' and (not support.enabled(state) or c['citizen_id'] in guard_ids))]
    if structural.enabled(state):
        defenders += [c for c in combat.home(state) if c['building_id']==hall['building_id'] and
                      c['current_hp']>0 and c not in defenders]
    citizens=sum(combat.strength(state,c)*(1+combat.rule('patrol_strength_bonus')/100
                 if c['assignment']=='patrol' else 1) for c in defenders)
    components=dict(citizens=citizens,ground_drones=sum(drones.strength(state,u) for u in drones.ready(state,'ground_defense_drone')),
                    guard_posts=support.defense_bonus(state),turrets=structural.turret_strength(state,'automated_turret',hall))
    return dict(total=sum(components.values()),**components)


def description(values):
    return (f"Citizens {values['citizens']:.1f}; ground drones {values['ground_drones']:.1f}; "
            f"Guard Posts {values['guard_posts']:.1f}; turrets {values['turrets']:.1f}. "
            'Local citizen-raid defense at the Town Hall, before randomness/allies. Air defense and missile interception are separate.')
