"""Two-shift offline log merge engine.

只合入两班日志断电点前已完整提交的整笔事务；同班按原提交顺序重放；
跨班写入同一个账本键即构成冲突，值班员可指定必须保住的事务，其余事务
在二分冲突图上求最大独立集，尽量多留。输出可复核的裁决（含每笔事务
的舍弃原因与冲突点）以及一份可再次演练的新日志。
"""
import copy
import hashlib
import json

from src.services.wal_engine import validate

MODEL_VERSION = 'two-shift-log-merge-v1'
MAX_RECORDS = 200


class MergeError(ValueError):
    """合账前置条件不满足或裁决无法成立。"""


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _sha256(obj):
    return hashlib.sha256(_canon(obj).encode()).hexdigest()


def _committed_side(side_tag, initial, records, crash_after):
    """返回（已提交事务列表，断电点前未合入事务列表）。"""
    validate(initial, records)
    if type(crash_after) is not int or not 0 <= crash_after <= len(records):
        raise MergeError(f'{side_tag}班断电点超出日志范围（0—{len(records)}）')
    txs = {}
    order = []
    for lsn, r in enumerate(records[:crash_after], 1):
        op = r['op']
        tx = r.get('tx')
        if op == 'checkpoint':
            continue
        if op == 'begin':
            txs[tx] = {'ref': f'{side_tag}:{tx}', 'side': side_tag, 'tx': tx,
                       'writes': [], 'state': 'active', 'commit_lsn': None}
            order.append(tx)
        elif op == 'write':
            txs[tx]['writes'].append({'lsn': lsn, 'key': r['key'], 'value': r['value']})
        elif op == 'commit':
            txs[tx]['state'] = 'committed'
            txs[tx]['commit_lsn'] = lsn
        elif op == 'abort':
            txs[tx]['state'] = 'aborted'
    committed = [txs[t] for t in order if txs[t]['state'] == 'committed']
    discarded = []
    for t in order:
        if txs[t]['state'] == 'committed':
            continue
        reason = ('事务已abort，写入已撤销，不属于已提交事务'
                  if txs[t]['state'] == 'aborted'
                  else f'断电点（前{crash_after}条）前未提交，整笔事务不合账')
        discarded.append({'ref': f'{side_tag}:{t}', 'side': side_tag, 'tx': t,
                          'reason': reason})
    return committed, discarded


def _max_independent_set(left, right, adj):
    """二分图最大独立集（Kuhn 最大匹配 + Kőnig 最小点覆盖），顶点有序保证结果确定。"""
    match_b = {}

    def augment(a_ref, seen):
        for b_ref in adj[a_ref]:
            if b_ref in seen:
                continue
            seen.add(b_ref)
            if b_ref not in match_b or augment(match_b[b_ref], seen):
                match_b[b_ref] = a_ref
                return True
        return False

    for a_ref in left:
        augment(a_ref, set())
    matched_a = set(match_b.values())
    # 从左侧未匹配点出发，沿非匹配边到B、再沿匹配边回A，标记可达点。
    reach_a = {a_ref for a_ref in left if a_ref not in matched_a}
    reach_b = set()
    stack = list(reach_a)
    while stack:
        a_ref = stack.pop()
        for b_ref in adj[a_ref]:
            if match_b.get(b_ref) == a_ref or b_ref in reach_b:
                continue
            reach_b.add(b_ref)
            back = match_b.get(b_ref)
            if back and back not in reach_a:
                reach_a.add(back)
                stack.append(back)
    cover = {a_ref for a_ref in left if a_ref not in reach_a} | set(reach_b)
    independent = [v for v in left + right if v not in cover]
    return sorted(independent), sorted(cover), match_b


