"""merge_service 幂等与校验流程自检（标准库，无需第三方依赖）。
python -I /workspace/backend/scripts/verify_merge_service.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 桩件目录优先，提供 sqlalchemy/fastapi/pydantic 与配置模块的最小实现；业务代码仍取自 backend/src。
sys.path.insert(0, str(ROOT / 'scripts' / '_stubs'))
sys.path.insert(1, str(ROOT))

from types import SimpleNamespace
from src.services import merge_service
from src.models.entities import LogSet, MergeJob


def side(log_set_id, crash_after):
    return SimpleNamespace(log_set_id=log_set_id, crash_after=crash_after)


def payload(a, b, pinned, verdict_key=None, label=None, new_log_set_name=None):
    data = {'side_a': side(*a), 'side_b': side(*b), 'pinned': pinned}
    if verdict_key is not None:
        data.update(verdict_key=verdict_key, label=label,
                    new_log_set_name=new_log_set_name, description='d')
    return SimpleNamespace(**data)

INITIAL = {'sample_A': 100, 'sample_B': 50}
LATE = [
    {'op': 'begin', 'tx': 'T1'}, {'op': 'write', 'tx': 'T1', 'key': 'sample_A', 'value': 75},
    {'op': 'commit', 'tx': 'T1'},
    {'op': 'begin', 'tx': 'T3'}, {'op': 'write', 'tx': 'T3', 'key': 'sample_A', 'value': 60},
    {'op': 'commit', 'tx': 'T3'},
]
EARLY = [
    {'op': 'begin', 'tx': 'E1'}, {'op': 'write', 'tx': 'E1', 'key': 'sample_A', 'value': 88},
    {'op': 'commit', 'tx': 'E1'},
    {'op': 'begin', 'tx': 'E3'}, {'op': 'write', 'tx': 'E3', 'key': 'sample_B', 'value': 30},
]


class FakeDB:
    def __init__(self):
        LogSet._columns = ['id', 'name', 'initial', 'records', 'description']
        MergeJob._columns = ['id', 'label', 'status', 'verdict_key', 'snapshot',
                             'verdict', 'new_log_set_id', 'created_at']
        self.logs = {
            1: LogSet(id=1, name='早班', initial=INITIAL, records=EARLY, description=''),
            2: LogSet(id=2, name='晚班', initial=INITIAL, records=LATE, description=''),
            3: LogSet(id=3, name='异底账', initial={'sample_A': 1}, records=LATE, description=''),
        }
        self.jobs = {}
        self._id = 0
        self._logid = 100

    def get(self, model, ident):
        if model is LogSet:
            return self.logs.get(ident)
        if model is MergeJob:
            return self.jobs.get(ident)
        raise KeyError(model)

    def scalar(self, stmt):
        # 解析桩件产生的 ('eq', 列名, 值) 过滤标记。
        filters = {name: value for kind, name, value in stmt.filters if kind == 'eq'}
        if stmt.entities and stmt.entities[0] is MergeJob:
            key = filters.get('verdict_key')
            if key is not None:
                return next((j for j in self.jobs.values() if j.verdict_key == key), None)
            return next(iter(self.jobs.values()), None)
        if stmt.entities and stmt.entities[0] is LogSet:
            name = filters.get('name')
            return next((l for l in self.logs.values() if getattr(l, 'name', None) == name), None)
        return None

    def add(self, obj):
        if isinstance(obj, LogSet):
            obj.id = self._logid
            self._logid += 1
            self.logs[obj.id] = obj
        elif isinstance(obj, MergeJob):
            self._id += 1
            obj.id = self._id
            self.jobs[obj.id] = obj

    def flush(self):
        pass

    def rollback(self):
        pass


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print('  ok -', msg)


db = FakeDB()
preview_data = payload((1, 4), (2, 6), [])
v = merge_service.preview_merge(db, preview_data)
check(v['stats']['committed'] == 3 and v['stats']['kept'] == 2, '预览：3笔已提交，最大留存2笔')
check(len(v['merged_records']) == 6, '2笔保留事务生成 begin/write/commit 共6条新日志')

print('1. 首次合账生成新日志与裁决记录')
commit_data = payload((1, 4), (2, 6), [], verdict_key=v['verdict_key'],
                      label='两班合账核对', new_log_set_name='merged-1')
job, reused = merge_service.commit_merge(db, commit_data)
check(not reused and job['new_log_set_id'] in db.logs, '首次合账创建新日志集')
check(db.logs[job['new_log_set_id']].records == v['merged_records'], '新日志内容与裁决一致')
check(db.logs[1].records == EARLY and db.logs[2].records == LATE, '原日志保持不变')

print('2. 结果没收到时重试：沿用预览裁决，不重复生成')
before = set(db.logs)
job2, reused2 = merge_service.commit_merge(db, commit_data)
check(reused2 and job2['id'] == job['id'], '重试返回同一条合账记录')
check(set(db.logs) == before, '没有重复生成新日志集')

print('3. 裁决键与当前输入不符时拒绝（伪造一个64位键，且无既有记录可复用）')
from fastapi import HTTPException
fake_key = 'f' * 64
bad = payload((1, 4), (2, 6), ['A:E1'], verdict_key=fake_key,
              label='x', new_log_set_name='merged-bad')
try:
    merge_service.commit_merge(db, bad)
    raise AssertionError('应拒绝键不符')
except HTTPException as exc:
    check(exc.status_code == 422 and '不一致' in exc.detail, str(exc.detail))

print('4. 底账不同拒绝合账')
diff = payload((1, 4), (3, 6), [])
try:
    merge_service.preview_merge(db, diff)
    raise AssertionError('应拒绝异底账')
except HTTPException as exc:
    check(exc.status_code == 422 and '底账' in exc.detail, str(exc.detail))

print('5. 互斥指定带冲突点拒绝')
mutex = payload((1, 4), (2, 6), ['A:E1', 'B:T1'])
try:
    merge_service.preview_merge(db, mutex)
    raise AssertionError('应拒绝互斥')
except HTTPException as exc:
    check(exc.status_code == 422 and '互斥' in exc.detail and 'sample_A' in exc.detail, str(exc.detail))

print('6. 断电点超界与缺失日志的 4xx')
over = payload((1, 99), (2, 6), [])
try:
    merge_service.preview_merge(db, over)
    raise AssertionError('应拒绝超界')
except HTTPException as exc:
    check(exc.status_code == 422, str(exc.detail))
missing = payload((99, 1), (2, 6), [])
try:
    merge_service.preview_merge(db, missing)
    raise AssertionError('应 404')
except HTTPException as exc:
    check(exc.status_code == 404, str(exc.detail))

print('\n合账服务层自检全部通过。')
