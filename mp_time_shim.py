# Adds MicroPython-style ticks helpers onto CPython's time module.
import time as _t
if not hasattr(_t, "ticks_ms"):
    _t.ticks_ms  = lambda: int(_t.time() * 1000)
if not hasattr(_t, "ticks_add"):
    _t.ticks_add = lambda a, b: a + b
if not hasattr(_t, "ticks_diff"):
    _t.ticks_diff = lambda a, b: a - b
