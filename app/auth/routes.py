import re

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import User
from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.utils import safe_next, send_email

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9 \-]{10,15}$")
MIN_PASSWORD = 8
MAX_PASSWORD = 128


def check_password_rules(password, confirm):
    errors = []
    if len(password) < MIN_PASSWORD:
        errors.append(f"Password must be at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        errors.append(f"Password must be at most {MAX_PASSWORD} characters.")
    if password != confirm:
        errors.append("Password and confirm password do not match.")
    return errors


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if not current_app.config["ALLOW_REGISTRATION"]:
        flash("New registrations are closed.", "warning")
        return redirect(url_for("auth.login"))

    form = {}
    if request.method == "POST":
        form = request.form
        name = form.get("full_name", "").strip()
        email = form.get("email", "").strip().lower()
        phone = form.get("phone", "").strip()
        password = form.get("password", "")
        confirm = form.get("confirm_password", "")

        errors = []
        if not name or len(name) > 100:
            errors.append("Enter your full name (up to 100 characters).")
        if not EMAIL_RE.match(email) or len(email) > 255:
            errors.append("Enter a valid email address.")
        if phone and not PHONE_RE.match(phone):
            errors.append("Enter a valid phone number or leave it empty.")
        errors += check_password_rules(password, confirm)
        if not errors and User.query.filter_by(email=email).first():
            errors.append("An account with this email already exists.")

        if not errors:
            user = User(full_name=name, email=email, phone=phone or None)
            user.set_password(password)
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors.append("An account with this email already exists.")
            else:
                login_user(user)
                session.permanent = True
                flash("Your account is ready.", "success")
                return redirect(url_for("main.dashboard"))

        for e in errors:
            flash(e, "danger")
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = {}
    if request.method == "POST":
        form = request.form
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=bool(form.get("remember")))
            session.permanent = True
            return redirect(safe_next(request.args.get("next")) or url_for("main.dashboard"))
        flash("Email or password is incorrect.", "danger")
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have logged out.", "success")
    return redirect(url_for("auth.login"))


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def make_reset_token(user):
    # The password hash fragment makes the link single use: it stops working once the password changes.
    return _serializer().dumps({"id": user.id, "h": user.password_hash[-12:]})


def read_reset_token(token):
    try:
        data = _serializer().loads(token, max_age=3600)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(User, data.get("id"))
    if user and user.password_hash[-12:] == data.get("h"):
        return user
    return None


@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            link = url_for("auth.reset_password", token=make_reset_token(user), _external=True)
            body = (f"Hello {user.full_name},\n\nUse this link to reset your {current_app.config['SITE_NAME']} password. "
                    f"It works once and expires in 1 hour:\n\n{link}\n\nIf you did not ask for this, ignore this email.")
            try:
                send_email(user.email, "Reset your password", body)
            except Exception:
                current_app.logger.exception("Could not send reset email")
        flash("If an account exists for that email, a reset link has been sent.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = read_reset_token(token)
    if not user:
        flash("This reset link is invalid or has expired. Request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        errors = check_password_rules(request.form.get("password", ""), request.form.get("confirm_password", ""))
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            user.set_password(request.form["password"])
            db.session.commit()
            flash("Password updated. Log in with your new password.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", token=token)