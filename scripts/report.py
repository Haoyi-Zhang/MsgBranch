"""Derive original-suite tables only from the recorded results."""
from pathlib import Path
import csv,json,statistics
ROOT=Path(__file__).resolve().parents[1]

def run():
    rows=json.loads((ROOT/'results/controls.json').read_text())
    fluent=json.loads((ROOT/'results/fluent-cases.json').read_text())
    out=ROOT/'results'
    with (out/'control-table.csv').open('w') as f:
        w=csv.writer(f);w.writerow(['format','case','category','ordinary','branch','call','native_catalog_alarm','selected','runs'])
        for r in rows:
            w.writerow(['gettext',r['id'],r['category'],int(r['ordinary_detects']),int(r['branch_only_detects']),int(r['call_aware_detects']),int(r['babel_alarm']),len(r['representatives']),r['domain_size']])
        for r in fluent:
            w.writerow(['Fluent',r['case'],r['category'],int(r['ordinary_detects']),int(r['branch_detects']),int(r['call_detects']),r['parse_errors'],r['selected'],r['runs']])
    performance={'gettext_planning_total_ms':sum(r['planner_ms'] for r in rows),
                 'gettext_selected_execution_family_median_ms':statistics.median(r['selected_execution_ms_median'] for r in rows),
                 'gettext_selected_execution_family_range_ms':[min(r['selected_execution_ms_median'] for r in rows),max(r['selected_execution_ms_median'] for r in rows)],
                 'fluent_full_traced_evaluation_ms':sum(r['wall_ms'] for r in fluent),
                 'note':'Different instrumentation and protocols; not a cross-format speed comparison. Planning enumerates the full finite domain. Selected execution medians use seven repeats.'}
    (out/'performance.json').write_text(json.dumps(performance,indent=2)+'\n')
    coverage={'gettext_known_families':sum(r['category']!='unknown' for r in rows),
              'gettext_unknown_families':sum(r['category']=='unknown' for r in rows),
              'gettext_legitimate_equality_supported':sum(r['placeholder_equality_alarm'] is not None for r in rows if r['category']=='legitimate'),
              'gettext_legitimate_equality_false_alarms':sum(bool(r['placeholder_equality_alarm']) for r in rows if r['category']=='legitimate'),
              'gettext_known_representatives':sum(len(r['representatives']) for r in rows if r['category']!='unknown'),
              'fluent_recorded_selected':sum(r['selected'] for r in fluent),
              'note':'Representative counts are not defect counts. Fluent reductions are post-execution trace grouping, not predictive generation.'}
    (out/'coverage.json').write_text(json.dumps(coverage,indent=2)+'\n')
    print(json.dumps({'performance':performance,'coverage':coverage},indent=2))
if __name__=='__main__':run()
