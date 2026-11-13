from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app import db, login_manager
from app.utils import now_local

NOTE_CATEGORIES = ["Personal", "College", "Ideas", "To-do"]
TASK_CATEGORIES = ["College", "Assignment", "Personal", "Work", "Other"]
PRIORITIES = ["Low", "Medium", "High"]
GOAL_CATEGORIES = ["Daily", "Weekly", "Monthly", "Yearly", "Custom", "Personal", "Academic", "Fitness", "Career"]
DOC_CATEGORIES = ["Certificate", "Assignment", "Notes", "Identity", "Form", "Project", "Photo", "Other"]
EXPENSE_CATEGORIES = ["Food", "Travel", "Education", "Shopping", "Recharge", "Entertainment", "Personal", "Other"]
INCOME_CATEGORIES = ["Pocket money", "Salary", "Stipend", "Gift", "Other"]
EVENT_CATEGORIES = ["College holiday", "College event", "Exam date", "Assignment submission", "Personal event", "Birthday", "Important date"]
REPEATS = ["none", "daily", "weekly"]
STUDY_KINDS = ["Practical", "Assignment", "PYQ", "Exam prep"]


def _created():
    return db.Column(db.DateTime, default=now_local, nullable=False)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20))
    password_hash = db.Column(db.String(255), nullable=False)
    theme = db.Column(db.String(10), nullable=False, default="light", server_default="light")
    hide_email = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    reminder_notifications = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    avatar = db.Column(db.String(255))
    created_at = _created()

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def initials(self):
        parts = self.full_name.split()
        return "".join(p[0] for p in parts[:2]).upper() or "U"


class Note(db.Model):
    __tablename__ = "notes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False, default="")
    content = db.Column(db.Text, nullable=False, default="")
    category = db.Column(db.String(30), nullable=False, default="Personal")
    is_pinned = db.Column(db.Boolean, nullable=False, default=False)
    is_important = db.Column(db.Boolean, nullable=False, default=False)
    created_at = _created()
    updated_at = db.Column(db.DateTime, default=now_local, onupdate=now_local, nullable=False)
    deleted_at = db.Column(db.DateTime)


class Task(db.Model):
    __tablename__ = "tasks"
    __table_args__ = (db.Index("ix_tasks_user_due", "user_id", "due_date"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    priority = db.Column(db.String(10), nullable=False, default="Medium")
    category = db.Column(db.String(30), nullable=False, default="Personal")
    due_date = db.Column(db.Date)
    due_time = db.Column(db.Time)
    is_done = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.DateTime)
    created_at = _created()


class Goal(db.Model):
    __tablename__ = "goals"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(30), nullable=False, default="Personal")
    description = db.Column(db.Text, nullable=False, default="")
    daily_target = db.Column(db.String(200), nullable=False, default="")
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_done = db.Column(db.Boolean, nullable=False, default=False)
    created_at = _created()
    subtasks = db.relationship("GoalTask", backref="goal", cascade="all, delete-orphan", order_by="GoalTask.due_date, GoalTask.id")

    @property
    def total(self):
        return len(self.subtasks)

    @property
    def done_count(self):
        return sum(1 for t in self.subtasks if t.is_done)

    @property
    def percent(self):
        if self.subtasks:
            return round(self.done_count * 100 / self.total)
        return 100 if self.is_done else 0

    @property
    def completed(self):
        return self.percent == 100


class GoalTask(db.Model):
    __tablename__ = "goal_tasks"

    id = db.Column(db.Integer, primary_key=True)
    goal_id = db.Column(db.Integer, db.ForeignKey("goals.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    due_date = db.Column(db.Date)
    is_done = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.DateTime)


class Folder(db.Model):
    __tablename__ = "folders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("folders.id"), index=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = _created()


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    folder_id = db.Column(db.Integer, db.ForeignKey("folders.id"), index=True)
    original_name = db.Column(db.String(200), nullable=False)
    stored_name = db.Column(db.String(80), nullable=False)
    ext = db.Column(db.String(10), nullable=False)
    size = db.Column(db.Integer, nullable=False, default=0)
    category = db.Column(db.String(30), nullable=False, default="Other")
    is_important = db.Column(db.Boolean, nullable=False, default=False)
    created_at = _created()
    deleted_at = db.Column(db.DateTime)


class Transaction(db.Model):
    __tablename__ = "transactions"
    __table_args__ = (db.Index("ix_tx_user_date", "user_id", "date"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    kind = db.Column(db.String(10), nullable=False)  # income or expense
    category = db.Column(db.String(30), nullable=False, default="Other")
    amount_paise = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(200), nullable=False, default="")
    created_at = _created()


class Loan(db.Model):
    __tablename__ = "loans"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)  # borrowed or lent
    person = db.Column(db.String(100), nullable=False)
    amount_paise = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date)
    note = db.Column(db.String(200), nullable=False, default="")
    is_settled = db.Column(db.Boolean, nullable=False, default=False)
    created_at = _created()


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(30), nullable=False, default="Personal event")
    description = db.Column(db.Text, nullable=False, default="")
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    repeat_yearly = db.Column(db.Boolean, nullable=False, default=False)
    created_at = _created()


class Reminder(db.Model):
    __tablename__ = "reminders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    remind_at = db.Column(db.DateTime, nullable=False)
    repeat = db.Column(db.String(10), nullable=False, default="none")
    notified = db.Column(db.Boolean, nullable=False, default=False)
    is_done = db.Column(db.Boolean, nullable=False, default=False)
    created_at = _created()


class Subject(db.Model):
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    semester = db.Column(db.Integer, nullable=False, default=1)
    created_at = _created()
    topics = db.relationship("SyllabusTopic", backref="subject", cascade="all, delete-orphan", order_by="SyllabusTopic.id")

    @property
    def total(self):
        return len(self.topics)

    @property
    def done_count(self):
        return sum(1 for t in self.topics if t.is_done)

    @property
    def percent(self):
        return round(self.done_count * 100 / self.total) if self.topics else 0


class SyllabusTopic(db.Model):
    __tablename__ = "syllabus_topics"

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False, index=True)
    unit = db.Column(db.String(100), nullable=False, default="")
    chapter = db.Column(db.String(100), nullable=False, default="")
    title = db.Column(db.String(200), nullable=False)
    is_done = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.DateTime)


class StudyItem(db.Model):
    __tablename__ = "study_items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"))
    kind = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    due_date = db.Column(db.Date)
    is_done = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.DateTime)
    created_at = _created()
    subject = db.relationship("Subject")


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    text = db.Column(db.String(255), nullable=False)
    created_at = _created()


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
