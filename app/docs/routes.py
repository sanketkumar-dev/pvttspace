import os
import re
import uuid

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app import db
from app.models import DOC_CATEGORIES, Document, Folder
from app.utils import log_activity, now_local, safe_next

bp = Blueprint("docs", __name__, url_prefix="/docs")

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP = b"PK\x03\x04"
SIGNATURES = {
    "pdf": [b"%PDF"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],
    "doc": [OLE], "xls": [OLE], "ppt": [OLE],
    "docx": [ZIP], "xlsx": [ZIP], "pptx": [ZIP],
    "txt": [], "csv": [],
}
INLINE = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg",
    "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
}
DEFAULT_FOLDERS = {
    "College": ["Semester 1", "Semester 2", "Semester 3", "Assignments", "Practical Files"],
    "Personal": ["Certificates", "Identity Documents", "Important Forms"],
    "Projects": [],
    "Photos": [],
    "Other Documents": [],
}


def user_dir(user_id):
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def file_path(doc):
    return os.path.join(user_dir(doc.user_id), os.path.basename(doc.stored_name))


def clean_name(name):
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "", name).strip(" .")
    return name[:150]


def valid_content(ext, data):
    if ext not in SIGNATURES:
        return False
    if ext == "webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    sigs = SIGNATURES[ext]
    if sigs:
        return any(data.startswith(s) for s in sigs)
    return b"\x00" not in data[:2048]  # txt, csv


def storage_used(user_id):
    return db.session.query(db.func.coalesce(db.func.sum(Document.size), 0)).filter(Document.user_id == user_id).scalar()


def save_upload(user_id, display_name, data, folder_id, category):
    """Validate and store one file. Returns (Document or None, error or None)."""
    name = clean_name(display_name)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not name or ext not in SIGNATURES:
        return None, f"{name or 'File'}: this file type is not allowed."
    if len(data) == 0:
        return None, f"{name}: the file is empty."
    if len(data) > current_app.config["MAX_FILE_BYTES"]:
        return None, f"{name}: larger than 10 MB."
    if not valid_content(ext, data):
        return None, f"{name}: the content does not match a .{ext} file."
    if storage_used(user_id) + len(data) > current_app.config["USER_QUOTA_BYTES"]:
        return None, f"{name}: storage limit reached."
    stored = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(user_dir(user_id), stored), "wb") as f:
        f.write(data)
    doc = Document(user_id=user_id, folder_id=folder_id, original_name=name, stored_name=stored,
                   ext=ext, size=len(data), category=category)
    db.session.add(doc)
    return doc, None


def get_doc_or_404(doc_id, include_deleted=False):
    q = Document.query.filter_by(id=doc_id, user_id=current_user.id)
    if not include_deleted:
        q = q.filter(Document.deleted_at.is_(None))
    return q.first_or_404()


def get_folder_or_404(folder_id):
    return Folder.query.filter_by(id=folder_id, user_id=current_user.id).first_or_404()


def ensure_default_folders(user_id):
    if Folder.query.filter_by(user_id=user_id).first():
        return
    for top, subs in DEFAULT_FOLDERS.items():
        parent = Folder(user_id=user_id, name=top)
        db.session.add(parent)
        db.session.flush()
        for s in subs:
            db.session.add(Folder(user_id=user_id, name=s, parent_id=parent.id))
    db.session.commit()


def breadcrumb(folder):
    chain = []
    while folder and len(chain) < 20:
        chain.insert(0, folder)
        folder = db.session.get(Folder, folder.parent_id) if folder.parent_id else None
    return chain


def folder_choices(user_id):
    folders = Folder.query.filter_by(user_id=user_id).all()
    by_id = {f.id: f for f in folders}

    def path(f):
        parts, seen = [], 0
        while f and seen < 20:
            parts.insert(0, f.name)
            f = by_id.get(f.parent_id)
            seen += 1
        return " / ".join(parts)

    return sorted(((f.id, path(f)) for f in folders), key=lambda x: x[1].lower())


@bp.route("/")
@login_required
def index():
    ensure_default_folders(current_user.id)
    uid = current_user.id
    view = request.args.get("view", "")
    q = request.args.get("q", "").strip()
    folder = None
    if request.args.get("folder", "").isdigit():
        folder = get_folder_or_404(int(request.args["folder"]))

    files = Document.query.filter(Document.user_id == uid, Document.deleted_at.is_(None))
    folders = []
    if q:
        files = files.filter(Document.original_name.ilike(f"%{q}%"))
    elif view == "recent":
        files = files.order_by(Document.created_at.desc()).limit(20)
    elif view == "important":
        files = files.filter(Document.is_important.is_(True))
    else:
        view = ""
        files = files.filter(Document.folder_id == (folder.id if folder else None))
        folders = Folder.query.filter_by(user_id=uid, parent_id=folder.id if folder else None).order_by(Folder.name).all()
    if view != "recent":
        files = files.order_by(Document.created_at.desc())
    files = files.all()

    counts = {}
    for fid, n in db.session.query(Document.folder_id, db.func.count(Document.id)).filter(
        Document.user_id == uid, Document.deleted_at.is_(None)).group_by(Document.folder_id):
        counts[fid] = n
    return render_template(
        "docs/index.html", files=files, folders=folders, folder=folder, crumbs=breadcrumb(folder),
        view=view, q=q, categories=DOC_CATEGORIES, choices=folder_choices(uid), counts=counts,
        used=storage_used(uid), quota=current_app.config["USER_QUOTA_BYTES"],
    )


