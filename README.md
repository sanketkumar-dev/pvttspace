# PVTTSpace

Your Life. Your Space. A private workspace for tasks, notes, goals, files, money, calendar, reminders and study.

## Run locally (Windows)

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python run.py
```

Open http://127.0.0.1:5000

## Updating from Phase 1

Extract this folder over your old PVTTSpace folder and overwrite files. Keep the `instance` folder.
Run `pip install -r requirements.txt` and `python run.py`. New columns are added to your existing
database automatically.

## Modules

Dashboard, Goals, Tasks (with daily streak), Notes, Documents, Expenses (with borrowed and lent),
Calendar, Reminders, Study and Syllabus, Graphs, Calculator, Global search, Quick add, Favourites,
Recycle bin, Settings (theme, privacy, email, export, backup and restore, delete account), Profile.

## Password reset email

Set MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD and MAIL_FROM in `.env`. Without them,
the reset link is printed in the terminal where the app runs.

## Before launch

1. Set `CONTACT_EMAIL` in `.env` to a real address (shown on the privacy and terms pages).
2. Read the privacy policy and terms and adjust them to your situation.
3. Set a long random `SECRET_KEY`, `COOKIE_SECURE=1` and `FLASK_DEBUG=0`.
4. Serve over HTTPS with a production server (for example gunicorn) and connect your custom domain.
5. Back up `instance/pvttspace.db` and the `uploads` folder, or use Settings, Download full backup.
