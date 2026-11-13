import json
from datetime import datetime, timedelta

from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required

from app import db
from app.models import (EVENT_CATEGORIES, EXPENSE_CATEGORIES, PRIORITIES, ActivityLog, Document, Event, Folder, Goal, Note,
                        Reminder, Subject, SyllabusTopic, Task, Transaction)
from app.streak import compute_streak
from app.utils import (log_activity, now_local, parse_date, parse_time, percent, safe_next, to_paise, week_start)

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


def goal_bars(uid, today):
    goals = Goal.query.filter_by(user_id=uid).all()
    out = {}
    for cat in ("Daily", "Weekly", "Monthly"):
        pool = [g for g in goals if g.category == cat and (not g.end_date or g.end_date >= today or g.completed)]
        out[cat] = {"count": len(pool), "percent": round(sum(g.percent for g in pool) / len(pool)) if pool else 0}
    return out


@bp.route("/dashboard")
@login_required
def dashboard():
    now = now_local()
    today = now.date()
    uid = current_user.id
    greeting = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 17 else "Good evening"

    base = Task.query.filter_by(user_id=uid)
    today_tasks = base.filter(Task.due_date == today).order_by(Task.is_done, Task.due_time.is_(None), Task.due_time).all()
    t_total = len(today_tasks)
    t_done = sum(1 for t in today_tasks if t.is_done)
    stats = {
        "today_total": t_total, "today_done": t_done, "today_percent": percent(t_done, t_total),
        "pending": base.filter(Task.is_done.is_(False)).count(),
        "completed": base.filter(Task.is_done.is_(True)).count(),
        "overdue": base.filter(Task.is_done.is_(False), Task.due_date < today).count(),
    }

    month_start = today.replace(day=1)
    month_expense = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount_paise), 0)).filter(
        Transaction.user_id == uid, Transaction.kind == "expense", Transaction.date >= month_start).scalar()
    total_expense = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount_paise), 0)).filter(
        Transaction.user_id == uid, Transaction.kind == "expense").scalar()

    subjects = Subject.query.filter_by(user_id=uid).all()
    s_total, s_done = sum(s.total for s in subjects), sum(s.done_count for s in subjects)

    start_of_day = datetime.combine(today, datetime.min.time())
    summary = {
        "tasks_done": Task.query.filter(Task.user_id == uid, Task.completed_at >= start_of_day).count(),
        "notes": Note.query.filter(Note.user_id == uid, Note.deleted_at.is_(None), Note.created_at >= start_of_day).count(),
        "spent": db.session.query(db.func.coalesce(db.func.sum(Transaction.amount_paise), 0)).filter(
            Transaction.user_id == uid, Transaction.kind == "expense", Transaction.date == today).scalar(),
        "topics": SyllabusTopic.query.join(Subject, Subject.id == SyllabusTopic.subject_id).filter(
            Subject.user_id == uid, SyllabusTopic.completed_at >= start_of_day).count(),
        "reminders": Reminder.query.filter(Reminder.user_id == uid, Reminder.is_done.is_(False),
                                           Reminder.remind_at >= start_of_day,
                                           Reminder.remind_at < start_of_day + timedelta(days=1)).count(),
    }
    events = []
    for ev in Event.query.filter(Event.user_id == uid, Event.repeat_yearly.is_(False),
                                 db.func.coalesce(Event.end_date, Event.start_date) >= today).order_by(Event.start_date).limit(5):
        events.append((ev, ev.start_date))
    for ev in Event.query.filter_by(user_id=uid, repeat_yearly=True):
        for yr in (today.year, today.year + 1):
            try:
                occ = ev.start_date.replace(year=yr)
            except ValueError:
                continue
            if occ >= today:
                events.append((ev, occ))
                break
    events = sorted(events, key=lambda x: x[1])[:5]

    return render_template(
        "main/dashboard.html", greeting=greeting, now=now, stats=stats, today_tasks=today_tasks,
        streak=compute_streak(uid, today), goals=goal_bars(uid, today),
        study={"percent": percent(s_done, s_total), "done": s_done, "total": s_total},
        money={"month": month_expense, "total": total_expense}, summary=summary, events=events,
        reminders=Reminder.query.filter_by(user_id=uid, is_done=False).order_by(Reminder.remind_at).limit(5).all(),
        recent_notes=Note.query.filter(Note.user_id == uid, Note.deleted_at.is_(None)).order_by(Note.updated_at.desc()).limit(5).all(),
        recent_docs=Document.query.filter(Document.user_id == uid, Document.deleted_at.is_(None)).order_by(Document.created_at.desc()).limit(5).all(),
        activity=ActivityLog.query.filter_by(user_id=uid).order_by(ActivityLog.id.desc()).limit(8).all(),
        priorities=PRIORITIES, exp_cats=EXPENSE_CATEGORIES, ev_cats=EVENT_CATEGORIES,
    )


