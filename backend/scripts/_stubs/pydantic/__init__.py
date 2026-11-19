class _BaseModel:
    def __init__(self, **data):
        for k, v in data.items():
            setattr(self, k, v)

    def model_dump(self):
        return dict(self.__dict__)

    def model_copy(self, update=None):
        data = dict(self.__dict__)
        data.update(update or {})
        return type(self)(**data)


class BaseModel(_BaseModel):
    pass


class _Field:
    def __init__(self, default=None, **kwargs):
        self.default = default


def Field(default=None, **kwargs):
    return _Field(default)
