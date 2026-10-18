"""Conservative market decisions using only ordinary public/own-player data."""
import math
import random
from game.trading import available

MATERIALS=('scrap','metal','electronics')


def purchase(state, market, resource, needed, purpose, action, emergency=False):
    from game.economy import storage
    if not market or not market.get('can_trade'):return None
    cap=storage(state)
    room=(cap[resource]-state['resources'][resource] if resource in ('food','water')
          else cap['material']-sum(state['resources'][r] for r in MATERIALS))
    budget=max(0,available(state,'credits')-(0 if emergency else 50))
    choices=[]
    row=market['resources'][resource]
    for source,stock,price in [('buy',row['stock'],row['buy_price']),
                               ('reserve_buy',row['reserve_remaining'],row['reserve_price'])]:
        quantity=min(math.ceil(needed),int(stock),math.floor(room+1e-8),int(budget//price))
        if quantity>0:choices.append((price,source,quantity))
    if not choices:return None
    # Buy shared goods first when prices tie; preserve the personal fallback.
    price,source,quantity=min(choices,key=lambda v:(v[0],v[1]!='buy'))
    return action('/market',f'Buy {quantity} {resource} for {purpose}; '+
                  ('shared stock' if source=='buy' else 'daily personal reserve')+f' at {price} Credits/unit.',
                  action=source,resource=resource,quantity=quantity)


def choose_market(state,rates,seed,action,market,*,costs=None,purpose='construction',emergency_only=False):
    if not market or not market.get('can_trade'):return None
    from game.economy import storage
    cap=storage(state)
    # Supply support is first. Buy a buffer while a deficit threatens the next two hours.
    shortages=[]
    for r in ('food','water'):
        demand=rates.get(r,{}).get('consumption',0)
        net=rates.get(r,{}).get('net',0)
        stock=available(state,r)
        if net<0 and stock<max(5,demand*2):
            shortages.append((stock/max(1,-net),r,max(10,demand*6)-stock))
    for _,r,needed in sorted(shortages):
        decision=purchase(state,market,r,needed,'an urgent supply buffer',action,emergency=True)
        if decision:return decision
    if emergency_only:return None
    if costs:
        # Do not accumulate a project that cannot fit in current material storage.
        if sum(costs.get(r,0) for r in MATERIALS)>cap['material']+1e-8:return None
        for r in MATERIALS:
            missing=costs.get(r,0)-available(state,r)
            if missing>0:
                decision=purchase(state,market,r,missing,purpose,action)
                if decision:return decision
        room=cap['material']-sum(state['resources'][r] for r in MATERIALS)
        if room<1 and any(available(state,r)<costs.get(r,0) for r in MATERIALS):
            decision=make_room(state,rates,market,costs,action)
            if decision:return decision
        return None
    # Sell only positive net production/recovery near capacity, never promised goods.
    rng=random.Random(seed);resources=['food','water',*MATERIALS];rng.shuffle(resources)
    for r in resources:
        if rates.get(r,{}).get('net',0)<=0 and not (r in MATERIALS and sum(state['resources'][k] for k in MATERIALS)>=cap['material']-1e-8):continue
        stock=available(state,r)
        if r in ('food','water'):
            if state['resources'][r]<cap[r]*.85:continue
            keep=min(cap[r]*.8,max(cap[r]*.5,rates.get(r,{}).get('consumption',0)*6))
        else:
            if sum(state['resources'][k] for k in MATERIALS)<cap['material']*.85:continue
            keep=max({'scrap':80,'metal':40,'electronics':10}[r],rates.get(r,{}).get('consumption',0)*6)
            # Protect inputs already committed to finite/repeating manufacturing orders.
            if any(j['job_type']=='manufacturing' and j['status'] in ('queued','active','paused') for j in state.get('jobs',[])):
                continue
        quantity=min(25,math.floor(stock-keep))
        if quantity>0 and quantity*market['resources'][r]['sell_price']>=2:
            return action('/market',f'Sell {quantity} surplus {r} to free storage while keeping a working reserve.',
                          action='sell',resource=r,quantity=quantity)
    return None


def make_room(state,rates,market,costs,action):
    """Sell excess material even when capped production reports zero net flow."""
    if any(j['job_type']=='manufacturing' and j['status'] in ('queued','active','paused') for j in state.get('jobs',[])):return None
    candidates=[]
    for r in MATERIALS:
        keep=max(costs.get(r,0),{'scrap':80,'metal':40,'electronics':10}[r],rates.get(r,{}).get('consumption',0)*6)
        quantity=min(25,math.floor(available(state,r)-keep))
        if quantity>0 and quantity*market['resources'][r]['sell_price']>=2:candidates.append((quantity,r))
    if not candidates:return None
    quantity,r=max(candidates)
    return action('/market',f'Sell {quantity} excess {r} to make room for missing project materials; preserve the project cost and working reserve.',action='sell',resource=r,quantity=quantity)
