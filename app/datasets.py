from datetime import date, datetime, time, timedelta

from app import db
from app.models import Goal, GoalTask, StudyItem, Subject, SyllabusTopic, Task, Transaction
from app.utils import today_local, week_start


def _days(n, today):
    return [today - timedelta(days=n - 1 - i) for i in range(n)]


def _months(n, today):
    y, m, out = today.year, today.month, []
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _mlabel(y, m):
    return date(y, m, 1).strftime("%b %Y")


def _since(first_day):
    return datetime.combine(first_day, time.min)


def _count_days(rows, days):
    counts = {d: 0 for d in days}
    for (dt,) in rows:
        if dt and dt.date() in counts:
            counts[dt.date()] += 1
    return [counts[d] for d in days]


def _done_rows(uid, first_day):
    since = _since(first_day)
    tasks = db.session.query(Task.completed_at).filter(Task.user_id == uid, Task.completed_at >= since).all()
    topics = (
        db.session.query(SyllabusTopic.completed_at)
        .join(Subject, Subject.id == SyllabusTopic.subject_id)
        .filter(Subject.user_id == uid, SyllabusTopic.completed_at >= since)
        .all()
    )
    items = db.session.query(StudyItem.completed_at).filter(StudyItem.user_id == uid, StudyItem.completed_at >= since).all()
    gtasks = (
        db.session.query(GoalTask.completed_at)
        .join(Goal, Goal.id == GoalTask.goal_id)
        .filter(Goal.user_id == uid, GoalTask.completed_at >= since)
        .all()
    )
    return tasks, topics, items, gtasks


def _fmt_days(days):
    return [d.strftime("%d %b") for d in days]


def tasks_daily(uid, days):
    today = today_local()
    ds = _days(days, today)
    tasks, *_ = _done_rows(uid, ds[0])
    return {"labels": _fmt_days(ds), "series": [{"label": "Tasks completed", "data": _count_days(tasks, ds)}]}


def study_daily(uid, days):
    today = today_local()
    ds = _days(days, today)
    _, topics, items, _g = _done_rows(uid, ds[0])
    a, b = _count_days(topics, ds), _count_days(items, ds)
    return {"labels": _fmt_days(ds), "series": [{"label": "Study progress (topics and study items done)", "data": [x + y for x, y in zip(a, b)]}]}


def productivity(uid, days):
    today = today_local()
    ds = _days(days, today)
    tasks, topics, items, gtasks = _done_rows(uid, ds[0])
    study = [x + y for x, y in zip(_count_days(topics, ds), _count_days(items, ds))]
    return {
        "labels": _fmt_days(ds),
        "series": [
            {"label": "Tasks", "data": _count_days(tasks, ds)},
            {"label": "Study", "data": study},
            {"label": "Goal steps", "data": _count_days(gtasks, ds)},
        ],
    }


def _expense_rows(uid, first_day, kind="expense"):
    return (
        db.session.query(Transaction.date, Transaction.amount_paise, Transaction.category)
        .filter(Transaction.user_id == uid, Transaction.kind == kind, Transaction.date >= first_day)
        .all()
    )


def expenses_daily(uid, days):
    ds = _days(days, today_local())
    sums = {d: 0 for d in ds}
    for d, amt, _c in _expense_rows(uid, ds[0]):
        if d in sums:
            sums[d] += amt
    return {"labels": _fmt_days(ds), "money": True, "series": [{"label": "Expenses", "data": [sums[d] / 100 for d in ds]}]}


def expenses_weekly(uid, days):
    start = week_start(today_local()) - timedelta(weeks=7)
    weeks = [start + timedelta(weeks=i) for i in range(8)]
    sums = {w: 0 for w in weeks}
    for d, amt, _c in _expense_rows(uid, start):
        sums[week_start(d)] = sums.get(week_start(d), 0) + amt
    return {"labels": [w.strftime("Week of %d %b") for w in weeks], "money": True, "series": [{"label": "Expenses", "data": [sums[w] / 100 for w in weeks]}]}


def expenses_monthly(uid, days):
    ms = _months(12, today_local())
    sums = {m: 0 for m in ms}
    for d, amt, _c in _expense_rows(uid, date(ms[0][0], ms[0][1], 1)):
        if (d.year, d.month) in sums:
            sums[(d.year, d.month)] += amt
    return {"labels": [_mlabel(*m) for m in ms], "money": True, "series": [{"label": "Expenses", "data": [sums[m] / 100 for m in ms]}]}


