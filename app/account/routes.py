import io
import json
import os

import shutil
import uuid
import zipfile
from datetime import date, datetime, time

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required, logout_user

from app import db
from app.auth.routes import EMAIL_RE, PHONE_RE, check_password_rules
from app.docs.routes import INLINE, SIGNATURES, file_path, storage_used, user_dir, valid_content
from app.models import (REPEATS, STUDY_KINDS, PRIORITIES, ActivityLog, Document, Event, Folder, Goal, GoalTask, Loan, Note,
                        Reminder, StudyItem, Subject, SyllabusTopic, Task, Transaction, User)
from app.utils import now_local, safe_next

bp = Blueprint("account", __name__)

AVATAR_EXTS = {"png", "jpg", "jpeg", "webp"}
MAX_AVATAR = 2 * 1024 * 1024
MODELS = [
    ("folders", Folder), ("documents", Document), ("goals", Goal), ("goal_tasks", GoalTask),
    ("subjects", Subject), ("syllabus_topics", SyllabusTopic), ("study_items", StudyItem),
    ("notes", Note), ("tasks", Task), ("transactions", Transaction), ("loans", Loan),
    ("events", Event), ("reminders", Reminder),
]
FKS = {
    "folders": {"parent_id": "folders"}, "documents": {"folder_id": "folders"},
    "goal_tasks": {"goal_id": "goals"}, "syllabus_topics": {"subject_id": "subjects"},
    "study_items": {"subject_id": "subjects"},
}
CHECKS = {
    "transactions": lambda r: r.get("kind") in ("income", "expense") and isinstance(r.get("amount_paise"), int) and 0 < r["amount_paise"] <= 9999999999,
    "loans": lambda r: r.get("kind") in ("borrowed", "lent") and isinstance(r.get("amount_paise"), int) and 0 < r["amount_paise"] <= 9999999999,
    "reminders": lambda r: r.get("repeat", "none") in REPEATS,
    "study_items": lambda r: r.get("kind") in STUDY_KINDS,
    "tasks": lambda r: r.get("priority", "Medium") in PRIORITIES,
}


# ---------- profile ----------

@bp.route("/profile")
@login_required
def profile():
    return render_template("account/profile.html")


@bp.route("/profile/update", methods=["POST"])
@login_required
def update_profile():
    name = request.form.get("full_name", "").strip()
    phone = request.form.get("phone", "").strip()
    errors = []
    if not name or len(name) > 100:
        errors.append("Enter your full name (up to 100 characters).")
    if phone and not PHONE_RE.match(phone):
        errors.append("Enter a valid phone number or leave it empty.")
    if errors:
        for e in errors:
            flash(e, "danger")
    else:
        current_user.full_name, current_user.phone = name, phone or None
        db.session.commit()
        flash("Profile saved.", "success")
    return redirect(url_for("account.profile"))


@bp.route("/profile/password", methods=["POST"])
@login_required
def change_password():
    errors = []
    if not current_user.check_password(request.form.get("current_password", "")):
        errors.append("Current password is incorrect.")
    errors += check_password_rules(request.form.get("new_password", ""), request.form.get("confirm_password", ""))
    if errors:
        for e in errors:
            flash(e, "danger")
    else:
        current_user.set_password(request.form["new_password"])
        db.session.commit()
        flash("Password changed.", "success")
    return redirect(url_for("account.profile"))


def remove_avatar_file(user):
    if user.avatar:
        try:
            os.remove(os.path.join(user_dir(user.id), os.path.basename(user.avatar)))
        except OSError:
            pass
        user.avatar = None


@bp.route("/profile/picture", methods=["GET", "POST"])
@login_required
def picture():
    if request.method == "POST":
        f = request.files.get("picture")
        if not f or not f.filename:
            flash("Choose an image first.", "danger")
            return redirect(url_for("account.profile"))
        data = f.read(MAX_AVATAR + 1)
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in AVATAR_EXTS or not valid_content(ext, data):
            flash("Use a PNG, JPG or WebP image.", "danger")
        elif len(data) > MAX_AVATAR:
            flash("The picture must be 2 MB or smaller.", "danger")
        else:
            remove_avatar_file(current_user)
            name = f"avatar_{uuid.uuid4().hex}.{ext}"
            with open(os.path.join(user_dir(current_user.id), name), "wb") as out:
                out.write(data)
            current_user.avatar = name
            db.session.commit()
            flash("Profile picture updated.", "success")
        return redirect(url_for("account.profile"))
    if not current_user.avatar:
        abort(404)
    path = os.path.join(user_dir(current_user.id), os.path.basename(current_user.avatar))
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype=INLINE.get(current_user.avatar.rsplit(".", 1)[-1], "application/octet-stream"))


