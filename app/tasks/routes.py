
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import PRIORITIES, TASK_CATEGORIES, Task
from datetime import timedelta

from app.streak import compute_streak
from app.utils import log_activity, now_local, parse_date, parse_time, safe_next, week_start

bp = Blueprint("tasks", __name__, url_prefix="/tasks")

FILTERS = ["all", "today", "week", "month", "pending", "completed", "overdue"]


def month_end(d):
    nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def get_task_or_404(task_id):
    return Task.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()


def read_form(form):
    errors = []
    title = form.get("title", "").strip()
    if not title:
        errors.append("Enter a task title.")
    if len(title) > 200:
        errors.append("Title must be 200 characters or fewer.")
    description = form.get("description", "").strip()
    if len(description) > 5000:
        errors.append("Description must be 5000 characters or fewer.")
    priority = form.get("priority", "Medium")
    if priority not in PRIORITIES:
        errors.append("Choose a valid priority.")
    category = form.get("category", "Personal")
    if category not in TASK_CATEGORIES:
        errors.append("Choose a valid category.")
    try:
        due_date = parse_date(form.get("due_date"))
    except ValueError:
        due_date = None
        errors.append("Enter a valid due date.")
    try:
        due_time = parse_time(form.get("due_time"))
    except ValueError:
        due_time = None
        errors.append("Enter a valid due time.")
    data = dict(
        title=title,
        description=description,
        priority=priority,
        category=category,
        due_date=due_date,
        due_time=due_time,
    )
    return data, errors


@bp.route("/")
@login_required
def index():
    flt = request.args.get("filter", "all")
    if flt not in FILTERS:
        flt = "all"
    today = now_local().date()
    base = Task.query.filter_by(user_id=current_user.id)

    counts = {
        "all": base.count(),
        "today": base.filter(Task.due_date == today).count(),
        "week": base.filter(Task.due_date >= week_start(today), Task.due_date <= week_start(today) + timedelta(days=6)).count(),
        "month": base.filter(Task.due_date >= today.replace(day=1), Task.due_date <= month_end(today)).count(),
        "pending": base.filter(Task.is_done.is_(False)).count(),
        "completed": base.filter(Task.is_done.is_(True)).count(),
        "overdue": base.filter(Task.is_done.is_(False), Task.due_date < today).count(),
    }

    q = base
    if flt == "today":
        q = q.filter(Task.due_date == today)
    elif flt == "week":
        q = q.filter(Task.due_date >= week_start(today), Task.due_date <= week_start(today) + timedelta(days=6))
    elif flt == "month":
        q = q.filter(Task.due_date >= today.replace(day=1), Task.due_date <= month_end(today))
    elif flt == "pending":
        q = q.filter(Task.is_done.is_(False))
    elif flt == "completed":
        q = q.filter(Task.is_done.is_(True))
    elif flt == "overdue":
        q = q.filter(Task.is_done.is_(False), Task.due_date < today)

    tasks = q.order_by(
        Task.is_done,
        Task.due_date.is_(None),
        Task.due_date,
        Task.due_time.is_(None),
        Task.due_time,
        Task.id.desc(),
    ).all()
    return render_template("tasks/list.html", tasks=tasks, flt=flt, counts=counts, today=today,
                           streak=compute_streak(current_user.id, today))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        data, errors = read_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "tasks/form.html", task=None, form=request.form,
                priorities=PRIORITIES, categories=TASK_CATEGORIES,
            )
        db.session.add(Task(user_id=current_user.id, **data))
        log_activity(f"Added task: {data['title']}")
        db.session.commit()
        flash("Task added.", "success")
        return redirect(url_for("tasks.index"))
    return render_template(
        "tasks/form.html", task=None, form=None,
        priorities=PRIORITIES, categories=TASK_CATEGORIES,
    )


@bp.route("/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit(task_id):
    task = get_task_or_404(task_id)
    if request.method == "POST":
        data, errors = read_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "tasks/form.html", task=task, form=request.form,
                priorities=PRIORITIES, categories=TASK_CATEGORIES,
            )
        for key, value in data.items():
            setattr(task, key, value)
        db.session.commit()
        flash("Task saved.", "success")
        return redirect(url_for("tasks.index"))
    return render_template(
        "tasks/form.html", task=task, form=None,
        priorities=PRIORITIES, categories=TASK_CATEGORIES,
    )


@bp.route("/<int:task_id>/toggle", methods=["POST"])
@login_required
def toggle(task_id):
    task = get_task_or_404(task_id)
    task.is_done = not task.is_done
    task.completed_at = now_local() if task.is_done else None
    if task.is_done:
        log_activity(f"Completed task: {task.title}")
    db.session.commit()
    return redirect(safe_next(request.form.get("next")) or url_for("tasks.index"))


@bp.route("/<int:task_id>/delete", methods=["POST"])
@login_required
def delete(task_id):
    task = get_task_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    flash("Task deleted.", "success")
    return redirect(safe_next(request.form.get("next")) or url_for("tasks.index"))
