"""settings.json values with type checking, and the glue that turns them into
shrink.Options (shared by the GUI and the CLI).

The file sits next to the exe where anyone can edit it, so nothing in it is
trusted: a wrong type or an unknown value falls back to the default.
"""
from __future__ import annotations

import dataclasses

import i18n
import shrink


@dataclasses.dataclass
class Prefs:
    mode: str = shrink.TARGET
    target_kb: int = shrink.DEFAULT_TARGET_KB  # a preset or the user's own number
    long_edge: int = shrink.DEFAULT_SIZE
    quality_level: str = shrink.DEFAULT_QUALITY_LEVEL  # high, medium, low
    output: str = shrink.FOLDER
    keep_png: bool = False
    recursive: bool = True
    update_check: bool = True  # once a day, ask the tools site whether a newer version exists
    update_check_last: str = ""  # YYYY-MM-DD of the last check the server answered
    update_check_skipped: str = ""  # "Later" was pressed for this version: do not show it again

    def options(self) -> shrink.Options:
        return shrink.Options(mode=self.mode, target_kb=self.target_kb, long_edge=self.long_edge,
                              quality=shrink.QUALITY_LEVELS.get(self.quality_level, 75), output=self.output,
                              keep_png=self.keep_png).validated()


CHOICES = {"mode": shrink.MODES, "output": shrink.OUTPUTS, "quality_level": tuple(shrink.QUALITY_LEVELS),
           "long_edge": shrink.SIZES}
RANGES = {"target_kb": (shrink.TARGET_MIN_KB, shrink.TARGET_MAX_KB)}


def load() -> Prefs:
    raw = i18n.load_settings()
    default = Prefs()
    values = {}
    for f in dataclasses.fields(Prefs):
        want = type(getattr(default, f.name))
        value = raw.get(f.name, getattr(default, f.name))
        ok = isinstance(value, want) and (want is bool or not isinstance(value, bool))
        values[f.name] = value if ok else getattr(default, f.name)
    p = Prefs(**values)
    for name, allowed in CHOICES.items():
        if getattr(p, name) not in allowed:
            setattr(p, name, getattr(default, name))
    for name, (lo, hi) in RANGES.items():
        if not lo <= getattr(p, name) <= hi:
            setattr(p, name, getattr(default, name))
    p.update_check_last = p.update_check_last.strip()[:10]
    p.update_check_skipped = p.update_check_skipped.strip()[:32]
    return p


def save(p: Prefs) -> None:
    settings = i18n.load_settings()
    settings.update(dataclasses.asdict(p))
    i18n.save_settings(settings)
