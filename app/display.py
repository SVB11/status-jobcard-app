"""Staff-facing job identifiers.

The unit ID staff see is job_cards.stock_number, kept exactly as stored
(WS####, CWS, SPWS, or any other prefix). job_cards.job_number (JC-####)
stays the internal key in the database and in URLs. If stock_number is
blank, the JC number is shown so the label is never empty.
"""
from datetime import datetime, timedelta, timezone

SAST_TZ = timezone(timedelta(hours=2))  # South Africa has no daylight saving


def job_display_id(job) -> str:
    if job is None:
        return ""
    stock = (getattr(job, "stock_number", None) or "").strip()
    if stock:
        return stock
    return (getattr(job, "job_number", None) or "").strip()


def job_display_date(job) -> str:
    """Short created date in SAST, used to tell repeat stock numbers apart."""
    raw = getattr(job, "created_at", None) if job is not None else None
    if not raw:
        return ""
    if isinstance(raw, str):
        text = raw.replace("Z", "+00:00")
        try:
            raw = datetime.fromisoformat(text)
        except ValueError:
            return raw[:10]
    dt = raw
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(SAST_TZ).strftime("%d %b %Y")


def stock_repeat_counts(jobs) -> dict:
    counts = {}
    for job in jobs or []:
        stock = (getattr(job, "stock_number", None) or "").strip()
        if stock:
            counts[stock] = counts.get(stock, 0) + 1
    return counts


def job_display_fields(job, counts=None) -> dict:
    """display_id plus a date hint when this stock number appears more than once."""
    label = job_display_id(job)
    hint = ""
    stock = (getattr(job, "stock_number", None) or "").strip() if job is not None else ""
    n = 0
    if stock and counts is not None:
        if isinstance(counts, dict):
            n = counts.get(stock, 0)
        else:
            try:
                n = int(counts)
            except (TypeError, ValueError):
                n = 0
    if stock and n > 1:
        hint = job_display_date(job)
    return {"display_id": label, "display_hint": hint}


def job_display_label(job, counts=None) -> str:
    fields = job_display_fields(job, counts)
    if fields["display_hint"]:
        return f"{fields['display_id']} · {fields['display_hint']}"
    return fields["display_id"]


def with_display(payload: dict, job, counts=None) -> dict:
    payload.update(job_display_fields(job, counts))
    return payload
