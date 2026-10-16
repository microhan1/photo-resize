"""Sentences built from several lang keys, shared by the GUI and the CLI."""
from __future__ import annotations

import shrink
from i18n import t

DOT = chr(0xB7)


def summary_text(s: shrink.Summary) -> str:
    """'120 photos · 860 MB -> 95 MB (89% smaller) · over target 2 · location removed 118'.
    The location count is always shown (PRD: GPS is always removed)."""
    parts = [t("summary_main", count=s.count, before=shrink.format_bytes(s.before),
               after=shrink.format_bytes(s.after), percent=s.percent)]
    if s.over:
        parts.append(t("summary_over", count=s.over))
    if s.small:
        parts.append(t("summary_small", count=s.small))
    if s.failed:
        parts.append(t("summary_failed", count=s.failed))
    if s.cancelled:
        parts.append(t("summary_cancelled", count=s.cancelled))
    parts.append(t("summary_gps", count=s.gps))
    return f" {DOT} ".join(parts)
