from datetime import timedelta

from app import db
from app.models import Task


def compute_streak(user_id, today):
    """A day counts when it has at least one task due and every one is done.
    Days with no tasks are skipped (they neither add nor break the streak).
    Today never breaks the streak while it is still incomplete."""
    rows = (
        db.session.query(
            Task.due_date,
            db.func.count(Task.id),
            db.func.sum(db.case((Task.is_done.is_(True), 1), else_=0)),
        )
        .filter(Task.user_id == user_id, Task.due_date.isnot(None), Task.due_date <= today)
        .group_by(Task.due_date)
        .all()
    )
    days = {d: (total, int(done or 0)) for d, total, done in rows}

    current = 0
    if days:
        d = today
        earliest = min(days)
        while d >= earliest:
            total, done = days.get(d, (0, 0))
            if total:
                if done == total:
                    current += 1
                elif d != today:
                    break
            d -= timedelta(days=1)

    best = run = 0
    for d in sorted(days):
        total, done = days[d]
        if done == total:
            run += 1
            best = max(best, run)
        elif d != today:
            run = 0

    recent = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        total, done = days.get(d, (0, 0))
        if not total:
            state = "none"
        elif done == total:
            state = "done"
        elif d == today:
            state = "pending"
        else:
            state = "missed"
        recent.append((d, state))

    t_total, t_done = days.get(today, (0, 0))
    return {
        "current": current,
        "best": max(best, current),
        "recent": recent,
        "today_total": t_total,
        "today_left": t_total - t_done,
        "today_complete": bool(t_total) and t_done == t_total,
    }
