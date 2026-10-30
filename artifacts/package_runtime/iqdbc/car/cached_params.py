import time

PARAMS_REFRESH_S = 0.1


class CachedParams:
  def __init__(self, params, refresh_s: float = PARAMS_REFRESH_S):
    self._params = params
    self._refresh_s = refresh_s
    self._bools: dict[str, tuple[bool, float]] = {}

  def get_bool(self, key, *args, **kwargs):
    if args or kwargs:
      return self._params.get_bool(key, *args, **kwargs)
    now = time.monotonic()
    entry = self._bools.get(key)
    if entry is not None and now - entry[1] < self._refresh_s:
      return entry[0]
    value = self._params.get_bool(key)
    self._bools[key] = (value, now)
    return value

  def put(self, key, *args, **kwargs):
    self._bools.pop(key, None)
    return self._params.put(key, *args, **kwargs)

  def put_bool(self, key, *args, **kwargs):
    self._bools.pop(key, None)
    return self._params.put_bool(key, *args, **kwargs)

  def put_nonblocking(self, key, *args, **kwargs):
    self._bools.pop(key, None)
    return self._params.put_nonblocking(key, *args, **kwargs)

  def put_bool_nonblocking(self, key, *args, **kwargs):
    self._bools.pop(key, None)
    return self._params.put_bool_nonblocking(key, *args, **kwargs)

  def remove(self, key, *args, **kwargs):
    self._bools.pop(key, None)
    return self._params.remove(key, *args, **kwargs)

  def __getattr__(self, name):
    return getattr(self._params, name)