@bp.route("/profile/picture/remove", methods=["POST"])
@login_required
def picture_remove():
    remove_avatar_file(current_user)
    db.session.commit()
    flash("Profile picture removed.", "success")
    return redirect(url_for("account.profile"))


# ---------- settings ----------

@bp.route("/settings")
@login_required
def settings():
    return render_template("account/settings.html", used=storage_used(current_user.id),
                           quota=current_app.config["USER_QUOTA_BYTES"])


@bp.route("/settings/theme", methods=["POST"])
@login_required
def set_theme():
    value = request.form.get("value", "")
    if value in ("light", "dark", "system"):
        current_user.theme = value
        db.session.commit()
    return redirect(safe_next(request.form.get("next")) or url_for("account.settings"))


@bp.route("/settings/privacy", methods=["POST"])
@login_required
def set_privacy():
    current_user.hide_email = bool(request.form.get("hide_email"))
    current_user.reminder_notifications = bool(request.form.get("reminder_notifications"))
    db.session.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("account.settings"))


@bp.route("/settings/email", methods=["POST"])
@login_required
def change_email():
    email = request.form.get("email", "").strip().lower()
    if not current_user.check_password(request.form.get("password", "")):
        flash("Password is incorrect.", "danger")
    elif not EMAIL_RE.match(email) or len(email) > 255:
        flash("Enter a valid email address.", "danger")
    elif User.query.filter(User.email == email, User.id != current_user.id).first():
        flash("That email is already used by another account.", "danger")
    else:
        current_user.email = email
        db.session.commit()
        flash("Email updated.", "success")
    return redirect(url_for("account.settings"))


# ---------- export, backup, restore ----------

def iso(v):
    return v.isoformat() if isinstance(v, (date, datetime, time)) else v


def user_rows(uid, name, model):
    if name == "goal_tasks":
        q = GoalTask.query.join(Goal, Goal.id == GoalTask.goal_id).filter(Goal.user_id == uid)
    elif name == "syllabus_topics":
        q = SyllabusTopic.query.join(Subject, Subject.id == SyllabusTopic.subject_id).filter(Subject.user_id == uid)
    else:
        q = model.query.filter_by(user_id=uid)
    return q.order_by(model.id).all()


def collect(uid):
    tables = {}
    for name, model in MODELS:
        cols = [c.name for c in model.__table__.columns if c.name != "user_id"]
        tables[name] = [{c: iso(getattr(r, c)) for c in cols} for r in user_rows(uid, name, model)]
    return {"app": "PVTTSpace", "version": 1, "exported_at": now_local().isoformat(), "tables": tables}


@bp.route("/settings/export.json")
@login_required
def export_json():
    data = collect(current_user.id)
    buf = io.BytesIO(json.dumps(data, indent=2).encode("utf-8"))
    return send_file(buf, mimetype="application/json", as_attachment=True,
                     download_name=f"pvttspace-data-{now_local().strftime('%Y%m%d')}.json")


@bp.route("/settings/backup.zip")
@login_required
def backup_zip():
    data = collect(current_user.id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data.json", json.dumps(data, indent=2))
        for d in Document.query.filter_by(user_id=current_user.id):
            p = file_path(d)
            if os.path.exists(p):
                z.write(p, f"files/{d.stored_name}")
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"pvttspace-backup-{now_local().strftime('%Y%m%d')}.zip")


def convert(col, val):
    if val is None:
        return None
    t = col.type.python_type
    if t is datetime:
        return datetime.fromisoformat(val)
    if t is date:
        return date.fromisoformat(val)
    if t is time:
        return time.fromisoformat(val)
    if t is bool:
        return bool(val)
    if t is int:
        return int(val)
    s = str(val)
    length = getattr(col.type, "length", None)
    return s[:length] if length else s


