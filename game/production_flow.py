"""Storage-aware continuous work, shared by resource delivery and work XP."""
from game.trading import available

MATERIALS = ('scrap', 'metal', 'electronics')


def headroom_rate(room, seconds):
    room = max(0, room)
    if seconds:
        return room * 3600 / seconds
    return float('inf') if room > 1e-8 else 0


def material_flow(state, utility, loot, capacity, seconds):
    """Share accepted incoming volume between salvage and renewable production.

    Resolve renewable sources before converters, regardless of building age.
    Reuse the converter/storage calculation so new Scrap cannot overfill storage
    or earn work XP for discarded output.
    """
    sources={bid:status['outputs'].pop('scrap') for bid,status in utility['buildings'].items()
             if status['outputs'].get('scrap') and not status['inputs']}
    original=loot['scrap'];total=original+sum(sources.values())
    loot['scrap']=total
    _material_flow(state,utility,loot,capacity,seconds)
    if sources:
        fraction=min(1,max(0,loot['scrap']/total))
        loot['scrap']=original*fraction
        for bid,output in sources.items():
            status=utility['buildings'][bid]
            status['outputs']['scrap']=output*fraction
            status['work_fraction']*=fraction
            if fraction<1:
                status['reason']='Output storage is full' if fraction==0 else 'Limited by output storage'


def _material_flow(state, utility, loot, capacity, seconds):
    """Discard incoming salvage before wasting converter output or inputs.

    The workbook's converters lose material volume and form a Scrap -> Metal ->
    Electronics chain. Incoming salvage can feed an empty input pool, but its
    final products must still fit. A bounded search finds how much can be kept.
    """
    ordered = sorted(utility['buildings'].items(),
                     key=lambda item: (bool(item[1]['inputs'].get('metal', 0)), item[0]))
    raw = {bid: (dict(status['inputs']), dict(status['outputs'])) for bid, status in ordered}

    def evaluate(keep):
        supply = {r: loot[r] * keep for r in MATERIALS}
        processed = {}
        for bid, status in ordered:
            inputs, outputs = raw[bid]
            ratio = 1.0
            for resource, demand in inputs.items():
                stock = available(state, resource)
                if demand and (seconds or stock <= 1e-8):
                    incoming = max(0, supply[resource] + (stock * 3600 / seconds if seconds else 0))
                    ratio = min(ratio, incoming / demand)
            ratio = min(1, ratio)
            used = {r: value * ratio for r, value in inputs.items()}
            made = {r: value * ratio for r, value in outputs.items()}
            for resource in MATERIALS:
                supply[resource] += made.get(resource, 0) - used.get(resource, 0)
            processed[bid] = (used, made, ratio)
        return supply, processed

    budget = headroom_rate(capacity - sum(state['resources'][r] for r in MATERIALS), seconds)
    keep = 1.0
    supply, processed = evaluate(keep)
    excess = sum(supply.values()) - budget
    if excess > 1e-9:
        # Preserve incoming inputs that are already doing useful conversion work.
        # Removing surplus first also avoids mistaking a later converter's freed
        # capacity for a storage stall in an earlier converter.
        unused = {}
        for resource in MATERIALS:
            stock = available(state, resource)
            stock_rate = stock * 3600 / seconds if seconds else (float('inf') if stock > 1e-8 else 0)
            used = sum(values[0].get(resource, 0) for values in processed.values())
            made = sum(values[1].get(resource, 0) for values in processed.values())
            needed = max(0, used - made - stock_rate)
            unused[resource] = max(0, loot[resource] - needed)
        total = sum(unused.values())
        if total:
            fraction = min(1, excess / total)
            for resource in MATERIALS:
                loot[resource] -= unused[resource] * fraction
            supply, processed = evaluate(keep)
    if sum(supply.values()) > budget + 1e-9 and any(loot[r] for r in MATERIALS):
        low, high = 0.0, 1.0
        for _ in range(40):
            middle = (low + high) / 2
            candidate, _ = evaluate(middle)
            if sum(candidate.values()) <= budget:
                low = middle
            else:
                high = middle
        keep = low
        if keep < 1e-10:
            keep = 0.0
        supply, processed = evaluate(keep)
    for resource in MATERIALS:
        loot[resource] *= keep
    for bid, status in ordered:
        status['inputs'], status['outputs'], ratio = processed[bid]
        status['work_fraction'] = ratio
        if ratio < 1 and raw[bid][0]:
            status['reason'] = 'Waiting for input materials' if ratio == 0 else 'Limited by arriving input materials'


def supply_flow(state, utility, loot, store, hall_outputs, consumption, protected, seconds):
    """Share useful Food/Water throughput across their continuous producers."""
    hall_fractions = []
    for resource in ('food', 'water'):
        reserved = state.get('reserved', {}).get(resource, 0)
        usable = max(0, state['resources'][resource] - reserved - (protected if resource == 'food' else 0))
        room = max(0, store[resource] - reserved) - usable
        budget = consumption[resource] + headroom_rate(room, seconds)
        loot[resource] = min(loot[resource], budget)
        continuous = hall_outputs[resource] + sum(s['outputs'].get(resource, 0) for s in utility['buildings'].values())
        ratio = min(1, max(0, budget - loot[resource]) / continuous) if continuous else 1
        if hall_outputs[resource]:
            hall_fractions.append(ratio)
        hall_outputs[resource] *= ratio
        for status in utility['buildings'].values():
            if status['outputs'].get(resource, 0):
                status['outputs'][resource] *= ratio
                status['work_fraction'] *= ratio
                status['output'] = status['outputs'].get('food', 0)
                if ratio < 1:
                    status['reason'] = 'Output storage is full' if ratio == 0 else 'Limited by output storage'
    utility['hall_work_fraction'] = max(hall_fractions, default=1)


def input_retry(state, rates, statuses):
    """Retry only when arriving material can feed the waiting converter.

    An empty Scrap pool must not force one-second steps forever when an
    Electronics Fabricator is waiting for Metal and no Metal is arriving.
    Resource depletion, work, health, XP and other boundaries still apply.
    """
    from game.buildings import spec
    for building in state['buildings'][1:]:
        status=statuses.get(building['building_id'],{})
        if status.get('reason')!='Waiting for input materials':
            continue
        settings=spec(state,building)
        if any(settings.get(r+'_input',0)>0 and available(state,r)<=1e-8
               and rates[r]['production']>0 for r in ('scrap','metal')):
            return True
    return False
