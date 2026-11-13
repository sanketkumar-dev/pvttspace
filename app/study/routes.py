from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import STUDY_KINDS, StudyItem, Subject, SyllabusTopic
from app.utils import log_activity, now_local, parse_date, percent, safe_next

bp = Blueprint("study", __name__, url_prefix="/study")


def get_subject_or_404(sid):
    return Subject.query.filter_by(id=sid, user_id=current_user.id).first_or_404()


def get_topic_or_404(tid):
    return (SyllabusTopic.query.join(Subject, Subject.id == SyllabusTopic.subject_id)
            .filter(SyllabusTopic.id == tid, Subject.user_id == current_user.id).first_or_404())


def read_subject(form):
    errors = []
    name = form.get("name", "").strip()
    if not name or len(name) > 150:
        errors.append("Enter a subject name (up to 150 characters).")
    try:
        sem = int(form.get("semester", "1"))
        if not 1 <= sem <= 8:
            raise ValueError
    except ValueError:
        sem = 1
        errors.append("Semester must be between 1 and 8.")
    return dict(name=name, semester=sem), errors


@bp.route("/")
@login_required
def index():
    subjects = Subject.query.filter_by(user_id=current_user.id).order_by(Subject.semester, Subject.name).all()
    sems = {}
    for s in subjects:
        d = sems.setdefault(s.semester, {"subjects": [], "total": 0, "done": 0})
        d["subjects"].append(s)
        d["total"] += s.total
        d["done"] += s.done_count
    for d in sems.values():
        d["percent"] = percent(d["done"], d["total"])
    total = sum(s.total for s in subjects)
    done = sum(s.done_count for s in subjects)
    return render_template("study/index.html", sems=dict(sorted(sems.items())), overall=percent(done, total),
                           total=total, done=done, has_subjects=bool(subjects))


