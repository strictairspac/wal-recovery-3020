import json
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.config.database import get_db
from src.middlewares.auth import current_user, writable
from src.schemas.merge import MergePreviewInput, MergeCommitInput
from src.services.merge_service import preview_merge, commit_merge, list_merges, get_merge
from src.models.entities import MergeJob
from src.controllers.actions import audit
from src.utils.serialize import record

router = APIRouter()


@router.get('/merges')
def listing(db=Depends(get_db), user=Depends(current_user)):
    return list_merges(db)


@router.post('/merges/preview')
def preview(data: MergePreviewInput, db=Depends(get_db), user=Depends(current_user)):
    return preview_merge(db, data)


@router.post('/merges', status_code=201)
def commit(data: MergeCommitInput, db=Depends(get_db), user=Depends(writable)):
    try:
        obj, reused = commit_merge(db, data)
    except IntegrityError:
        # 并发重试同一裁决：唯一键兜底，返回既有合账，不重复生成新日志。
        db.rollback()
        existing = db.scalar(select(MergeJob).where(MergeJob.verdict_key == data.verdict_key))
        if existing is not None:
            return record(existing)
        raise
    audit(db, user, f'merge:{"reuse" if reused else "commit"}:{obj["id"]}')
    db.commit()
    return obj


@router.get('/merges/{ident}')
def detail(ident: int, db=Depends(get_db), user=Depends(current_user)):
    return record(get_merge(db, ident))


@router.get('/merges/{ident}/export')
def export(ident: int, db=Depends(get_db), user=Depends(current_user)):
    obj = get_merge(db, ident)
    return Response(json.dumps(record(obj), ensure_ascii=False, indent=2),
                    media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="merge-{ident}.json"'})