@bp.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip()
    uid = current_user.id
    results = {}
    if len(q) >= 2:
        like = f"%{q}%"
        results["Notes"] = Note.query.filter(Note.user_id == uid, Note.deleted_at.is_(None),
                                             db.or_(Note.title.ilike(like), Note.content.ilike(like))).limit(20).all()
        results["Documents and files"] = Document.query.filter(Document.user_id == uid, Document.deleted_at.is_(None),
                                                               Document.original_name.ilike(like)).limit(20).all()
        results["Tasks"] = Task.query.filter(Task.user_id == uid, db.or_(Task.title.ilike(like), Task.description.ilike(like))).limit(20).all()
        results["Goals"] = Goal.query.filter(Goal.user_id == uid, db.or_(Goal.title.ilike(like), Goal.description.ilike(like))).limit(20).all()
        results["Events"] = Event.query.filter(Event.user_id == uid, db.or_(Event.title.ilike(like), Event.description.ilike(like))).limit(20).all()
        results["Subjects"] = Subject.query.filter(Subject.user_id == uid, Subject.name.ilike(like)).limit(20).all()
        results["Syllabus topics"] = (SyllabusTopic.query.join(Subject, Subject.id == SyllabusTopic.subject_id)
                                      .filter(Subject.user_id == uid, SyllabusTopic.title.ilike(like)).limit(20).all())
    total = sum(len(v) for v in results.values())
    return render_template("main/search.html", q=q, results=results, total=total)


def back(default="main.dashboard"):
    return redirect(safe_next(request.form.get("next")) or url_for(default))


@bp.route("/quick/<kind>", methods=["POST"])
@login_required
def quick_add(kind):
    f = request.form
    uid = current_user.id
    errors = []
    try:
        if kind == "note":
            title, content = f.get("title", "").strip()[:200], f.get("content", "").strip()
            if not title and not content:
                errors.append("Write a title or some content for the note.")
            elif len(content) > 100000:
                errors.append("The note is too long.")
            else:
                db.session.add(Note(user_id=uid, title=title or content.splitlines()[0][:60], content=content))
                log_activity(f"Added note: {title or content[:40]}")
        elif kind == "task":
            title = f.get("title", "").strip()
            pr = f.get("priority", "Medium")
            due = parse_date(f.get("due_date"))
            if not title or len(title) > 200:
                errors.append("Enter a task title (up to 200 characters).")
            elif pr not in PRIORITIES:
                errors.append("Choose a valid priority.")
            else:
                db.session.add(Task(user_id=uid, title=title, priority=pr, due_date=due))
                log_activity(f"Added task: {title}")
        elif kind == "expense":
            cat = f.get("category", "Other")
            if cat not in EXPENSE_CATEGORIES:
                errors.append("Choose a valid category.")
            else:
                amount = to_paise(f.get("amount", ""))
                d = parse_date(f.get("date")) or now_local().date()
                db.session.add(Transaction(user_id=uid, kind="expense", category=cat, amount_paise=amount, date=d,
                                           note=f.get("note", "").strip()[:200]))
                log_activity(f"Added expense: {cat}")
        elif kind == "reminder":
            title = f.get("title", "").strip()
            d, t = parse_date(f.get("date")), parse_time(f.get("time"))
            if not title or len(title) > 200:
                errors.append("Enter a reminder title (up to 200 characters).")
            elif not d or not t:
                errors.append("Choose a date and time for the reminder.")
            else:
                db.session.add(Reminder(user_id=uid, title=title, remind_at=datetime.combine(d, t)))
                log_activity(f"Added reminder: {title}")
        elif kind == "event":
            title, cat = f.get("title", "").strip(), f.get("category", "")
            d = parse_date(f.get("date"))
            if not title or len(title) > 200:
                errors.append("Enter an event title (up to 200 characters).")
            elif cat not in EVENT_CATEGORIES:
                errors.append("Choose a valid category.")
            elif not d:
                errors.append("Choose a date for the event.")
            else:
                db.session.add(Event(user_id=uid, title=title, category=cat, start_date=d))
                log_activity(f"Added event: {title}")
        else:
            return redirect(url_for("main.dashboard"))
    except ValueError:
        errors.append("Check the amount, date and time you entered.")
    if errors:
        for e in errors:
            flash(e, "danger")
        db.session.rollback()
    else:
        db.session.commit()
        flash(f"{kind.capitalize()} added.", "success")
    return back()


