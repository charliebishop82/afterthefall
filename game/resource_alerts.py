"""Read-only resource guidance based on the current plan, not new game rules."""
from html import escape

MATERIALS = ('scrap','metal','electronics')


def alerts(state, rates):
    result=[]
    running=state['season']['status'] in ('active','finalizing') and state['settlement']['status']=='active'
    prefix='' if running else 'When play resumes: '
    def add(key,severity,resources,message,link,label):
        result.append(dict(key=key,severity=severity,resources=list(resources),
                           message=prefix+message,link=link,label=label))
    for resource in ('food','water')+MATERIALS:
        rate=rates.get(resource)
        if not rate: continue
        stock=state['resources'][resource];net=rate['net'];name=resource.title()
        hours=rate.get('hours_to_empty')
        if resource in ('food','water') and stock<=1e-8:
            add(resource+'-empty','critical',[resource],
                f'{name} is empty. Increase production or obtain supplies; review rations.',
                '#needs','Review supplies & rations')
        elif net<0 and hours is not None and hours<=2:
            add(resource+'-low','warning',[resource],
                f'{name} may run out in {hours:.1f} hours at current rates. '+
                ('Increase production or review rations.' if resource in ('food','water') else 'Produce or trade for inputs; reduce dependent manufacturing if needed.'),
                '#screen-build','Review production')
        if resource not in ('food','water'): continue
        cap=rate['capacity']
        if net>1e-8:
            if stock>=cap-1e-8:
                add(resource+'-overflow','warning',[resource],
                    f'{name} storage is full. About {net:.1f}/hour of surplus may be discarded. Add storage, trade supplies or reduce output.',
                    '#construction','Build storage / manage output')
            elif cap>0:
                fill=(cap-stock)/net
                if fill<=1 or stock>=.9*cap:
                    add(resource+'-filling','notice',[resource],
                        f'{name} storage is {stock/cap:.0%} full; may fill in {fill:.1f} hours. Add storage or trade the surplus.',
                        '#construction','Review storage')
    material_rates=[rates[r] for r in MATERIALS if r in rates]
    if material_rates:
        stock=sum(state['resources'][r] for r in MATERIALS)
        cap=material_rates[0]['capacity'];net=sum(r['net'] for r in material_rates)
        if stock>=cap-1e-8 and (stock>0 or net>1e-8):
            add('materials-full','warning',MATERIALS,
                'Shared Scrap, Metal and Electronics storage is full. Production may pause; incoming scavenged materials may be discarded. Add storage, use or trade materials, or reduce scavenging.',
                '#scavenging','Review crews / build storage')
        elif cap>0 and net>1e-8:
            fill=(cap-stock)/net
            if fill<=1 or stock>=.9*cap:
                add('materials-filling','notice',MATERIALS,
                    f'Shared material storage is {stock/cap:.0%} full; may fill in {fill:.1f} hours. Scrap, Metal and Electronics share this space.',
                    '#construction','Review storage')
    # Credits have no storage cap; do not invent one or warn about harmless stock.
    order={'critical':0,'warning':1,'notice':2}
    return sorted(result,key=lambda row:order[row['severity']])


def panel(rows):
    items=''.join(f'<li class="attention-{row["severity"]}"><strong>{escape(row["message"])}</strong> '
                  f'<a href="{escape(row["link"],quote=True)}">{escape(row["label"])}</a></li>' for row in rows)
    return ('<section class="production-panel" id="attention"><h2>Needs attention</h2>'
            '<p class="small-note">Estimates use current staffing and rates. Storage limits and consumption can change; paused plans are labelled.</p>'
            '<ul id="resource-alert-list">'+items+'</ul><p id="resource-alert-empty"'+(' hidden' if rows else '')+
            '>No resource storage or imminent-shortage warnings at current rates.</p></section>')
