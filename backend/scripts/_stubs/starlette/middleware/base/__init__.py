class BaseHTTPMiddleware:
    def __init__(self, app):
        self.app = app


class _JSONResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


def JSONResponse(content, status_code=200):
    return _JSONResponse(content, status_code)
