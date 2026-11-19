"""合账引擎离线自检：python -I scripts/verify_merge.py（无需数据库/Redis）。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.merge_engine import build_verdict, MergeError

INITIAL = {'sample_A': 100, 'sample_B': 50}
LATE = [
    {'op': 'begin', 'tx': 'T1'}, {'op': 'write', 'tx': 'T1', 'key': 'sample_A', 'value': 75},
    {'op': 'commit', 'tx': 'T1'}, {'op': 'checkpoint'},
    {'op': 'begin', 'tx': 'T2'}, {'op': 'write', 'tx': 'T2', 'key': 'sample_B', 'value': 40},
    {'op': 'begin', 'tx': 'T3'}, {'op': 'write', 'tx': 'T3', 'key': 'sample_A', 'value': 60},
    {'op': 'commit', 'tx': 'T3'},
    {'op': 'write', 'tx': 'T2', 'key': 'sample_B', 'value': 35}, {'op': 'commit', 'tx': 'T2'},
]
EARLY = [
    {'op': 'begin', 'tx': 'E1'}, {'op': 'write', 'tx': 'E1', 'key': 'sample_A', 'value': 88},
    {'op': 'commit', 'tx': 'E1'},
    {'op': 'begin', 'tx': 'E2'}, {'op': 'write', 'tx': 'E2', 'key': 'sample_A', 'value': 82},
    {'op': 'commit', 'tx': 'E2'},
    {'op': 'begin', 'tx': 'E3'}, {'op': 'write', 'tx': 'E3', 'key': 'sample_B', 'value': 30},
]


def side(tag, log_set_id, name, initial, records, crash_after):
    return {'log_set_id': log_set_id, 'name': name, 'initial': initial,
            'records': records, 'crash_after': crash_after}


def decision_map(v):
    return {d['ref']: d for d in v['decisions']}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print('  ok -', msg)


print('1. 底账不同拒绝合账')
try:
    build_verdict(side('A', 1, 'a', {'x': 1}, [{'op': 'begin', 'tx': 't1'}, {'op': 'write', 'tx': 't1', 'key': 'x', 'value': 2}, {'op': 'commit', 'tx': 't1'}], 3),
                  side('B', 2, 'b', {'x': 2}, [{'op': 'begin', 'tx': 't2'}, {'op': 'write', 'tx': 't2', 'key': 'x', 'value': 3}, {'op': 'commit', 'tx': 't2'}], 3), [])
    raise AssertionError('应拒绝底账不同')
except MergeError as exc:
    check('底账' in str(exc), str(exc))

print('2. 仅收断电点前已提交整笔；未提交/abort带舍弃原因')
v = build_verdict(side('A', 1, '早班', INITIAL, EARLY, 7),
                  side('B', 2, '晚班', INITIAL, LATE, 10), [])
refs = {d['ref']: d for d in v['decisions']}
check(set(refs) == {'A:E1', 'A:E2', 'B:T1', 'B:T3'}, '已提交事务集合为 E1/E2/T1/T3（E3未提交、T2未提交均不入裁决）')
check(any(d['tx'] == 'E3' and '未提交' in d['reason'] for d in v['discarded']), 'E3 标记为断电前未提交舍弃')
check(decision_map(v)['B:T3']['commit_lsn'] == 9, '保留原提交 LSN 信息')

print('3. 跨班同键冲突点输出')
check([c['key'] for c in v['conflicts']] == ['sample_A'], 'sample_A 为唯一跨班冲突键')
point_refs = {p['ref'] for p in v['conflicts'][0]['points']}
check(point_refs == {'A:E1', 'A:E2', 'B:T1', 'B:T3'}, '冲突点列出两侧全部写者及写入LSN')

print('4. 无指定时最大独立集尽量多留（左侧2节点 vs 右侧2节点团冲突，保留2）')
kept = {r for r, d in refs.items() if d['kept']}
check(len(kept) == 2, f'最大留存2笔，实际 {sorted(kept)}')
dropped = [d for d in v['decisions'] if not d['kept']]
check(all(d['reason'] and '冲突裁决舍弃' in d['reason'] for d in dropped), '被舍弃事务均带冲突裁决原因')
check(v['stats']['kept'] == 2 and v['stats']['dropped_committed'] == 2, '统计字段一致')

print('5. 指定保留事务生效，其余尽量多留')
v2 = build_verdict(side('A', 1, '早班', INITIAL, EARLY, 7),
                   side('B', 2, '晚班', INITIAL, LATE, 10), ['B:T1'])
m2 = decision_map(v2)
check(m2['B:T1']['kept'] and not m2['A:E1']['kept'] and not m2['A:E2']['kept'], '指定保住 B:T1，A班两笔强制舍弃')
check('指定保留事务 B:T1' in m2['A:E1']['reason'], '强制舍弃原因指明保住的事务')

print('6. 指定事务互斥时指出冲突点')
try:
    build_verdict(side('A', 1, '早班', INITIAL, EARLY, 7),
                  side('B', 2, '晚班', INITIAL, LATE, 10), ['A:E1', 'B:T1'])
    raise AssertionError('应拒绝互斥指定')
except MergeError as exc:
    check('互斥' in str(exc) and 'sample_A' in str(exc) and 'LSN' in str(exc), str(exc))

print('7. 同班原提交顺序重放，新日志可再次演练，账本与裁决一致')
order = v['replay_order']
check(order == sorted(order, key=lambda r: (r[0], refs[r]['commit_lsn'])), '重放顺序按班、按原提交LSN')
from src.services.wal_engine import validate, recover
validate(v['initial'], v['merged_records'])
rec = recover(v['initial'], v['merged_records'], len(v['merged_records']))
check(rec['recovered'] == v['merged_ledger'], '新日志完整重放账本与合账裁决账本一致')
check(rec['invariant_passed'], '新日志通过独立 oracle 不变式，可再次演练')
check(all(r['tx'].startswith('M') for r in v['merged_records']), '新日志事务ID顺序重命名，避免跨班复用')

print('8. 裁决确定性与幂等：相同输入 verdict_key 不变')
v_again = build_verdict(side('A', 1, '早班', INITIAL, EARLY, 7),
                        side('B', 2, '晚班', INITIAL, LATE, 10), [])
check(v_again['verdict_key'] == v['verdict_key'], '相同输入与裁决生成相同 verdict_key')
v_tweak = build_verdict(side('A', 1, '早班', INITIAL, EARLY, 6),
                        side('B', 2, '晚班', INITIAL, LATE, 10), [])
check(v_tweak['verdict_key'] != v['verdict_key'], '断电点变化导致裁决键变化')

print('9. abort 事务不计入合账')
abort_logs = [{'op': 'begin', 'tx': 'X1'}, {'op': 'write', 'tx': 'X1', 'key': 'sample_A', 'value': 9},
              {'op': 'abort', 'tx': 'X1'}]
v3 = build_verdict(side('A', 3, 'x', INITIAL, abort_logs, 3),
                   side('B', 2, '晚班', INITIAL, LATE, 11), [])
check(all(d['side'] != 'A' for d in v3['decisions']), 'A班仅abort事务，不进入裁决')
check(any(d['tx'] == 'X1' and 'abort' in d['reason'] for d in v3['discarded']), 'abort 舍弃原因可见')

print('10. 无冲突路径全部保留，且无重复键写入')
initial3 = {'sample_A': 100, 'sample_B': 50, 'sample_C': 5}
clean = [{'op': 'begin', 'tx': 'C1'}, {'op': 'write', 'tx': 'C1', 'key': 'sample_C', 'value': 11},
         {'op': 'commit', 'tx': 'C1'}]
late3 = [dict(r) for r in LATE]
v4 = build_verdict(side('A', 4, 'c', initial3, clean, 3),
                   side('B', 2, '晚班', initial3, late3, 11), [])
check(all(d['kept'] for d in v4['decisions']), '无跨班冲突时全部已提交事务保留')
check(v4['merged_ledger'] == {'sample_A': 60, 'sample_B': 35, 'sample_C': 11}, '合账账本为两侧提交净效果')

print('\n全部合账引擎自检通过。')