@bp.route("/upload", methods=["POST"])
@login_required
def upload():
    folder_id = request.form.get("folder_id", "")
    folder = get_folder_or_404(int(folder_id)) if folder_id.isdigit() else None
    category = request.form.get("category", "Other")
    if category not in DOC_CATEGORIES:
        category = "Other"
    uploaded = [f for f in request.files.getlist("files") if f and f.filename]
    if not uploaded:
        flash("Choose at least one file to upload.", "danger")
    ok = 0
    for f in uploaded[:20]:
        data = f.read(current_app.config["MAX_FILE_BYTES"] + 1)
        doc, err = save_upload(current_user.id, f.filename, data, folder.id if folder else None, category)
        if err:
            flash(err, "danger")
        else:
            ok += 1
    if ok:
        log_activity(f"Uploaded {ok} file(s)")
        db.session.commit()
        flash(f"{ok} file(s) uploaded.", "success")
    return redirect(url_for("docs.index", folder=folder.id if folder else None))


@bp.route("/file/<int:doc_id>/raw")
@login_required
def raw(doc_id):
    doc = get_doc_or_404(doc_id)
    mime = INLINE.get(doc.ext)
    if not mime or not os.path.exists(file_path(doc)):
        abort(404)
    return send_file(file_path(doc), mimetype=mime, as_attachment=False, download_name=doc.original_name)


@bp.route("/file/<int:doc_id>/view")
@login_required
def view(doc_id):
    doc = get_doc_or_404(doc_id)
    return render_template("docs/preview.html", doc=doc, previewable=doc.ext in INLINE)


@bp.route("/file/<int:doc_id>/download")
@login_required
def download(doc_id):
    doc = get_doc_or_404(doc_id)
    if not os.path.exists(file_path(doc)):
        abort(404)
    return send_file(file_path(doc), as_attachment=True, download_name=doc.original_name)


@bp.route("/file/<int:doc_id>/edit", methods=["GET", "POST"])
@login_required
def edit(doc_id):
    doc = get_doc_or_404(doc_id)
    choices = folder_choices(current_user.id)
    if request.method == "POST":
        name = clean_name(request.form.get("name"))
        base = name.rsplit(".", 1)[0] if "." in name else name
        errors = []
        if not base:
            errors.append("Enter a file name.")
        category = request.form.get("category", doc.category)
        if category not in DOC_CATEGORIES:
            errors.append("Choose a valid category.")
        fid = request.form.get("folder_id", "")
        folder = get_folder_or_404(int(fid)) if fid.isdigit() else None
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            doc.original_name = f"{base[:140]}.{doc.ext}"
            doc.category = category
            doc.folder_id = folder.id if folder else None
            doc.is_important = bool(request.form.get("is_important"))
            db.session.commit()
            flash("File saved.", "success")
            return redirect(url_for("docs.index", folder=doc.folder_id))
    return render_template("docs/edit.html", doc=doc, choices=choices, categories=DOC_CATEGORIES)


@bp.route("/file/<int:doc_id>/important", methods=["POST"])
@login_required
def important(doc_id):
    doc = get_doc_or_404(doc_id)
    doc.is_important = not doc.is_important
    db.session.commit()
    return redirect(safe_next(request.form.get("next")) or url_for("docs.index"))


@bp.route("/file/<int:doc_id>/delete", methods=["POST"])
@login_required
def delete(doc_id):
    doc = get_doc_or_404(doc_id)
    doc.deleted_at = now_local()
    log_activity(f"Moved file to recycle bin: {doc.original_name}")
    db.session.commit()
    flash("File moved to the recycle bin.", "success")
    return redirect(safe_next(request.form.get("next")) or url_for("docs.index", folder=doc.folder_id))


def folder_name(form):
    name = (form.get("name") or "").strip()
    return name if 0 < len(name) <= 100 and "/" not in name and "\\" not in name else None


@bp.route("/folder/new", methods=["POST"])
@login_required
def folder_new():
    name = folder_name(request.form)
    pid = request.form.get("parent_id", "")
    parent = get_folder_or_404(int(pid)) if pid.isdigit() else None
    if not name:
        flash("Enter a folder name (up to 100 characters, no slashes).", "danger")
    else:
        db.session.add(Folder(user_id=current_user.id, name=name, parent_id=parent.id if parent else None))
        db.session.commit()
        flash("Folder created.", "success")
    return redirect(url_for("docs.index", folder=parent.id if parent else None))


@bp.route("/folder/<int:folder_id>/rename", methods=["POST"])
@login_required
def folder_rename(folder_id):
    folder = get_folder_or_404(folder_id)
    name = folder_name(request.form)
    if not name:
        flash("Enter a folder name (up to 100 characters, no slashes).", "danger")
    else:
        folder.name = name
        db.session.commit()
        flash("Folder renamed.", "success")
    return redirect(url_for("docs.index", folder=folder.id))


@bp.route("/folder/<int:folder_id>/delete", methods=["POST"])
@login_required
def folder_delete(folder_id):
    folder = get_folder_or_404(folder_id)
    has_sub = Folder.query.filter_by(user_id=current_user.id, parent_id=folder.id).first()
    has_files = Document.query.filter(Document.user_id == current_user.id, Document.folder_id == folder.id,
                                      Document.deleted_at.is_(None)).first()
    if has_sub or has_files:
        flash("Only empty folders can be deleted. Move or delete what is inside first.", "danger")
        return redirect(url_for("docs.index", folder=folder.id))
    Document.query.filter_by(user_id=current_user.id, folder_id=folder.id).update({"folder_id": None})
    parent = folder.parent_id
    db.session.delete(folder)
    db.session.commit()
    flash("Folder deleted.", "success")
    return redirect(url_for("docs.index", folder=parent))
