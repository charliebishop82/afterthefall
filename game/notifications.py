"""Player event summaries; internal random rolls stay in operator logs."""

def event(connection,state,kind,now,data,event_id):
    message=None
    if kind=='building_project_completed':
        message=f'{data["building_type"].replace("_"," ").title()} #{data["building_id"]}: {data["job_type"]} completed, level {data["level"]}.'
    elif kind=='citizen_raid_incoming':
        message=f'Incoming hostile attack #{data["attack_id"]}; arrival at UTC timestamp {data["resolves_at"]}.'
    elif kind=='citizen_raid_resolved':
        message=f'Attack #{data["attack_id"]} resolved: {data["result"].replace("_"," ")}.'
    elif kind in ('citizen_supply_death','citizen_died'):
        message=f'Citizen #{data["citizen_id"]} died: {data.get("cause","supply_shortage").replace("_"," ")}.'
    elif kind=='citizen_daily_rollover':
        parts=[]
        if data.get('birth_citizen_id'):parts.append(f'Citizen #{data["birth_citizen_id"]} was born')
        if data.get('deserted'):parts.append(f'{len(data["deserted"])} citizens deserted')
        if data.get('floor_arrivals'):parts.append(f'{len(data["floor_arrivals"])} recovery survivors arrived')
        if parts:message='; '.join(parts)+'.'
    elif kind in ('captured_citizen_deserted','captured_citizen_integrated'):
        message=f'Captured citizen #{data["citizen_id"]} '+('deserted.' if kind.endswith('deserted') else 'integrated.')
    elif kind=='building_repair_completed':
        message=f'Building #{data["building_id"]} repairs completed.'
    elif kind=='drone_repair_completed':
        message=f'Drone #{data["unit_id"]} repairs completed.'
    elif kind=='deployed_drone_home_destroyed':
        message=f'Drone home #{data["building_id"]} was destroyed while {len(data["unit_ids"])} drones were away. They will finish their mission and deliver earned rewards. Rebuild compatible storage before they return: drones without free slots will be destroyed on return.'
    elif kind=='military_unit_produced':
        message=f'{data["unit_type"].replace("_"," ").title()} manufactured for storage #{data["home_building_id"]}.'
    elif kind=='prototype_survivor_arrived':
        message=f'Survivor citizen #{data["citizen_id"]} joined the settlement.'
    elif kind=='bank_interest':
        message=f'Loan #{data["loan_id"]}: debt {data["before"]} -> {data["after"]} Credits after interest.'
    elif kind=='bank_liquidation_sale':
        message=f'Bank liquidation sold {data["asset_type"]} #{data["asset_id"]} for {data["credits"]} Credits.'
    elif kind=='bank_transaction':
        message=f'Bank: {data["kind"].replace("_"," ")}, {data["amount"]:+d} Credits.'
    if message:
        from game.social import notify
        notify(connection,state['settlement']['account_id'],state['season']['season_id'],kind,message,now,'game_event',event_id)
