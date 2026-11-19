"""测试桩件：切断真实数据库/Redis 配置依赖。"""


class _Base:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


Base = _Base
engine = None
Session = None


def get_db():
    yield None