@bp.route("/favourites")
@login_required
def favourites():
    uid = current_user.id
    notes = Note.query.filter(Note.user_id == uid, Note.deleted_at.is_(None),
                              db.or_(Note.is_important.is_(True), Note.is_pinned.is_(True))).order_by(Note.updated_at.desc()).all()
    docs = Document.query.filter(Document.user_id == uid, Document.deleted_at.is_(None),
                                 Document.is_important.is_(True)).order_by(Document.created_at.desc()).all()
    return render_template("main/favourites.html", notes=notes, docs=docs)


@bp.route("/trash")
@login_required
def trash():
    uid = current_user.id
    notes = Note.query.filter(Note.user_id == uid, Note.deleted_at.isnot(None)).order_by(Note.deleted_at.desc()).all()
    docs = Document.query.filter(Document.user_id == uid, Document.deleted_at.isnot(None)).order_by(Document.deleted_at.desc()).all()
    return render_template("main/trash.html", notes=notes, docs=docs)


def purge_doc(doc):
    import os

    from app.docs.routes import file_path
    try:
        os.remove(file_path(doc))
    except OSError:
        pass
    db.session.delete(doc)


@bp.route("/trash/<kind>/<int:item_id>/<action>", methods=["POST"])
@login_required
def trash_action(kind, item_id, action):
    model = {"note": Note, "doc": Document}.get(kind)
    if not model or action not in ("restore", "delete"):
        return redirect(url_for("main.trash"))
    item = model.query.filter(model.id == item_id, model.user_id == current_user.id, model.deleted_at.isnot(None)).first_or_404()
    if action == "restore":
        if kind == "doc" and item.folder_id and not db.session.get(Folder, item.folder_id):
            item.folder_id = None
        item.deleted_at = None
        flash("Restored.", "success")
    else:
        purge_doc(item) if kind == "doc" else db.session.delete(item)
        flash("Deleted permanently.", "success")
    db.session.commit()
    return redirect(url_for("main.trash"))


@bp.route("/trash/empty", methods=["POST"])
@login_required
def trash_empty():
    uid = current_user.id
    for n in Note.query.filter(Note.user_id == uid, Note.deleted_at.isnot(None)).all():
        db.session.delete(n)
    for d in Document.query.filter(Document.user_id == uid, Document.deleted_at.isnot(None)).all():
        purge_doc(d)
    db.session.commit()
    flash("Recycle bin emptied.", "success")
    return redirect(url_for("main.trash"))


@bp.route("/calculator")
@login_required
def calculator():
    return render_template("main/calculator.html")


@bp.route("/privacy")
def privacy():
    return render_template("main/privacy.html")


@bp.route("/terms")
def terms():
    return render_template("main/terms.html")


@bp.route("/manifest.webmanifest")
def manifest():
    data = {
        "name": current_app.config["SITE_NAME"], "short_name": current_app.config["SITE_NAME"],
        "description": current_app.config["TAGLINE"], "start_url": "/dashboard", "scope": "/",
        "display": "standalone", "background_color": "#f4f5f2", "theme_color": "#14625c",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    return Response(json.dumps(data), mimetype="application/manifest+json")


@bp.route("/sw.js")
def service_worker():
    resp = send_from_directory(current_app.static_folder, "js/sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp
