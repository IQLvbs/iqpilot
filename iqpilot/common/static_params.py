class StaticParams:
  def __init__(self, source):
    object.__setattr__(self, "_source", source)

  def __getattr__(self, name):
    value = getattr(self._source, name)
    object.__setattr__(self, name, value)
    return value


class StaticView:
  def __init__(self, attribute: str):
    self._attribute = attribute
    self._slot = "_static_" + attribute

  def __get__(self, obj, owner=None):
    if obj is None:
      return self
    source = getattr(obj, self._attribute)
    cached = obj.__dict__.get(self._slot)
    if cached is None or cached._source is not source:
      cached = obj.__dict__[self._slot] = StaticParams(source)
    return cached
