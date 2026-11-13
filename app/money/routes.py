from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import EXPENSE_CATEGORIES, INCOME_CATEGORIES, Loan, Transaction
from app.utils import log_activity, parse_date, safe_next, to_paise, today_local, week_start

bp = Blueprint("money", __name__, url_prefix="/money")

CATS = {"expense": EXPENSE_CATEGORIES, "income": INCOME_CATEGORIES}


def get_tx_or_404(tx_id):
    return Transaction.query.filter_by(id=tx_id, user_id=current_user.id).first_or_404()


def sum_paise(uid, kind, start=None, end=None):
    q = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount_paise), 0)).filter(
        Transaction.user_id == uid, Transaction.kind == kind)
    if start:
        q = q.filter(Transaction.date >= start)
    if end:
        q = q.filter(Transaction.date <= end)
    return q.scalar()


def read_tx_form(form):
    errors = []
    kind = form.get("kind", "expense")
    if kind not in CATS:
        errors.append("Choose income or expense.")
        kind = "expense"
    category = form.get("category", "Other")
    if category not in CATS[kind]:
        errors.append("Choose a valid category.")
    try:
        amount = to_paise(form.get("amount", ""))
    except ValueError:
        amount = None
        errors.append("Enter an amount greater than 0 (up to 99,999,999.99).")
    try:
        d = parse_date(form.get("date")) or today_local()
    except ValueError:
        d = None
        errors.append("Enter a valid date.")
    note = form.get("note", "").strip()
    if len(note) > 200:
        errors.append("Note must be 200 characters or fewer.")
    return dict(kind=kind, category=category, amount_paise=amount, date=d, note=note), errors


@bp.route("/")
@login_required
def index():
    uid = current_user.id
    today = today_local()
    month = request.args.get("month", today.strftime("%Y-%m"))
    try:
        y, m = int(month[:4]), int(month[5:7])
        start = date(y, m, 1)
        end = date(y + (m == 12), (m % 12) + 1, 1)
    except (ValueError, IndexError):
        y, m = today.year, today.month
        start, end = date(y, m, 1), date(y + (m == 12), (m % 12) + 1, 1)
        month = today.strftime("%Y-%m")
    kind = request.args.get("kind", "")
    category = request.args.get("category", "")

    q = Transaction.query.filter(Transaction.user_id == uid, Transaction.date >= start, Transaction.date < end)
    if kind in CATS:
        q = q.filter(Transaction.kind == kind)
    if category:
        q = q.filter(Transaction.category == category)
    txs = q.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(300).all()

    month_income = sum_paise(uid, "income", start, end - timedelta(days=1))
    month_expense = sum_paise(uid, "expense", start, end - timedelta(days=1))
    total_income, total_expense = sum_paise(uid, "income"), sum_paise(uid, "expense")
    stats = {
        "today": sum_paise(uid, "expense", today, today),
        "week": sum_paise(uid, "expense", week_start(today), today),
        "month": sum_paise(uid, "expense", date(today.year, today.month, 1), today),
        "year": sum_paise(uid, "expense", date(today.year, 1, 1), today),
        "total_income": total_income,
        "total_expense": total_expense,
        "balance": total_income - total_expense,
        "month_income": month_income,
        "month_expense": month_expense,
    }
    owe = db.session.query(db.func.coalesce(db.func.sum(Loan.amount_paise), 0)).filter(
        Loan.user_id == uid, Loan.kind == "borrowed", Loan.is_settled.is_(False)).scalar()
    owed = db.session.query(db.func.coalesce(db.func.sum(Loan.amount_paise), 0)).filter(
        Loan.user_id == uid, Loan.kind == "lent", Loan.is_settled.is_(False)).scalar()
    return render_template("money/index.html", txs=txs, stats=stats, month=month, kind=kind, category=category,
                           all_categories=EXPENSE_CATEGORIES + [c for c in INCOME_CATEGORIES if c not in EXPENSE_CATEGORIES],
                           owe=owe, owed=owed)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        data, errors = read_tx_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("money/form.html", tx=None, form=request.form, cats=CATS, today=today_local())
        db.session.add(Transaction(user_id=current_user.id, **data))
        log_activity(f"Added {data['kind']}: {data['category']}")
        db.session.commit()
        flash("Transaction added.", "success")
        return redirect(url_for("money.index", month=data["date"].strftime("%Y-%m")))
    return render_template("money/form.html", tx=None, form=None, cats=CATS, today=today_local())


@bp.route("/<int:tx_id>/edit", methods=["GET", "POST"])
@login_required
def edit(tx_id):
    tx = get_tx_or_404(tx_id)
    if request.method == "POST":
        data, errors = read_tx_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("money/form.html", tx=tx, form=request.form, cats=CATS, today=today_local())
        for k, v in data.items():
            setattr(tx, k, v)
        db.session.commit()
        flash("Transaction saved.", "success")
        return redirect(url_for("money.index", month=tx.date.strftime("%Y-%m")))
    return render_template("money/form.html", tx=tx, form=None, cats=CATS, today=today_local())


@bp.route("/<int:tx_id>/delete", methods=["POST"])
@login_required
def delete(tx_id):
    tx = get_tx_or_404(tx_id)
    month = tx.date.strftime("%Y-%m")
    db.session.delete(tx)
    db.session.commit()
    flash("Transaction deleted.", "success")
    return redirect(url_for("money.index", month=month))


# Borrowed, lent and pending payments

def get_loan_or_404(loan_id):
    return Loan.query.filter_by(id=loan_id, user_id=current_user.id).first_or_404()


@bp.route("/loans", methods=["GET", "POST"])
@login_required
def loans():
    if request.method == "POST":
        f = request.form
        errors = []
        kind = f.get("kind", "")
        if kind not in ("borrowed", "lent"):
            errors.append("Choose borrowed or lent.")
        person = f.get("person", "").strip()
        if not person or len(person) > 100:
            errors.append("Enter the person's name (up to 100 characters).")
        try:
            amount = to_paise(f.get("amount", ""))
        except ValueError:
            amount = None
            errors.append("Enter an amount greater than 0.")
        try:
            d = parse_date(f.get("date")) or today_local()
            due = parse_date(f.get("due_date"))
        except ValueError:
            d = due = None
            errors.append("Enter valid dates.")
        note = f.get("note", "").strip()
        if len(note) > 200:
            errors.append("Note must be 200 characters or fewer.")
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            db.session.add(Loan(user_id=current_user.id, kind=kind, person=person, amount_paise=amount,
                                date=d, due_date=due, note=note))
            log_activity(f"Added {kind} money entry: {person}")
            db.session.commit()
            flash("Entry added.", "success")
            return redirect(url_for("money.loans"))
    items = Loan.query.filter_by(user_id=current_user.id).order_by(Loan.is_settled, Loan.due_date.is_(None), Loan.due_date, Loan.id.desc()).all()
    return render_template("money/loans.html", items=items, today=today_local(), form=request.form if request.method == "POST" else {})


@bp.route("/loans/<int:loan_id>/settle", methods=["POST"])
@login_required
def loan_settle(loan_id):
    loan = get_loan_or_404(loan_id)
    loan.is_settled = not loan.is_settled
    db.session.commit()
    return redirect(url_for("money.loans"))


@bp.route("/loans/<int:loan_id>/delete", methods=["POST"])
@login_required
def loan_delete(loan_id):
    db.session.delete(get_loan_or_404(loan_id))
    db.session.commit()
    flash("Entry deleted.", "success")
    return redirect(url_for("money.loans"))
