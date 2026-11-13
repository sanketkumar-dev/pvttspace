
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect


# ==========================================
# Initialize Flask Extensions
# ==========================================

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()


# ==========================================
# Application Factory
# ==========================================

def create_app():

    app = Flask(__name__)

    # Load application configuration
    app.config.from_object("config.Config")

    # Initialize extensions
    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    # Initialize CSRF protection
    csrf.init_app(app)

    from app.utils import fdate, fdatetime, ftime, inr, today_local

    app.add_template_filter(fdate, "fdate")
    app.add_template_filter(ftime, "ftime")
    app.add_template_filter(fdatetime, "fdatetime")
    app.add_template_filter(inr, "inr")

    @app.context_processor
    def inject_template_context():
        return {
            "site_name": app.config["SITE_NAME"],
            "tagline": app.config["TAGLINE"],
            "theme": current_user.theme if current_user.is_authenticated else "light",
            "today_iso": today_local().isoformat(),
        }

    # ======================================
    # Import Models
    # ======================================

    from app import models

    # ======================================
    # Import Blueprints
    # ======================================

    from app.auth.routes import bp as auth_bp
    from app.main.routes import bp as main_bp
    from app.account.routes import bp as account_bp
    from app.analytics.routes import bp as analytics_bp
    from app.calendar.routes import bp as calendar_bp
    from app.docs.routes import bp as docs_bp
    from app.goals.routes import bp as goals_bp
    from app.money.routes import bp as money_bp
    from app.notes.routes import bp as notes_bp
    from app.reminders.routes import bp as reminders_bp
    from app.study.routes import bp as study_bp
    from app.tasks.routes import bp as tasks_bp

    # ======================================
    # Register Blueprints
    # ======================================

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(docs_bp)
    app.register_blueprint(goals_bp)
    app.register_blueprint(money_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(reminders_bp)
    app.register_blueprint(study_bp)
    app.register_blueprint(tasks_bp)

    # ======================================
    # Database Initialization
    # ======================================

    with app.app_context():

        # Create missing database tables
        db.create_all()

        # Apply existing database schema upgrades
        from app.migrate import upgrade_schema
        upgrade_schema()

    return app
