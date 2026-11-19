# 初始化结构
SQLAlchemy metadata.create_all首次建users、log_sets、crash_cases、recoveries、audits、merge_jobs。log_sets.name、crash_cases.name、merge_jobs.verdict_key唯一，关联使用外键，入队冻结日志和崩溃点快照；合账任务冻结两侧日志标识与断电点、裁决结果及新日志外键。暂无在线schema升级器；在已存在的旧库上新增merge_jobs表需要手工执行 CREATE TABLE merge_jobs（定义见models/entities.py）或清空卷后重新初始化。
