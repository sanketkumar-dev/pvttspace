from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import REPEATS, Reminder
from app.utils import fdatetime, log_activity, now_local, parse_date, parse_time, safe_next

bp = Blueprint("reminders", __name__, url_prefix="/reminders")

STEP = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}


def get_or_404(rid):
    return Reminder.query.filter_by(id=rid, user_id=current_user.id).first_or_404()


def advance(rem, now):
    step = STEP.get(rem.repeat)
    if not step:
        return
    while rem.remind_at <= now:
        rem.remind_at += step
    rem.notified = False


def read_form(form):
    errors = []
    title = form.get("title", "").strip()
    if not title or len(title) > 200:
        errors.append("Enter a reminder title (up to 200 characters).")
    desc = form.get("description", "").strip()
    if len(desc) > 2000:
        errors.append("Description is too long.")
    repeat = form.get("repeat", "none")
    if repeat not in REPEATS:
        errors.append("Choose a valid repeat option.")
    when = None
    try:
        d, t = parse_date(form.get("date")), parse_time(form.get("time"))
        if not d or not t:
            errors.append("Choose a date and a time.")
        else:
            when = datetime.combine(d, t)
    except ValueError:
        errors.append("Enter a valid date and time.")
    return dict(title=title, description=desc, repeat=repeat, remind_at=when), errors


@bp.route("/")
@login_required
def index():
    flt = request.args.get("filter", "upcoming")
    now = now_local()
    base = Reminder.query.filter_by(user_id=current_user.id)
    if flt == "completed":
        items = base.filter(Reminder.is_done.is_(True)).order_by(Reminder.remind_at.desc()).all()
    elif flt == "due":
        items = base.filter(Reminder.is_done.is_(False), Reminder.remind_at <= now).order_by(Reminder.remind_at).all()
    elif flt == "all":
        items = base.order_by(Reminder.is_done, Reminder.remind_at).all()
    else:
        flt = "upcoming"
        items = base.filter(Reminder.is_done.is_(False), Reminder.remind_at > now).order_by(Reminder.remind_at).all()
    counts = {
        "upcoming": base.filter(Reminder.is_done.is_(False), Reminder.remind_at > now).count(),
        "due": base.filter(Reminder.is_done.is_(False), Reminder.remind_at <= now).count(),
        "completed": base.filter(Reminder.is_done.is_(True)).count(),
        "all": base.count(),
    }
    return render_template("reminders/list.html", items=items, flt=flt, counts=counts, now=now)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        data, errors = read_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("reminders/form.html", rem=None, form=request.form, repeats=REPEATS)
        db.session.add(Reminder(user_id=current_user.id, **data))
        log_activity(f"Added reminder: {data['title']}")
        db.session.commit()
        flash("Reminder added.", "success")
        return redirect(url_for("reminders.index"))
    return render_template("reminders/form.html", rem=None, form=None, repeats=REPEATS)


@bp.route("/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def edit(rid):
    rem = get_or_404(rid)
    if request.method == "POST":
        data, errors = read_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("reminders/form.html", rem=rem, form=request.form, repeats=REPEATS)
        for k, v in data.items():
            setattr(rem, k, v)
        rem.notified = False
        rem.is_done = False
        db.session.commit()
        flash("Reminder saved.", "success")
        return redirect(url_for("reminders.index"))
    return render_template("reminders/form.html", rem=rem, form=None, repeats=REPEATS)


@bp.route("/<int:rid>/toggle", methods=["POST"])
@login_required
def toggle(rid):
    rem = get_or_404(rid)
    now = now_local()
    if rem.repeat != "none" and not rem.is_done:
        step = STEP[rem.repeat]
        rem.remind_at += step
        while rem.remind_at <= now:
            rem.remind_at += step
        rem.notified = False
        flash(f"Marked as done. Next reminder: {fdatetime(rem.remind_at)}.", "success")
    else:
        rem.is_done = not rem.is_done
        if rem.is_done:
            rem.notified = True
            log_activity(f"Completed reminder: {rem.title}")
        else:
            rem.notified = False
    db.session.commit()
    return redirect(safe_next(request.form.get("next")) or url_for("reminders.index"))


@bp.route("/<int:rid>/delete", methods=["POST"])
@login_required
def delete(rid):
    db.session.delete(get_or_404(rid))
    db.session.commit()
    flash("Reminder deleted.", "success")
    return redirect(url_for("reminders.index"))


@bp.route("/due")
@login_required
def due():
    now = now_local()
    rows = Reminder.query.filter(Reminder.user_id == current_user.id, Reminder.is_done.is_(False),
                                 Reminder.notified.is_(False), Reminder.remind_at <= now).order_by(Reminder.remind_at).limit(10).all()
    return jsonify([{"id": r.id, "title": r.title, "body": r.description or "Reminder is due now."} for r in rows])


@bp.route("/<int:rid>/notified", methods=["POST"])
@login_required
def notified(rid):
    rem = get_or_404(rid)
    now = now_local()
    if rem.repeat != "none":
        advance(rem, now)
    else:
        rem.notified = True
    db.session.commit()
    return jsonify({"ok": True})
