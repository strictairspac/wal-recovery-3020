from sqlalchemy import select
from fastapi import HTTPException
from src.models.entities import LogSet, MergeJob
from src.services.merge_engine import build_verdict, MergeError
from src.utils.serialize import record


def _load_side(db, side, tag):
    logs = db.get(LogSet, side.log_set_id)
    if logs is None:
        raise HTTPException(404, f'{tag}班日志集不存在')
    if side.crash_after > len(logs.records):
        raise HTTPException(422, f'{tag}班断电点超过日志条数')
    return {'log_set_id': logs.id, 'name': logs.name, 'initial': logs.initial,
            'records': logs.records, 'crash_after': side.crash_after}


def _build(db, data):
    side_a = _load_side(db, data.side_a, 'A')
    side_b = _load_side(db, data.side_b, 'B')
    try:
        return build_verdict(side_a, side_b, data.pinned)
    except MergeError as exc:
        raise HTTPException(422, str(exc))


def preview_merge(db, data):
    return _build(db, data)


def commit_merge(db, data):
    # 先按预览中的裁决条件幂等查找：结果未收到时重试沿用同一裁决，不重复生成新日志。
    existing = db.scalar(select(MergeJob).where(MergeJob.verdict_key == data.verdict_key))
    if existing is not None:
        return record(existing), True
    verdict = _build(db, data)
    if verdict['verdict_key'] != data.verdict_key:
        raise HTTPException(422, '裁决已与预览不一致，请刷新预览后按最新裁决合账')
    if db.scalar(select(LogSet.id).where(LogSet.name == data.new_log_set_name)):
        raise HTTPException(409, '新日志集名称已存在，请换名后重试')
    new_logs = LogSet(name=data.new_log_set_name, initial=verdict['initial'],
                      records=verdict['merged_records'], description=data.description)
    db.add(new_logs)
    db.flush()
    snapshot = {
        'side_a': {'log_set_id': data.side_a.log_set_id, 'crash_after': data.side_a.crash_after},
        'side_b': {'log_set_id': data.side_b.log_set_id, 'crash_after': data.side_b.crash_after},
        'pinned': data.pinned,
    }
    job = MergeJob(label=data.label, status='completed', verdict_key=verdict['verdict_key'],
                   snapshot=snapshot, verdict=verdict, new_log_set_id=new_logs.id)
    db.add(job)
    db.flush()
    return record(job), False


def list_merges(db):
    return [record(x) for x in db.scalars(select(MergeJob).order_by(MergeJob.id.desc()).limit(100))]


def get_merge(db, ident):
    obj = db.get(MergeJob, ident)
    if obj is None:
        raise HTTPException(404, '合账记录不存在')
    return obj
