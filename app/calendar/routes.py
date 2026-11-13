from datetime import date, datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import EVENT_CATEGORIES, Event, Reminder, Task
from app.utils import log_activity, parse_date, parse_time, today_local

bp = Blueprint("calendar", __name__, url_prefix="/calendar")

COLORS = {
    "College holiday": "#b45309", "College event": "#0f766e", "Exam date": "#b42318",
    "Assignment submission": "#1d4ed8", "Personal event": "#4b5563", "Birthday": "#a16207",
    "Important date": "#9f1239",
}


def get_event_or_404(event_id):
    return Event.query.filter_by(id=event_id, user_id=current_user.id).first_or_404()


def range_args():
    try:
        start = datetime.strptime(request.args.get("start", "")[:10], "%Y-%m-%d").date()
        end = datetime.strptime(request.args.get("end", "")[:10], "%Y-%m-%d").date()
    except ValueError:
        start = today_local().replace(day=1)
        end = start + timedelta(days=42)
    return start, end


@bp.route("/")
@login_required
def index():
    return render_template("calendar/index.html")


@bp.route("/feed")
@login_required
def feed():
    start, end = range_args()
    uid = current_user.id
    out = []

    def add_event(ev, s_date, e_date):
        item = {"id": f"e{ev.id}-{s_date.isoformat()}", "title": ev.title, "color": COLORS.get(ev.category, "#4b5563"),
                "url": url_for("calendar.edit", event_id=ev.id)}
        if ev.start_time:
            item["start"] = datetime.combine(s_date, ev.start_time).isoformat()
            if ev.end_time:
                item["end"] = datetime.combine(e_date or s_date, ev.end_time).isoformat()
        else:
            item["start"] = s_date.isoformat()
            item["allDay"] = True
            if e_date and e_date > s_date:
                item["end"] = (e_date + timedelta(days=1)).isoformat()
        out.append(item)

    for ev in Event.query.filter(Event.user_id == uid, Event.repeat_yearly.is_(False),
                                 Event.start_date <= end, db.func.coalesce(Event.end_date, Event.start_date) >= start):
        add_event(ev, ev.start_date, ev.end_date)
    for ev in Event.query.filter_by(user_id=uid, repeat_yearly=True):
        for yr in range(start.year, end.year + 1):
            try:
                occ = ev.start_date.replace(year=yr)
            except ValueError:
                continue
            if start <= occ <= end:
                add_event(ev, occ, None)

    for t in Task.query.filter(Task.user_id == uid, Task.due_date >= start, Task.due_date <= end):
        item = {"id": f"t{t.id}", "title": ("Done: " if t.is_done else "Task: ") + t.title, "color": "#64748b",
                "url": url_for("tasks.edit", task_id=t.id), "classNames": ["fc-done"] if t.is_done else []}
        item["start"] = datetime.combine(t.due_date, t.due_time).isoformat() if t.due_time else t.due_date.isoformat()
        out.append(item)

    s_dt, e_dt = datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.min.time())
    for r in Reminder.query.filter(Reminder.user_id == uid, Reminder.remind_at >= s_dt, Reminder.remind_at <= e_dt):
        out.append({"id": f"r{r.id}", "title": "Reminder: " + r.title, "start": r.remind_at.isoformat(),
                    "color": "#0f766e", "url": url_for("reminders.edit", rid=r.id),
                    "classNames": ["fc-done"] if r.is_done else []})
    return jsonify(out)


def read_form(form):
    errors = []
    title = form.get("title", "").strip()
    if not title or len(title) > 200:
        errors.append("Enter an event title (up to 200 characters).")
    category = form.get("category", "")
    if category not in EVENT_CATEGORIES:
        errors.append("Choose a valid category.")
    desc = form.get("description", "").strip()
    if len(desc) > 5000:
        errors.append("Description is too long.")
    start = end = st = et = None
    try:
        start = parse_date(form.get("start_date"))
        end = parse_date(form.get("end_date"))
        st = parse_time(form.get("start_time"))
        et = parse_time(form.get("end_time"))
    except ValueError:
        errors.append("Enter valid dates and times.")
    if not start:
        errors.append("Choose a start date.")
    if start and end and end < start:
        errors.append("End date cannot be before start date.")
    if et and not st:
        errors.append("Add a start time or clear the end time.")
    if start and st and et and (end or start) == start and et <= st:
        errors.append("End time must be after start time.")
    repeat = bool(form.get("repeat_yearly"))
    if repeat:
        end = None
    return dict(title=title, category=category, description=desc, start_date=start, end_date=end,
                start_time=st, end_time=et, repeat_yearly=repeat), errors


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        data, errors = read_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("calendar/form.html", ev=None, form=request.form, categories=EVENT_CATEGORIES)
        db.session.add(Event(user_id=current_user.id, **data))
        log_activity(f"Added event: {data['title']}")
        db.session.commit()
        flash("Event added.", "success")
        return redirect(url_for("calendar.index"))
    default = request.args.get("date", "")
    try:
        parse_date(default)
    except ValueError:
        default = ""
    return render_template("calendar/form.html", ev=None, form={"start_date": default} if default else None,
                           categories=EVENT_CATEGORIES)


@bp.route("/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
def edit(event_id):
    ev = get_event_or_404(event_id)
    if request.method == "POST":
        data, errors = read_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("calendar/form.html", ev=ev, form=request.form, categories=EVENT_CATEGORIES)
        for k, v in data.items():
            setattr(ev, k, v)
        db.session.commit()
        flash("Event saved.", "success")
        return redirect(url_for("calendar.index"))
    return render_template("calendar/form.html", ev=ev, form=None, categories=EVENT_CATEGORIES)


@bp.route("/<int:event_id>/delete", methods=["POST"])
@login_required
def delete(event_id):
    db.session.delete(get_event_or_404(event_id))
    db.session.commit()
    flash("Event deleted.", "success")
    return redirect(url_for("calendar.index"))
