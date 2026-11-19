class _Select:
    def __init__(self, *entities):
        self.entities = entities
        self.filters = []

    def where(self, *expr):
        self.filters.extend(expr)
        return self

    def order_by(self, *expr):
        return self

    def limit(self, n):
        return self


def select(*entities):
    return _Select(*entities)


class _IntegrityError(Exception):
    pass


IntegrityError = _IntegrityError


class _ForeignKey:
    def __init__(self, target):
        self.target = target


def ForeignKey(target):
    return _ForeignKey(target)


class _Column:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.name = None

    def __set_name__(self, owner, name):
        self.name = name

    def __eq__(self, other):
        return ('eq', self.name, other)

    def __hash__(self):
        return id(self)


def mapped_column(*args, **kwargs):
    return _Column(*args, **kwargs)


class _Mapped:
    def __getitem__(self, item):
        return None


Mapped = _Mapped()


class _Type:
    def __init__(self, *args, **kwargs):
        pass


def String(*a, **k):
    return _Type()


def Integer(*a, **k):
    return _Type()


def JSON(*a, **k):
    return _Type()


def DateTime(*a, **k):
    return _Type()