def build_verdict(side_a, side_b, pinned):
    """构造合账预览裁决。side_* 为含 log_set_id/name/initial/records/crash_after 的字典。"""
    if side_a['initial'] != side_b['initial']:
        raise MergeError('两份日志底账（初始账本）不同，拒绝合账')
    initial = copy.deepcopy(side_a['initial'])
    a_committed, a_discarded = _committed_side('A', side_a['initial'], side_a['records'], side_a['crash_after'])
    b_committed, b_discarded = _committed_side('B', side_b['initial'], side_b['records'], side_b['crash_after'])
    nodes = {t['ref']: t for t in a_committed + b_committed}
    keys_of = {ref: {w['key'] for w in t['writes']} for ref, t in nodes.items()}

    pin_set = sorted(set(pinned))
    unknown = [r for r in pin_set if r not in nodes]
    if unknown:
        raise MergeError('指定保留的事务不在断电点前已提交范围内：' + '、'.join(unknown))

    # 跨班冲突：两侧已提交事务写过同一个账本键。
    a_refs = [t['ref'] for t in a_committed]
    b_refs = [t['ref'] for t in b_committed]
    adj = {ref: [] for ref in a_refs}
    conflicts = []
    for key in sorted(initial):
        writers_a = [r for r in a_refs if key in keys_of[r]]
        writers_b = [r for r in b_refs if key in keys_of[r]]
        if not writers_a or not writers_b:
            continue
        for ar in writers_a:
            adj[ar].extend(r for r in writers_b if r not in adj[ar])
        points = []
        for ref in sorted(writers_a + writers_b):
            w = next(x for x in nodes[ref]['writes'] if x['key'] == key)
            points.append({'ref': ref, 'write_lsn': w['lsn'],
                           'commit_lsn': nodes[ref]['commit_lsn']})
        conflicts.append({'key': key, 'refs': sorted(writers_a + writers_b), 'points': points})
    for ref in adj:
        adj[ref].sort()

    # 指定保留的事务互斥：明确指出冲突键与两侧 LSN 冲突点。
    mutex_msgs = []
    for c in conflicts:
        pa = [r for r in c['refs'] if r in pin_set and r.startswith('A:')]
        pb = [r for r in c['refs'] if r in pin_set and r.startswith('B:')]
        if pa and pb:
            lsn_text = '、'.join(f"{p['ref']}写入LSN {p['write_lsn']}" for p in c['points'])
            mutex_msgs.append(f"{ '、'.join(pa) } 与 { '、'.join(pb) } 同时写键 {c['key']}（{lsn_text}）")
    if mutex_msgs:
        raise MergeError('指定保留的事务互斥，冲突点：' + '；'.join(mutex_msgs))

    kept = set(pin_set)
    drop_reason = {}
    # 与指定保留事务争键的事务强制舍弃。
    for ref in sorted(nodes):
        if ref in kept:
            continue
        blockers = sorted(p for p in pin_set if keys_of[ref] & keys_of[p])
        if blockers:
            shared = sorted(keys_of[ref] & set().union(*(keys_of[p] for p in blockers)))
            drop_reason[ref] = f"与指定保留事务 {'、'.join(blockers)} 冲突（键 {'、'.join(shared)}）"

    # 剩余冲突图求最大独立集，尽量多留。
    rest_left = [r for r in a_refs if r not in kept and r not in drop_reason]
    rest_right = [r for r in b_refs if r not in kept and r not in drop_reason]
    rest_adj = {r: [b for b in adj.get(r, []) if b in rest_right] for r in rest_left}
    independent, cover, _match = _max_independent_set(rest_left, rest_right, rest_adj)
    for ref in independent:
        kept.add(ref)
    for ref in cover:
        rivals = sorted(v for v in nodes if v in kept and keys_of[ref] & keys_of[v])
        shared = sorted(keys_of[ref] & set().union(*(keys_of[v] for v in rivals))) if rivals else sorted(keys_of[ref])
        tail = f"，裁决保留 {'、'.join(rivals)} 以留存更多整笔事务" if rivals else ''
        drop_reason[ref] = f"跨班写同键 {'、'.join(shared)} 冲突裁决舍弃{tail}"

    decisions = []
    for ref in a_refs + b_refs:
        t = nodes[ref]
        decisions.append({'ref': ref, 'side': t['side'], 'tx': t['tx'],
                          'commit_lsn': t['commit_lsn'],
                          'keys': sorted(keys_of[ref]), 'write_count': len(t['writes']),
                          'kept': ref in kept, 'reason': None if ref in kept else drop_reason.get(ref)})

    # 同班按原提交顺序，A班先于B班，整笔重放；事务ID在新日志内顺序重命名避免跨班复用。
    ordered_kept = [r for r in a_refs + b_refs if r in kept]
    if not ordered_kept:
        raise MergeError('没有可合账的断电点前已提交事务，无法生成新日志')
    rename = {}
    merged_records = []
    for idx, ref in enumerate(ordered_kept, 1):
        new_tx = f'M{idx}'
        rename[ref] = new_tx
        merged_records.append({'op': 'begin', 'tx': new_tx})
        for w in nodes[ref]['writes']:
            merged_records.append({'op': 'write', 'tx': new_tx, 'key': w['key'], 'value': w['value']})
        merged_records.append({'op': 'commit', 'tx': new_tx})
    if len(merged_records) > MAX_RECORDS:
        raise MergeError(f'合账后日志 {len(merged_records)} 条，超过 {MAX_RECORDS} 条上限，请缩小合账范围')
    validate(initial, merged_records)

    merged_ledger = copy.deepcopy(initial)
    for r in merged_records:
        if r['op'] == 'write':
            merged_ledger[r['key']] = r['value']

    content_sha_a = _sha256({'initial': side_a['initial'], 'records': side_a['records']})
    content_sha_b = _sha256({'initial': side_b['initial'], 'records': side_b['records']})
    verdict_key = _sha256({
        'model_version': MODEL_VERSION,
        'initial': initial,
        'sides': [
            {'log_set_id': side_a['log_set_id'], 'crash_after': side_a['crash_after'], 'content_sha256': content_sha_a},
            {'log_set_id': side_b['log_set_id'], 'crash_after': side_b['crash_after'], 'content_sha256': content_sha_b},
        ],
        'pinned': pin_set,
        'kept': sorted(kept),
        'merged_records': merged_records,
    })

    return {
        'simulation': True,
        'model_version': MODEL_VERSION,
        'verdict_key': verdict_key,
        'initial_match': True,
        'initial': initial,
        'pinned': pin_set,
        'sides': [
            {'side': 'A', 'log_set_id': side_a['log_set_id'], 'name': side_a['name'],
             'crash_after': side_a['crash_after'], 'record_count': len(side_a['records']),
             'content_sha256': content_sha_a},
            {'side': 'B', 'log_set_id': side_b['log_set_id'], 'name': side_b['name'],
             'crash_after': side_b['crash_after'], 'record_count': len(side_b['records']),
             'content_sha256': content_sha_b},
        ],
        'conflicts': conflicts,
        'decisions': decisions,
        'discarded': a_discarded + b_discarded,
        'replay_order': ordered_kept,
        'tx_rename': rename,
        'merged_records': merged_records,
        'merged_ledger': merged_ledger,
        'stats': {
            'committed': len(nodes),
            'kept': len(kept),
            'dropped_committed': len(nodes) - len(kept),
            'pre_crash_discarded': len(a_discarded) + len(b_discarded),
            'conflict_keys': len(conflicts),
            'merged_records': len(merged_records),
        },
        'result_sha256': _sha256({'merged_ledger': merged_ledger, 'merged_records': merged_records}),
        'input_sha256': _sha256({'side_a': content_sha_a, 'side_b': content_sha_b,
                                 'crash_a': side_a['crash_after'], 'crash_b': side_b['crash_after'],
                                 'pinned': pin_set}),
        'boundary': 'Python 两班离线补录合账教学模型：只接收断电点前已提交的整笔事务，同班按原提交顺序重放，'
                    '跨班同键写入按值班员裁决与最大留存原则取舍；不注入真实 PostgreSQL 故障，不执行数据库物理恢复。',
    }