def expenses_category(uid, days):
    first = today_local() - timedelta(days=days - 1)
    sums = {}
    for _d, amt, cat in _expense_rows(uid, first):
        sums[cat] = sums.get(cat, 0) + amt
    cats = sorted(sums, key=lambda c: -sums[c])
    return {"labels": cats, "money": True, "series": [{"label": "Expenses", "data": [sums[c] / 100 for c in cats]}]}


def income_expense(uid, days):
    ms = _months(12, today_local())
    first = date(ms[0][0], ms[0][1], 1)
    inc, exp = {m: 0 for m in ms}, {m: 0 for m in ms}
    for d, amt, _c in _expense_rows(uid, first, "income"):
        if (d.year, d.month) in inc:
            inc[(d.year, d.month)] += amt
    for d, amt, _c in _expense_rows(uid, first, "expense"):
        if (d.year, d.month) in exp:
            exp[(d.year, d.month)] += amt
    return {
        "labels": [_mlabel(*m) for m in ms],
        "money": True,
        "series": [{"label": "Income", "data": [inc[m] / 100 for m in ms]}, {"label": "Expenses", "data": [exp[m] / 100 for m in ms]}],
    }


def savings(uid, days):
    ms = _months(12, today_local())
    first = date(ms[0][0], ms[0][1], 1)
    before = 0
    for kind, amt in db.session.query(Transaction.kind, Transaction.amount_paise).filter(Transaction.user_id == uid, Transaction.date < first):
        before += amt if kind == "income" else -amt
    net = {m: 0 for m in ms}
    for kind, d, amt in db.session.query(Transaction.kind, Transaction.date, Transaction.amount_paise).filter(Transaction.user_id == uid, Transaction.date >= first):
        if (d.year, d.month) in net:
            net[(d.year, d.month)] += amt if kind == "income" else -amt
    running, out = before, []
    for m in ms:
        running += net[m]
        out.append(running / 100)
    return {"labels": [_mlabel(*m) for m in ms], "money": True, "series": [{"label": "Savings (income minus expenses, running total)", "data": out}]}


def subject_progress(uid, days):
    subs = Subject.query.filter_by(user_id=uid).order_by(Subject.semester, Subject.name).all()
    return {"labels": [s.name for s in subs], "percent": True, "series": [{"label": "Syllabus completed (%)", "data": [s.percent for s in subs]}]}


def goals_monthly(uid, days):
    ms = _months(12, today_local())
    first = date(ms[0][0], ms[0][1], 1)
    rows = (
        db.session.query(GoalTask.completed_at)
        .join(Goal, Goal.id == GoalTask.goal_id)
        .filter(Goal.user_id == uid, GoalTask.completed_at >= _since(first))
        .all()
    )
    counts = {m: 0 for m in ms}
    for (dt,) in rows:
        if dt and (dt.year, dt.month) in counts:
            counts[(dt.year, dt.month)] += 1
    return {"labels": [_mlabel(*m) for m in ms], "series": [{"label": "Goal steps completed", "data": [counts[m] for m in ms]}]}


def goals_progress(uid, days):
    goals = Goal.query.filter_by(user_id=uid).order_by(Goal.id.desc()).limit(12).all()
    return {"labels": [g.title for g in goals], "percent": True, "series": [{"label": "Goal progress (%)", "data": [g.percent for g in goals]}]}


DATASETS = {
    "tasks_daily": (tasks_daily, "Daily task completion", "bar"),
    "study_daily": (study_daily, "Daily study progress", "line"),
    "productivity": (productivity, "Weekly productivity", "bar"),
    "expenses_daily": (expenses_daily, "Daily expenses", "bar"),
    "expenses_weekly": (expenses_weekly, "Weekly expenses", "bar"),
    "expenses_monthly": (expenses_monthly, "Monthly expenses", "bar"),
    "expenses_category": (expenses_category, "Expenses by category", "pie"),
    "income_expense": (income_expense, "Income vs expenses", "bar"),
    "savings": (savings, "Savings", "area"),
    "subject_progress": (subject_progress, "Subject-wise syllabus progress", "bar"),
    "goals_monthly": (goals_monthly, "Monthly goal completion", "line"),
    "goals_progress": (goals_progress, "Goal progress", "bar"),
}
