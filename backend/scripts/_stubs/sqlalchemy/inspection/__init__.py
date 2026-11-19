class _ColumnAttr:
    def __init__(self, key):
        self.key = key


class _Mapper:
    def __init__(self, cls):
        self.column_attrs = [_ColumnAttr(k) for k in getattr(cls, '_columns', [])]


class _Inspected:
    def __init__(self, obj):
        self.mapper = _Mapper(type(obj))


def inspect(obj):
    return _Inspected(obj)
