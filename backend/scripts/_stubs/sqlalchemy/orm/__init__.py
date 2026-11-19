from .. import ForeignKey, mapped_column, Mapped, String, Integer, JSON, DateTime  # noqa: F401


class DeclarativeBase:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
