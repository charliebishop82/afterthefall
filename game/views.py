"""Small, escaped server-rendered pages; no frontend framework required."""

from collections import Counter
import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from string import Template

from game.settlement import load_config
from game.simulation import resource_rates
from game.buildings import spec, rules
from game.building_views import panels, map_additions, live_payload, map_staff, staff_badge, map_job_badge, map_filter_flags, filter_attributes

ROOT = Path(__file__).resolve().parents[1]


def render_page(state, token, error='', name='New Avalon'):
    def template(file, **values):
        return Template((ROOT / 'templates' / file).read_text(encoding='utf-8')).substitute(values)

    if state is None:
        config = load_config()
        content = template('welcome.html', token=escape(token, quote=True), name=escape(name, quote=True),
                           error=f'<p class="error" role="alert">{escape(error)}</p>' if error else '',
                           population=config['starting_population'])
        title = 'A place to begin'
        status = 'LOCAL PROTOTYPE'
    else:
        config = state['config']
        title = state['settlement']['settlement_name']
        status = 'SAVED ON THIS COMPUTER'
        hall = state['buildings'][0]
        hall_config = config['town_hall']
        if config['version'] in ('prototype_v3','prototype_v4','prototype_v5','prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
            hall_config = spec(state, hall)
        resources = state['resources']
        rates = resource_rates(state)
        homes = None
        if config['version'] in ('prototype_v5','prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
            from game.population import housing
            homes = housing(state)
        from game.storage_display import storage_status, badge, capacity_label
        capacities=storage_status(state,rates)
        supplies = ''.join(f'<div class="resource{" is-full" if capacities.get(key,{}).get("full") else ""}"><span>{label}</span><strong id="amount-{key}">{resources[key]:.2f}</strong>'
                           + (capacity_label(key,capacities[key])+badge(key,capacities[key]) if key in capacities else '') +
                           f'<small id="header-rate-{key}">{note}</small></div>' for key, label, note in [
                               ('food', 'Food', f'{rates["food"]["net"]:+g} / hour when running'),
                               ('water', 'Water', f'{rates["water"]["net"]:+g} / hour when running'),
                               ('scrap', 'Scrap', f'{rates["scrap"]["net"]:+.1f}/h net' if 'scrap' in rates else 'building material'),
                               ('metal', 'Metal', f'{rates["metal"]["net"]:+.1f}/h net' if 'metal' in rates else 'building material'),
                               ('electronics', 'Electronics', f'{rates["electronics"]["net"]:+.1f}/h net' if 'electronics' in rates else 'advanced material'), ('credits', 'Credits', 'settlement funds')])
        from game.ui_counts import citizen_counts
        counts=citizen_counts(state)
        supplies += (f'<div class="resource"><span><a href="#citizens">Citizens</a></span>'
                     f'<strong id="citizens-total">{counts["total"]}</strong><small>total residents, including away</small></div>'
                     f'<div class="resource"><span><a href="#citizens" title="Unassigned, at home, above zero health">Free citizens</a></span>'
                     f'<strong id="citizens-free">{counts["free"]}</strong><small>available for assignment</small></div>')
        from game.defense_display import local_defense, description
        defense=local_defense(state)
        supplies += (f'<div class="resource"><span><a href="#conflict" id="defense-help" title="{escape(description(defense),quote=True)}">Ground defense</a></span>'
                     f'<strong id="ground-defense">{defense["total"]:.1f}</strong><small>local · Town Hall</small></div>')
        from game.progression import enabled as progression_enabled
        name_counts=Counter(c['name'] for c in state['citizens'])
        from game.citizen_portal import data as citizen_card_data
        citizens = ''.join(f'<tr data-citizen-id="{c["citizen_id"]}" data-citizen-card="{escape(json.dumps(citizen_card_data(state,c)),quote=True)}"><th scope="row">' + escape(c['name']) + (f' <small>#{c["citizen_id"]}</small>' if name_counts[c['name']] > 1 else '') + '</th>'
                           f'<td>{c["level"]}{("<br><small>"+format(c["xp"],".2f")+" XP</small>") if progression_enabled(state) else ""}</td><td>{c["current_hp"]:g} HP</td>'
                           '<td>'+escape(c['sex'].title())+'</td>'
                           + f'<td><span class="role {"assigned" if c["assignment"] == "administrator" else ""}">'
                           + escape('Exploring the Wastes' if c.get('exploring') else 'Raiding' if c.get('away') else c['assignment'].replace('_', ' ').title()) + '</span></td><td>'
                           + escape((homes['assignments'][c['citizen_id']]['name'] if homes['assignments'][c['citizen_id']] else 'Homeless') if homes else 'Town Hall')
                           + '</td><td>'+f'{c.get("effective_morale",c["morale"]):g}'
                           + (f' ({c["housing_morale_modifier"]:+g} housing)' if c.get('housing_morale_modifier') else '')
                           + '</td></tr>'
                           for c in state['citizens'])
        size_x, size_y = config['map_width'], config['map_height']
        # SVG uses logical tiles directly, with no persistent tile rows or artwork dependency.
        map_svg = f'''<svg viewBox="0 0 {size_x} {size_y}" role="img" aria-labelledby="map-title map-description">
          <title id="map-title">Settlement map</title>
          <desc id="map-description">{size_x} by {size_y} tiles. Level {hall['level']} Town Hall at {hall['origin_x']}, {hall['origin_y']}, occupying 3 by 3 tiles. {len(state['buildings'])-1} Food buildings or sites. Dashed line shows Town Hall utility coverage.</desc>
          <defs><pattern id="tiles" width="1" height="1" patternUnits="userSpaceOnUse"><path d="M 1 0 L 0 0 0 1" fill="none" stroke="#41483a" stroke-width=".045"/></pattern></defs>
          <rect width="{size_x}" height="{size_y}" fill="#252c23"/>
          <rect width="{size_x}" height="{size_y}" fill="url(#tiles)"/>
          <path d="M 0 20 H 40 M 20 0 V 40" stroke="#c6b679" stroke-width=".07" stroke-dasharray=".25 .35" opacity=".22"/>
          <a {filter_attributes("town-hall",map_filter_flags(state))} href="#town-hall" aria-label="Inspect Town Hall">
            <rect x="{hall['origin_x']}" y="{hall['origin_y']}" width="3" height="3" fill="#bca264" stroke="#ead7a4" stroke-width=".12"/>
            <path d="M {hall['origin_x']+.5} {hall['origin_y']+1.2} l 1 -.6 1 .6 v 1.1 h -2 Z" fill="#35372c"/>
            <text x="{hall['origin_x']+1.5}" y="{hall['origin_y']+4.1}" text-anchor="middle" fill="#f0e7d0" font-size=".7">TOWN HALL</text>
            {map_job_badge(state,hall['building_id'],hall['origin_x']+1.5,hall['origin_y']+.4,3)}
            {staff_badge(map_staff(state,building=hall['building_id']),hall['origin_x']+1.5,hall['origin_y']+2.8)}
            <title>Town Hall: {map_staff(state,building=hall['building_id'])} assigned citizens</title>
          </a>{map_additions(state)}</svg>'''
        created = datetime.fromtimestamp(state['settlement']['created_at'], timezone.utc).strftime('%d %b %Y · %H:%M UTC')
        clock_status = state['season']['status']
        clock_label = 'Time is running.' if clock_status in ('active', 'finalizing') else (
            'Season finished.' if clock_status == 'finished' else 'Time is paused.')
        action = 'pause' if clock_status in ('active', 'finalizing') else 'resume'
        action_label = 'Pause time' if action == 'pause' else 'Start time'
        empty = min(resources['food'], resources['water']) <= 0
        disabled = 'disabled' if clock_status == 'finished' or (empty and action == 'resume') else ''
        options = ''.join(f'<option value="{c["citizen_id"]}"'
                          + (' selected' if c['assignment'] == 'administrator' else '') + '>'
                          + escape(c['name']) + '</option>' for c in state['citizens']
                          if not c.get('away') and c['current_hp'] > 0 and c['assignment'] in ('administrator', 'unassigned'))
        balance_rows = ''.join(f'<tr data-resource-rate="{key}"><th scope="row">{key.title()}</th>'
                               f'<td>+{rate["production"]:.2f}</td><td>−{rate["consumption"]:.2f}</td>'
                               f'<td>{rate["net"]:+.2f}</td><td id="remaining-{key}">'
                               + (f'{rate["hours_to_empty"]:.1f} hours' if rate['hours_to_empty'] is not None else 'Stable')
                               + '</td></tr>' for key, rate in rates.items())
        alerts = f'<p class="error" role="alert">{escape(error)}</p>' if error else ''
        if empty:
            alerts += ('<p class="error" role="status">Stored supplies are depleted. Check rations and production; shortage health consequences are active.</p>' if state.get('needs_clock') is not None else '<p class="error" role="status">Supplies depleted. The prototype is paused before health consequences; enable supply consequences to continue with recovery controls.</p>')
        placement, hall_controls, food_cards = panels(state, token)
        content = template('settlement.html', name=escape(title), supplies=supplies, map=map_svg,
                           population=len(state['citizens']), housing=hall_config['housing'],
                           citizens=citizens, hp=f'{hall["current_hp"]:g}', max_hp=hall_config['hp'],
                           created=created, food_storage=hall_config['food_storage'],
                           water_storage=hall_config['water_storage'], material_storage=hall_config['material_storage'],
                           materials=f'{sum(resources[k] for k in ("scrap", "metal", "electronics")):g}',
                           clock_status=clock_status, clock_label=clock_label, clock_action=action,
                           clock_action_label=action_label, disabled=disabled, token=escape(token, quote=True),
                           options=options, balance_rows=balance_rows, alerts=alerts,
                           staff_disabled='disabled' if clock_status == 'finished' else '',
                           hall_level=hall['level'], placement=placement, hall_controls=hall_controls,
                           food_cards=food_cards, revision=live_payload(state)['revision'],
                           housing_summary=(f'<section class="production-panel" aria-label="Housing"><div class="building-controls"><h2>Housing</h2><p>{len(state["citizens"])} citizens / {homes["capacity"]} usable housing places · {homes["homeless"]} homeless.</p><p>Safe housing is assigned automatically by Level, XP, then settlement seniority. Higher-quality housing goes first. Capacity depends on condition and Oxygen; electricity is optional.</p><p class="small-note">Housing comfort bonuses and ongoing homelessness health loss are not active yet. Becoming homeless applies the workbook’s immediate morale penalty.</p></div></section>' if homes else ''),
                           total_food_storage=f'{rates["food"]["capacity"]:g}',
                           utility_radius=f'{spec(state,hall)["radius"]:g}',
                           electricity=f'{spec(state,hall)["electricity_output"]:g}',
                           oxygen=f'{spec(state,hall)["oxygen_output"]:g}')
        content=content.replace('<section class="resources"',f'<section class="resources" data-settlement="{state["settlement"]["settlement_id"]}"',1)
        if config['version'] in ('prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
            from game.progression_views import panel as progression_panel
            content+=progression_panel(state)
        if config['version'] in ('prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
            from game.recovery import eligibility
            reasons=eligibility(state)
            from game.support import healing_rates
            healing=healing_rates(state)
            recovery_rows=''.join('<tr><th scope="row">'+escape(c['name'])+'</th>'
                +f'<td>{c["current_hp"]:.2f} / {c["max_hp"]:g} HP</td><td>'
                +escape(reasons[c['citizen_id']] or ('Ready to recover when time starts' if clock_status=='paused' else f"+{healing[c['citizen_id']]:.2f} HP/hour"))+'</td></tr>'
                for c in state['citizens'])
            content=content.replace('Housing comfort bonuses and ongoing homelessness health loss are not active yet.','Housing morale modifiers and powered comfort are active. Ongoing homelessness health loss is not active yet.')
            content+='<section class="production-panel" aria-label="Citizen recovery"><div class="building-controls"><h2>Citizen recovery</h2><p>Injured citizens recover with accessible Food, Water, and safe housing. Housing morale affects productivity while occupied; it does not accumulate. Healing pauses with settlement time.</p><p class="small-note">Health updates once per simulated minute. Medical care is available after enabling support and defense. Births and ongoing homelessness damage remain deferred.</p></div><div class="table-scroll"><table><caption class="sr-only">Citizen recovery status</caption><thead><tr><th>Citizen</th><th>Health</th><th>Recovery</th></tr></thead><tbody>'+recovery_rows+'</tbody></table></div></section>'
    if state:
        from game.needs import panel as needs_panel
        from game.manufacturing import panel as military_panel
        from game.support import panel as support_panel
        from game.maintenance import panel as maintenance_panel
        content+=needs_panel(state,token)+military_panel(state,token)+support_panel(state,token)+maintenance_panel(state,token)
        from game.structural import panel as structural_panel
        from game.ruins import panel as ruin_panel
        from game.consequences import panel as citizen_panel
        content+=structural_panel(state,token)+ruin_panel(state,token)+citizen_panel(state,token)
        if 'structural' in state['config']:
            content=content.replace('Missiles and interceptors await later increments.','Missiles can join attacks; interceptors defend automatically from operational batteries.')
        if 'consequences' in state['config']:
            content=content.replace('Ongoing homelessness health loss is not active yet.','Homelessness health loss begins after 12 hours.').replace('Births and ongoing homelessness damage remain deferred.','Births and ongoing homelessness damage are enabled.')
    return template('base.html', title=escape(title), status=status, content=content).encode('utf-8')
