import smtplib
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from flask import current_app


def now_local():
    """Current local time (naive) in the configured timezone."""
    tz = ZoneInfo(current_app.config["TIMEZONE"])
    return datetime.now(tz).replace(tzinfo=None)


def today_local():
    return now_local().date()


def parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_time(value):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%H:%M").time()


def safe_next(target):
    """Allow only same-site relative paths for redirects."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


def week_start(d):
    return d - timedelta(days=d.weekday())


def fdate(value):
    return value.strftime("%d %b %Y") if value else ""


def ftime(value):
    return value.strftime("%I:%M %p").lstrip("0") if value else ""


def fdatetime(value):
    return value.strftime("%d %b %Y, %I:%M %p").lstrip("0") if value else ""


def to_paise(value):
    try:
        d = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise ValueError("bad amount")
    if not d.is_finite() or d <= 0 or d > Decimal("99999999.99"):
        raise ValueError("bad amount")
    return int((d * 100).quantize(Decimal("1")))


def inr(paise):
    paise = int(paise or 0)
    sign = "-" if paise < 0 else ""
    rupees, rest = divmod(abs(paise), 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return f"{sign}\u20b9{s}.{rest:02d}"


def percent(done, total):
    return round(done * 100 / total) if total else 0


def log_activity(text):
    from flask_login import current_user

    from app import db
    from app.models import ActivityLog

    db.session.add(ActivityLog(user_id=current_user.id, text=text[:255]))


def send_email(to, subject, body):
    cfg = current_app.config
    if not cfg["MAIL_SERVER"]:
        print(f"\n--- EMAIL (not sent, MAIL_SERVER not set) ---\nTo: {to}\nSubject: {subject}\n\n{body}\n---------------------------------------------\n", flush=True)
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["MAIL_FROM"], to, subject
    msg.set_content(body)
    with smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=15) as s:
        s.starttls()
        if cfg["MAIL_USERNAME"]:
            s.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
        s.send_message(msg)
    return True