@bp.route("/subjects/new", methods=["GET", "POST"])
@login_required
def subject_new():
    if request.method == "POST":
        data, errors = read_subject(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("study/subject_form.html", subject=None, form=request.form)
        s = Subject(user_id=current_user.id, **data)
        db.session.add(s)
        log_activity(f"Added subject: {s.name}")
        db.session.commit()
        flash("Subject added. Add units and topics next.", "success")
        return redirect(url_for("study.subject", sid=s.id))
    return render_template("study/subject_form.html", subject=None, form=None)


@bp.route("/subjects/<int:sid>/edit", methods=["GET", "POST"])
@login_required
def subject_edit(sid):
    s = get_subject_or_404(sid)
    if request.method == "POST":
        data, errors = read_subject(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("study/subject_form.html", subject=s, form=request.form)
        s.name, s.semester = data["name"], data["semester"]
        db.session.commit()
        flash("Subject saved.", "success")
        return redirect(url_for("study.subject", sid=s.id))
    return render_template("study/subject_form.html", subject=s, form=None)


@bp.route("/subjects/<int:sid>/delete", methods=["POST"])
@login_required
def subject_delete(sid):
    s = get_subject_or_404(sid)
    StudyItem.query.filter_by(subject_id=s.id).update({"subject_id": None})
    log_activity(f"Deleted subject: {s.name}")
    db.session.delete(s)
    db.session.commit()
    flash("Subject deleted.", "success")
    return redirect(url_for("study.index"))


@bp.route("/subjects/<int:sid>")
@login_required
def subject(sid):
    s = get_subject_or_404(sid)
    units = {}
    for t in s.topics:
        u = units.setdefault(t.unit or "General", {})
        u.setdefault(t.chapter or "", []).append(t)
    unit_list = []
    for uname, chapters in units.items():
        topics = [t for ch in chapters.values() for t in ch]
        unit_list.append({
            "name": uname,
            "percent": percent(sum(1 for t in topics if t.is_done), len(topics)),
            "done": sum(1 for t in topics if t.is_done), "total": len(topics),
            "chapters": [{"name": cn, "topics": ts} for cn, ts in chapters.items()],
        })
    return render_template("study/subject.html", s=s, units=unit_list, unit_names=list(units.keys()))


@bp.route("/subjects/<int:sid>/topics", methods=["POST"])
@login_required
def topics_add(sid):
    s = get_subject_or_404(sid)
    unit = request.form.get("unit", "").strip()[:100]
    chapter = request.form.get("chapter", "").strip()[:100]
    lines = [ln.strip()[:200] for ln in request.form.get("topics", "").splitlines() if ln.strip()]
    if not lines:
        flash("Write at least one topic, one per line.", "danger")
    elif len(s.topics) + len(lines) > 1000:
        flash("A subject can have at most 1000 topics.", "danger")
    else:
        for ln in lines[:200]:
            s.topics.append(SyllabusTopic(unit=unit, chapter=chapter, title=ln))
        db.session.commit()
        flash(f"{min(len(lines), 200)} topic(s) added.", "success")
    return redirect(url_for("study.subject", sid=s.id))


@bp.route("/topics/<int:tid>/toggle", methods=["POST"])
@login_required
def topic_toggle(tid):
    t = get_topic_or_404(tid)
    t.is_done = not t.is_done
    t.completed_at = now_local() if t.is_done else None
    db.session.commit()
    return redirect(safe_next(request.form.get("next")) or url_for("study.subject", sid=t.subject_id))


@bp.route("/topics/<int:tid>/delete", methods=["POST"])
@login_required
def topic_delete(tid):
    t = get_topic_or_404(tid)
    sid = t.subject_id
    db.session.delete(t)
    db.session.commit()
    return redirect(url_for("study.subject", sid=sid))


# Practical, assignment, PYQ and exam preparation trackers

def get_item_or_404(iid):
    return StudyItem.query.filter_by(id=iid, user_id=current_user.id).first_or_404()


@bp.route("/tracker", methods=["GET", "POST"])
@login_required
def tracker():
    kind = request.args.get("kind", "Practical")
    if kind not in STUDY_KINDS:
        kind = "Practical"
    subjects = Subject.query.filter_by(user_id=current_user.id).order_by(Subject.name).all()
    if request.method == "POST":
        f = request.form
        errors = []
        kind = f.get("kind", kind)
        if kind not in STUDY_KINDS:
            errors.append("Choose a valid tracker.")
            kind = "Practical"
        title = f.get("title", "").strip()
        if not title or len(title) > 200:
            errors.append("Enter a title (up to 200 characters).")
        sid = f.get("subject_id", "")
        subject = None
        if sid.isdigit():
            subject = Subject.query.filter_by(id=int(sid), user_id=current_user.id).first()
            if not subject:
                errors.append("Choose a valid subject.")
        try:
            due = parse_date(f.get("due_date"))
        except ValueError:
            due = None
            errors.append("Enter a valid due date.")
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            db.session.add(StudyItem(user_id=current_user.id, kind=kind, title=title,
                                     subject_id=subject.id if subject else None, due_date=due))
            log_activity(f"Added {kind} item: {title}")
            db.session.commit()
            flash("Added.", "success")
        return redirect(url_for("study.tracker", kind=kind))
    all_items = StudyItem.query.filter_by(user_id=current_user.id).all()
    counts = {k: [sum(1 for i in all_items if i.kind == k and i.is_done), sum(1 for i in all_items if i.kind == k)] for k in STUDY_KINDS}
    items = (StudyItem.query.filter_by(user_id=current_user.id, kind=kind)
             .order_by(StudyItem.is_done, StudyItem.due_date.is_(None), StudyItem.due_date, StudyItem.id.desc()).all())
    return render_template("study/tracker.html", kind=kind, kinds=STUDY_KINDS, items=items, counts=counts, subjects=subjects)


@bp.route("/items/<int:iid>/toggle", methods=["POST"])
@login_required
def item_toggle(iid):
    i = get_item_or_404(iid)
    i.is_done = not i.is_done
    i.completed_at = now_local() if i.is_done else None
    db.session.commit()
    return redirect(url_for("study.tracker", kind=i.kind))


@bp.route("/items/<int:iid>/delete", methods=["POST"])
@login_required
def item_delete(iid):
    i = get_item_or_404(iid)
    kind = i.kind
    db.session.delete(i)
    db.session.commit()
    return redirect(url_for("study.tracker", kind=kind))
