"""Read-only catalogue/progression audit; uses only Python's standard library.

Run python audit_buildings.py --output building-audit.json to save its evidence.
This checks configuration contracts, not multi-week gameplay balance.
"""
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def audit():
 config=json.loads((ROOT/'config/prototype_v13.json').read_text(encoding='utf-8'))
 expansion=json.loads((ROOT/'config/expansion_v1.json').read_text(encoding='utf-8'))
 catalog=config['buildings'];catalog.update(expansion['buildings'])
 renewable=expansion.get('renewable_scrap')
 if renewable:
  for level,rate in zip(catalog[renewable['building']]['levels'],renewable['output_per_worker_hour']):level['scrap_output']=rate
 errors=[];levels=[]
 for kind,building in catalog.items():
  if len(building['levels'])!=building['max_level']:errors.append(f'{kind}: missing level')
  if building['unlock'] not in (1,2,3):errors.append(f'{kind}: invalid Town Hall unlock')
  for number,level in enumerate(building['levels'],1):
   if level['workers']<building['workers_min']:errors.append(f'{kind} L{number}: impossible staffing')
   if level['hp']<=0 or any(level[r]<0 for r in ('scrap','metal','electronics')):errors.append(f'{kind} L{number}: invalid HP/cost')
   levels.append({'building':kind,'level':number,'town_hall_unlock':building['unlock'],'materials':{r:level[r] for r in ('scrap','metal','electronics')},'total_cost':sum(level[r] for r in ('scrap','metal','electronics')),'workers_min':building['workers_min'],'workers_max':level['workers'],'output_per_effective_worker_hour':{r:level.get(key,0) for r,key in [('food','food'),('water','water'),('scrap','scrap_output'),('metal','metal_output'),('electronics','electronics_output')]},'oxygen':level['oxygen_demand'],'electricity':level['electricity_demand']})
 for resource,output,input_unlock in [('scrap','scrap_output',1),('metal','metal_output',2),('electronics','electronics_output',3)]:
  if not any(b['unlock']<=input_unlock and any(l.get(output,0)>0 for l in b['levels']) for b in catalog.values()):errors.append(f'{resource}: no renewable producer by Town Hall {input_unlock}')
 for unit,recipe in config['units'].items():
  if recipe['factory'] not in catalog or recipe['storage'] not in catalog:errors.append(f'{unit}: missing factory/storage')
 hall=catalog['town_hall']['levels'];yard=catalog['scrap_yard']['levels'][0]['material_storage'];warehouse=catalog['warehouse']['levels'][0]['material_storage']
 storage_paths=[{'target_town_hall':2,'cost':sum(hall[1][r] for r in ('scrap','metal','electronics')),'capacity':hall[0]['material_storage']+yard,'path':'Town Hall 1 + Scrap Yard'}, {'target_town_hall':3,'cost':sum(hall[2][r] for r in ('scrap','metal','electronics')),'capacity':hall[1]['material_storage']+warehouse,'path':'Town Hall 2 + Warehouse 1'}]
 for path in storage_paths:
  if path['cost']>path['capacity']:errors.append(f"{path['path']}: upgrade exceeds storage")
 return {'buildings':len(catalog),'levels':len(levels),'upgrades':len(levels)-len(catalog),'errors':errors,'storage_paths':storage_paths,'renewable_scrap':renewable,'all_level_1_costs':{r:sum(b['levels'][0][r] for b in catalog.values()) for r in ('scrap','metal','electronics')},'all_sequential_level_costs':{r:sum(l[r] for b in catalog.values() for l in b['levels']) for r in ('scrap','metal','electronics')},'levels_detail':levels}

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args();report=audit()
 print(f"{report['buildings']} buildings, {report['levels']} levels, {report['upgrades']} upgrades; {len(report['errors'])} configuration errors")
 for path in report['storage_paths']:print(f"{path['path']}: {path['cost']:g} cost / {path['capacity']:g} capacity")
 for error in report['errors']:print('ERROR:',error)
 if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 return int(bool(report['errors']))
if __name__=='__main__':raise SystemExit(main())
