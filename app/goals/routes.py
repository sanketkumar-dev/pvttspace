from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import GOAL_CATEGORIES, Goal, GoalTask
from app.utils import log_activity, now_local, parse_date, safe_next, today_local

bp = Blueprint("goals", __name__, url_prefix="/goals")


def get_goal_or_404(goal_id):
    return Goal.query.filter_by(id=goal_id, user_id=current_user.id).first_or_404()


def parse_lines(text, limit=100):
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return [ln[:200] for ln in lines[:limit]]


def add_steps(goal, lines, first_date=None):
    for i, line in enumerate(lines):
        due = first_date + timedelta(days=i) if first_date else None
        goal.subtasks.append(GoalTask(title=line, due_date=due))


def read_form(form):
    errors = []
    title = form.get("title", "").strip()
    if not title or len(title) > 200:
        errors.append("Enter a goal title (up to 200 characters).")
    category = form.get("category", "Personal")
    if category not in GOAL_CATEGORIES:
        errors.append("Choose a valid category.")
    desc = form.get("description", "").strip()
    target = form.get("daily_target", "").strip()
    if len(desc) > 5000 or len(target) > 200:
        errors.append("Description or daily target is too long.")
    start = end = None
    try:
        start = parse_date(form.get("start_date"))
        end = parse_date(form.get("end_date"))
    except ValueError:
        errors.append("Enter valid dates.")
    if start and end and end < start:
        errors.append("End date cannot be before start date.")
    return dict(title=title, category=category, description=desc, daily_target=target, start_date=start, end_date=end), errors


@bp.route("/")
@login_required
def index():
    view = request.args.get("view", "active")
    category = request.args.get("category", "")
    goals = Goal.query.filter_by(user_id=current_user.id).order_by(Goal.end_date.is_(None), Goal.end_date, Goal.id.desc()).all()
    if category in GOAL_CATEGORIES:
        goals = [g for g in goals if g.category == category]
    else:
        category = ""
    today = today_local()
    counts = {
        "active": sum(1 for g in goals if not g.completed),
        "completed": sum(1 for g in goals if g.completed),
        "all": len(goals),
    }
    if view == "completed":
        goals = [g for g in goals if g.completed]
    elif view == "all":
        pass
    else:
        view = "active"
        goals = [g for g in goals if not g.completed]
    return render_template("goals/list.html", goals=goals, view=view, category=category,
                           categories=GOAL_CATEGORIES, counts=counts, today=today)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        data, errors = read_form(request.form)
        lines = parse_lines(request.form.get("steps"))
        assign = bool(request.form.get("assign_daily"))
        if assign and not data["start_date"]:
            errors.append("Set a start date to assign one step per day.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("goals/form.html", goal=None, form=request.form, categories=GOAL_CATEGORIES)
        goal = Goal(user_id=current_user.id, **data)
        add_steps(goal, lines, data["start_date"] if assign else None)
        db.session.add(goal)
        log_activity(f"Created goal: {goal.title}")
        db.session.commit()
        flash("Goal created.", "success")
        return redirect(url_for("goals.detail", goal_id=goal.id))
    return render_template("goals/form.html", goal=None, form=None, categories=GOAL_CATEGORIES)


@bp.route("/<int:goal_id>")
@login_required
def detail(goal_id):
    goal = get_goal_or_404(goal_id)
    return render_template("goals/detail.html", goal=goal, today=today_local())


@bp.route("/<int:goal_id>/edit", methods=["GET", "POST"])
@login_required
def edit(goal_id):
    goal = get_goal_or_404(goal_id)
    if request.method == "POST":
        data, errors = read_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("goals/form.html", goal=goal, form=request.form, categories=GOAL_CATEGORIES)
        for k, v in data.items():
            setattr(goal, k, v)
        db.session.commit()
        flash("Goal saved.", "success")
        return redirect(url_for("goals.detail", goal_id=goal.id))
    return render_template("goals/form.html", goal=goal, form=None, categories=GOAL_CATEGORIES)


@bp.route("/<int:goal_id>/delete", methods=["POST"])
@login_required
def delete(goal_id):
    goal = get_goal_or_404(goal_id)
    log_activity(f"Deleted goal: {goal.title}")
    db.session.delete(goal)
    db.session.commit()
    flash("Goal deleted.", "success")
    return redirect(url_for("goals.index"))


@bp.route("/<int:goal_id>/complete", methods=["POST"])
@login_required
def toggle_goal(goal_id):
    goal = get_goal_or_404(goal_id)
    if goal.subtasks:
        flash("This goal completes automatically when all its steps are done.", "warning")
    else:
        goal.is_done = not goal.is_done
        if goal.is_done:
            log_activity(f"Completed goal: {goal.title}")
        db.session.commit()
    return redirect(safe_next(request.form.get("next")) or url_for("goals.detail", goal_id=goal.id))


@bp.route("/<int:goal_id>/steps", methods=["POST"])
@login_required
def add_step(goal_id):
    goal = get_goal_or_404(goal_id)
    lines = parse_lines(request.form.get("steps"))
    if not lines:
        flash("Write at least one step, one per line.", "danger")
        return redirect(url_for("goals.detail", goal_id=goal.id))
    first = None
    if request.form.get("assign_daily"):
        try:
            first = parse_date(request.form.get("first_date"))
        except ValueError:
            first = None
        if not first:
            flash("Choose a first date to assign one step per day.", "danger")
            return redirect(url_for("goals.detail", goal_id=goal.id))
    if len(goal.subtasks) + len(lines) > 500:
        flash("A goal can have at most 500 steps.", "danger")
        return redirect(url_for("goals.detail", goal_id=goal.id))
    add_steps(goal, lines, first)
    goal.is_done = False
    db.session.commit()
    flash(f"{len(lines)} step(s) added.", "success")
    return redirect(url_for("goals.detail", goal_id=goal.id))


def get_step_or_404(step_id):
    return (
        GoalTask.query.join(Goal, Goal.id == GoalTask.goal_id)
        .filter(GoalTask.id == step_id, Goal.user_id == current_user.id)
        .first_or_404()
    )


@bp.route("/steps/<int:step_id>/toggle", methods=["POST"])
@login_required
def toggle_step(step_id):
    step = get_step_or_404(step_id)
    step.is_done = not step.is_done
    step.completed_at = now_local() if step.is_done else None
    db.session.commit()
    return redirect(safe_next(request.form.get("next")) or url_for("goals.detail", goal_id=step.goal_id))


@bp.route("/steps/<int:step_id>/delete", methods=["POST"])
@login_required
def delete_step(step_id):
    step = get_step_or_404(step_id)
    gid = step.goal_id
    db.session.delete(step)
    db.session.commit()
    return redirect(url_for("goals.detail", goal_id=gid))