def restore_backup(uid, z):
    info = z.getinfo("data.json")
    if info.file_size > 20 * 1024 * 1024:
        raise ValueError("data.json is too large")
    payload = json.loads(z.read("data.json").decode("utf-8"))
    if payload.get("app") != "PVTTSpace" or payload.get("version") != 1:
        raise ValueError("This is not a PVTTSpace backup")
    tables = payload.get("tables", {})
    idmap = {name: {} for name, _ in MODELS}
    added = skipped = 0
    max_file = current_app.config["MAX_FILE_BYTES"]

    for name, model in MODELS:
        rows = tables.get(name, [])
        if not isinstance(rows, list):
            continue
        cols = {c.name: c for c in model.__table__.columns}
        for raw in rows[:20000]:
            if not isinstance(raw, dict):
                skipped += 1
                continue
            written = None
            try:
                row = {}
                for cname, col in cols.items():
                    if cname in ("id", "user_id") or cname not in raw:
                        continue
                    row[cname] = convert(col, raw[cname])
                for cname, col in cols.items():
                    if (cname not in row and cname not in ("id", "user_id") and not col.nullable
                            and col.default is None and col.server_default is None and not col.primary_key
                            and not (name == "documents" and cname in ("stored_name", "size"))):
                        raise ValueError("missing " + cname)
                if name in CHECKS and not CHECKS[name](row):
                    raise ValueError("invalid row")
                for fk, target in FKS.get(name, {}).items():
                    old = row.pop(fk, None)
                    if old is not None:
                        row[fk] = idmap[target].get(old)
                        if row[fk] is None and name in ("goal_tasks", "syllabus_topics"):
                            raise ValueError("orphan row")
                if name == "folders":
                    row["parent_id"] = None
                if name in ("goals", "subjects", "folders", "documents", "notes", "tasks", "transactions", "loans",
                            "events", "reminders", "study_items"):
                    row["user_id"] = uid
                if name == "documents":
                    stored = os.path.basename(str(raw.get("stored_name", "")))
                    ext = str(raw.get("ext", "")).lower()
                    member = f"files/{stored}"
                    if ext not in SIGNATURES or member not in z.namelist():
                        raise ValueError("missing file")
                    if z.getinfo(member).file_size > max_file:
                        raise ValueError("file too large")
                    data = z.read(member)
                    if not valid_content(ext, data) or storage_used(uid) + len(data) > current_app.config["USER_QUOTA_BYTES"]:
                        raise ValueError("file rejected")
                    new_name = f"{uuid.uuid4().hex}.{ext}"
                    written = os.path.join(user_dir(uid), new_name)
                    with open(written, "wb") as out:
                        out.write(data)
                    row["stored_name"], row["size"] = new_name, len(data)
                with db.session.begin_nested():
                    obj = model(**row)
                    db.session.add(obj)
                    db.session.flush()
                idmap[name][raw.get("id")] = obj.id
                added += 1
            except Exception:
                skipped += 1
                if written and os.path.exists(written):
                    os.remove(written)
        if name == "folders":  # second pass: link parents
            for raw in rows[:20000]:
                if not isinstance(raw, dict):
                    continue
                new_id = idmap["folders"].get(raw.get("id"))
                new_parent = idmap["folders"].get(raw.get("parent_id"))
                if new_id and new_parent and new_id != new_parent:
                    db.session.get(Folder, new_id).parent_id = new_parent
    db.session.commit()
    return added, skipped


@bp.route("/settings/restore", methods=["POST"])
@login_required
def restore():
    f = request.files.get("backup")
    if not f or not f.filename:
        flash("Choose a backup .zip file.", "danger")
        return redirect(url_for("account.settings"))
    try:
        z = zipfile.ZipFile(io.BytesIO(f.read()))
        if sum(i.file_size for i in z.infolist()) > 300 * 1024 * 1024:
            raise ValueError("The backup is too large")
        added, skipped = restore_backup(current_user.id, z)
    except (zipfile.BadZipFile, KeyError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        db.session.rollback()
        flash(f"Could not restore: {e if isinstance(e, ValueError) else 'the file is not a valid PVTTSpace backup'}.", "danger")
    else:
        flash(f"Restored {added} item(s)." + (f" Skipped {skipped} item(s) that were invalid." if skipped else ""), "success")
    return redirect(url_for("account.settings"))


# ---------- delete account ----------

@bp.route("/settings/delete-account", methods=["POST"])
@login_required
def delete_account():
    if not current_user.check_password(request.form.get("del_password", "")) or request.form.get("confirm") != "DELETE":
        flash("Enter your password and type DELETE to confirm.", "danger")
        return redirect(url_for("account.settings"))
    uid = current_user.id
    user = db.session.get(User, uid)
    logout_user()
    StudyItem.query.filter_by(user_id=uid).delete()
    for g in Goal.query.filter_by(user_id=uid):
        db.session.delete(g)
    for s in Subject.query.filter_by(user_id=uid):
        db.session.delete(s)
    Document.query.filter_by(user_id=uid).delete()
    Folder.query.filter_by(user_id=uid).update({"parent_id": None})
    for model in (Folder, Note, Task, Transaction, Loan, Event, Reminder, ActivityLog):
        model.query.filter_by(user_id=uid).delete()
    db.session.delete(user)
    db.session.commit()
    shutil.rmtree(os.path.join(current_app.config["UPLOAD_FOLDER"], str(uid)), ignore_errors=True)
    flash("Your account and all its data were deleted.", "success")
    return redirect(url_for("auth.login"))
