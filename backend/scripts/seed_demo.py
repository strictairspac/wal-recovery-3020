import os
from sqlalchemy import select
from src.config.database import Base,engine,Session
from src.models.entities import User,LogSet,CrashCase
from src.utils.security import hash_password
RECORDS=[{'op':'begin','tx':'T1'},{'op':'write','tx':'T1','key':'sample_A','value':75},{'op':'commit','tx':'T1'},{'op':'checkpoint'},{'op':'begin','tx':'T2'},{'op':'write','tx':'T2','key':'sample_B','value':40},{'op':'begin','tx':'T3'},{'op':'write','tx':'T3','key':'sample_A','value':60},{'op':'commit','tx':'T3'},{'op':'write','tx':'T2','key':'sample_B','value':35},{'op':'commit','tx':'T2'}]
# 早班离线补录：与晚班同底账，E1/E2 已提交并写 sample_A（与晚班T1/T3跨班冲突），E3 断电前未提交。
EARLY_RECORDS=[{'op':'begin','tx':'E1'},{'op':'write','tx':'E1','key':'sample_A','value':88},{'op':'commit','tx':'E1'},{'op':'begin','tx':'E2'},{'op':'write','tx':'E2','key':'sample_A','value':82},{'op':'commit','tx':'E2'},{'op':'begin','tx':'E3'},{'op':'write','tx':'E3','key':'sample_B','value':30}]
def seed():
    Base.metadata.create_all(engine)
    if os.getenv('SEED_DEMO','true').lower()!='true':return
    with Session() as db:
        for role in ('admin','operator','viewer'):
            email=role+'@haili.local'
            if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,role=role,password_hash=hash_password('Recovery2026!')))
        logs=db.scalar(select(LogSet).where(LogSet.name=='海砾采样账本-晚班'))
        if logs is None:
            logs=LogSet(name='海砾采样账本-晚班',description='A初始100份、B初始50份，T1提交后检查点，T2未提交，T3已提交',initial={'sample_A':100,'sample_B':50},records=RECORDS);db.add(logs);db.flush()
        early=db.scalar(select(LogSet).where(LogSet.name=='海砾采样账本-早班补录'))
        if early is None:
            early=LogSet(name='海砾采样账本-早班补录',description='离线补录早班历史，与晚班同底账；E1/E2已提交写A，E3在断电点7前未提交',initial={'sample_A':100,'sample_B':50},records=EARLY_RECORDS);db.add(early);db.flush()
        for name,point in [('断电点10-撤销T2',10),('完整提交点11',11),('初始点0',0)]:
            if not db.scalar(select(CrashCase).where(CrashCase.name==name)):db.add(CrashCase(name=name,log_set_id=logs.id,crash_after=point))
        early_case='早班断电点7-丢弃E3'
        if not db.scalar(select(CrashCase).where(CrashCase.name==early_case)):db.add(CrashCase(name=early_case,log_set_id=early.id,crash_after=7))
        db.commit()
if __name__=='__main__':seed()
