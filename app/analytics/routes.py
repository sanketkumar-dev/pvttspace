from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from app.datasets import DATASETS

bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@bp.route("/")
@login_required
def index():
    options = [(k, v[1], v[2]) for k, v in DATASETS.items()]
    return render_template("analytics/index.html", options=options)


@bp.route("/data")
@login_required
def data():
    key = request.args.get("dataset", "")
    if key not in DATASETS:
        return jsonify({"error": "Unknown dataset"}), 400
    try:
        days = int(request.args.get("days", "14"))
    except ValueError:
        days = 14
    days = max(3, min(days, 365))
    fn, title, default_type = DATASETS[key]
    result = fn(current_user.id, days)
    result["title"] = title
    return jsonify(result)
