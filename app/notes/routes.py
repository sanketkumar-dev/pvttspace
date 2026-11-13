from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import NOTE_CATEGORIES, Note
from app.utils import log_activity, now_local, safe_next

bp = Blueprint("notes", __name__, url_prefix="/notes")

MAX_TITLE = 200
MAX_CONTENT = 100000


def get_note_or_404(note_id):
    return Note.query.filter(Note.id == note_id, Note.user_id == current_user.id, Note.deleted_at.is_(None)).first_or_404()


@bp.route("/")
@login_required
def index():
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    q = Note.query.filter(Note.user_id == current_user.id, Note.deleted_at.is_(None))
    important_only = request.args.get("important") == "1"
    if important_only:
        q = q.filter(Note.is_important.is_(True))
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(Note.title.ilike(like), Note.content.ilike(like)))
    if category in NOTE_CATEGORIES:
        q = q.filter(Note.category == category)
    else:
        category = ""
    notes = q.order_by(Note.is_pinned.desc(), Note.updated_at.desc()).all()
    return render_template(
        "notes/list.html", notes=notes, search=search, category=category, categories=NOTE_CATEGORIES,
        important_only=important_only
    )


@bp.route("/quick", methods=["POST"])
@login_required
def quick():
    content = request.form.get("content", "").strip()
    if not content:
        flash("Write something before saving.", "danger")
    elif len(content) > MAX_CONTENT:
        flash("That note is too long.", "danger")
    else:
        first_line = content.splitlines()[0][:60]
        db.session.add(Note(user_id=current_user.id, title=first_line, content=content))
        log_activity(f"Added note: {first_line}")
        db.session.commit()
        flash("Note saved.", "success")
    return redirect(url_for("notes.index"))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category = request.form.get("category", "Personal")
        errors = []
        if not title and not content:
            errors.append("Add a title or some content.")
        if len(title) > MAX_TITLE:
            errors.append(f"Title must be {MAX_TITLE} characters or fewer.")
        if len(content) > MAX_CONTENT:
            errors.append("Content is too long.")
        if category not in NOTE_CATEGORIES:
            errors.append("Choose a valid category.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "notes/form.html", note=None, form=request.form, categories=NOTE_CATEGORIES
            )
        note = Note(
            user_id=current_user.id,
            title=title,
            content=content,
            category=category,
            is_important=bool(request.form.get("is_important")),
            is_pinned=bool(request.form.get("is_pinned")),
        )
        db.session.add(note)
        log_activity(f"Added note: {title or 'Untitled note'}")
        db.session.commit()
        flash("Note saved.", "success")
        return redirect(url_for("notes.edit", note_id=note.id))
    return render_template("notes/form.html", note=None, form=None, categories=NOTE_CATEGORIES)


@bp.route("/<int:note_id>", methods=["GET", "POST"])
@login_required
def edit(note_id):
    note = get_note_or_404(note_id)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        category = request.form.get("category", note.category)
        errors = []
        if len(title) > MAX_TITLE:
            errors.append(f"Title must be {MAX_TITLE} characters or fewer.")
        if len(content) > MAX_CONTENT:
            errors.append("Content is too long.")
        if category not in NOTE_CATEGORIES:
            errors.append("Choose a valid category.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "notes/form.html", note=note, form=request.form, categories=NOTE_CATEGORIES
            )
        note.title = title
        note.content = content
        note.category = category
        note.is_important = bool(request.form.get("is_important"))
        note.is_pinned = bool(request.form.get("is_pinned"))
        db.session.commit()
        flash("Note saved.", "success")
        return redirect(url_for("notes.edit", note_id=note.id))
    return render_template("notes/form.html", note=note, form=None, categories=NOTE_CATEGORIES)


@bp.route("/<int:note_id>/autosave", methods=["POST"])
@login_required
def autosave(note_id):
    note = get_note_or_404(note_id)
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()
    content = str(data.get("content", "")).strip()
    if len(title) > MAX_TITLE or len(content) > MAX_CONTENT:
        return jsonify({"saved": False, "error": "Too long"}), 400
    note.title = title
    note.content = content
    db.session.commit()
    return jsonify({"saved": True, "saved_at": now_local().strftime("%I:%M:%S %p").lstrip("0")})


@bp.route("/<int:note_id>/pin", methods=["POST"])
@login_required
def pin(note_id):
    note = get_note_or_404(note_id)
    note.is_pinned = not note.is_pinned
    db.session.commit()
    return redirect(safe_next(request.form.get("next")) or url_for("notes.index"))


@bp.route("/<int:note_id>/important", methods=["POST"])
@login_required
def important(note_id):
    note = get_note_or_404(note_id)
    note.is_important = not note.is_important
    db.session.commit()
    return redirect(safe_next(request.form.get("next")) or url_for("notes.index"))


@bp.route("/<int:note_id>/delete", methods=["POST"])
@login_required
def delete(note_id):
    note = get_note_or_404(note_id)
    note.deleted_at = now_local()
    log_activity(f"Moved note to recycle bin: {note.title or 'Untitled note'}")
    db.session.commit()
    flash("Note moved to the recycle bin.", "success")
    return redirect(url_for("notes.index"))
