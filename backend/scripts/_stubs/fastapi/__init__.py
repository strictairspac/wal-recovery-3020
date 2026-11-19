class HTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class APIRouter:
    def __init__(self, *a, **k):
        pass

    def get(self, *a, **k):
        def deco(fn):
            return fn
        return deco

    def post(self, *a, **k):
        def deco(fn):
            return fn
        return deco


class Depends:
    def __init__(self, fn=None):
        self.fn = fn


class _Response:
    def __init__(self, content='', media_type=None, headers=None):
        self.content = content


def Response(*a, **k):
    return _Response(*a, **k)
