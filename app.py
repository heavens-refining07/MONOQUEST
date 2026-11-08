"""MONOQUEST Celestial Sect public web demo."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import hmac
import os
import re
import secrets
import sqlite3

from flask import (
    Flask, abort, flash, g, has_request_context, redirect, render_template, request, session, url_for,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("MONOQUEST_DATA_DIR", str(BASE_DIR / "data")))
PUBLIC_DEMO = True
DATABASE = DATA_DIR / "demo-template.db"
TZ = ZoneInfo("Asia/Kolkata")
CATEGORIES = ("Mind", "Body", "Study", "Code", "Life")
XP_VALUES = (10, 20, 30, 40, 50, 75, 100)
AVATARS = ("ronin", "wanderer", "scholar", "vanguard")

DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
app.secret_key = os.environ.get("MONOQUEST_SECRET")
if not app.secret_key:
    raise RuntimeError("Set MONOQUEST_SECRET before starting the public demo.")


def today() -> date:
    return datetime.now(TZ).date()


class LocalConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connection():
    path = g.get("demo_database", DATABASE) if has_request_context() else DATABASE
    con = sqlite3.connect(path, factory=LocalConnection)
    if path != DATABASE:
        con.execute("PRAGMA max_page_count=256")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def initialize():
    with connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS habits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                xp INTEGER NOT NULL DEFAULT 20,
                created_on TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
                completed_on TEXT NOT NULL,
                UNIQUE(habit_id, completed_on)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS routine_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                symbol TEXT NOT NULL DEFAULT 'clock'
            );
            CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                display_name TEXT NOT NULL DEFAULT 'Dev',
                title TEXT NOT NULL DEFAULT 'Disciple of Progress',
                bio TEXT NOT NULL DEFAULT 'One quest at a time. One day stronger.',
                focus TEXT NOT NULL DEFAULT 'Building a better routine',
                avatar TEXT NOT NULL DEFAULT 'ronin'
            );
        """)
        # v1 earned XP depended on the latest habit reward. Snapshot existing
        # rewards as part of a lossless upgrade, so editing a habit preserves XP.
        columns = {r["name"] for r in db.execute("PRAGMA table_info(completions)")}
        if "earned_xp" not in columns:
            db.execute("ALTER TABLE completions ADD COLUMN earned_xp INTEGER")
        db.execute("""
            UPDATE completions SET earned_xp = (
                SELECT xp FROM habits WHERE habits.id = completions.habit_id
            ) WHERE earned_xp IS NULL
        """)
        db.execute("INSERT OR IGNORE INTO profile(id) VALUES(1)")
        habit_columns = {r["name"] for r in db.execute("PRAGMA table_info(habits)")}
        if "duration_minutes" not in habit_columns:
            db.execute("ALTER TABLE habits ADD COLUMN duration_minutes INTEGER NOT NULL DEFAULT 30")
        completion_columns = {r["name"] for r in db.execute("PRAGMA table_info(completions)")}
        if "completed_minutes" not in completion_columns:
            db.execute("ALTER TABLE completions ADD COLUMN completed_minutes INTEGER")
        db.execute("""UPDATE completions SET completed_minutes = (
            SELECT duration_minutes FROM habits WHERE habits.id = completions.habit_id
        ) WHERE completed_minutes IS NULL""")
        if not db.execute("SELECT 1 FROM settings WHERE key='routines_seeded'").fetchone():
            if not db.execute("SELECT 1 FROM routine_items LIMIT 1").fetchone():
                db.executemany("INSERT INTO routine_items(title, scheduled_time, symbol) VALUES(?,?,?)", [
                    ("College", "08:00", "book"),
                    ("Lunch & Rest", "13:30", "clock"),
                    ("Study / Assignment", "14:00", "book"),
                    ("Coding / Project", "16:00", "code"),
                    ("Workout", "18:00", "flame"),
                    ("Evening Revision", "19:00", "book"),
                    ("Reading & Sleep", "22:30", "sparkles"),
                ])
            db.execute("INSERT INTO settings(key,value) VALUES('routines_seeded','yes')")
        if not db.execute("SELECT 1 FROM settings WHERE key='seeded'").fetchone():
            if not db.execute("SELECT 1 FROM habits LIMIT 1").fetchone():
                sample = [
                    ("Attend College (8 AM – 1 PM)", "Study", "08:00", 50, 300),
                    ("Study – TCS (1 hour)", "Study", "14:00", 40, 60),
                    ("Code / Project Work (1 hour)", "Code", "16:00", 50, 60),
                    ("Workout (30 minutes)", "Body", "18:00", 30, 30),
                    ("Read (30 minutes)", "Mind", "20:30", 20, 30),
                    ("Plan Tomorrow (10 minutes)", "Life", "22:30", 10, 10),
                ]
                db.executemany("""
                    INSERT INTO habits(title,category,scheduled_time,xp,duration_minutes,created_on)
                    VALUES(?,?,?,?,?,?)
                """, [(n,c,t,x,d,today().isoformat()) for n,c,t,x,d in sample])
            db.execute("INSERT INTO settings(key,value) VALUES('seeded','yes')")


def clock_display(value: str) -> str:
    try:
        return datetime.strptime(value, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return value

app.jinja_env.filters["clock"] = clock_display


@app.before_request
def validate_form_token():
    if request.method == "POST":
        actual = str(request.form.get("csrf_token", ""))
        expected = str(session.get("csrf_token", ""))
        if not expected or not hmac.compare_digest(actual, expected):
            abort(400, "This form expired. Refresh the page and try again.")


@app.context_processor
def global_template_values():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"], "public_demo": PUBLIC_DEMO}


def player_stats():
    now = today()
    day = now.isoformat()
    with connection() as db:
        profile = dict(db.execute("SELECT * FROM profile WHERE id=1").fetchone())
        raw_habits = db.execute("""
            SELECT * FROM habits WHERE archived = 0
            ORDER BY scheduled_time ASC, id ASC
        """).fetchall()
        done_ids = {r["habit_id"] for r in db.execute(
            "SELECT habit_id FROM completions WHERE completed_on = ?", (day,)
        )}
        history = db.execute("""
            SELECT completed_on, COUNT(*) AS n, COALESCE(SUM(earned_xp),0) AS xp
            FROM completions GROUP BY completed_on ORDER BY completed_on
        """).fetchall()
        routines = [dict(r) for r in db.execute(
            "SELECT * FROM routine_items ORDER BY scheduled_time, id").fetchall()]
        category_totals = {r['category']: r['n'] for r in db.execute(
            """SELECT c.category_snapshot category, COUNT(*) n FROM completions c WHERE c.state='full' GROUP BY c.category_snapshot""").fetchall()}
        category_minutes = {r['category']: r['mins'] or 0 for r in db.execute(
            """SELECT c.category_snapshot category, SUM(c.completed_minutes) mins FROM completions c WHERE c.state='full' GROUP BY c.category_snapshot""").fetchall()}
    entries = {r["completed_on"]: {"n": r["n"], "xp": r["xp"]} for r in history}
    total_xp = sum(v["xp"] for v in entries.values())
    completions = sum(v["n"] for v in entries.values())
    streak = 0
    cur = now if day in entries else now - timedelta(days=1)
    while cur.isoformat() in entries:
        streak += 1
        cur -= timedelta(days=1)
    habits = [{**dict(h), "done": h["id"] in done_ids} for h in raw_habits]
    done = sum(h["done"] for h in habits)
    percent = round(done / len(habits) * 100) if habits else 0
    level = total_xp // 200 + 1
    week = []
    for i in range(6,-1,-1):
        d = now - timedelta(days=i)
        info = entries.get(d.isoformat(), {"n":0,"xp":0})
        week.append({"day": d.strftime("%a"), "day_no": d.day,
                     "date": d.isoformat(), "count": info["n"],
                     "today": i == 0, "active": info["n"] > 0})
    rank = ("Legend" if level >= 20 else "Elite" if level >= 10
            else "Hunter" if level >= 6 else "Apprentice" if level >= 3 else "Rookie")
    achievements = [
        {"icon": "sparkles", "name": "First Steps", "desc": "Complete your first quest", "unlocked": completions >= 1, "progress": min(completions,1), "target": 1},
        {"icon": "flame", "name": "7-Day Warrior", "desc": "Keep a seven-day streak", "unlocked": streak >= 7, "progress": min(streak,7), "target": 7},
        {"icon": "zap", "name": "Rising Star", "desc": "Earn a total of 500 XP", "unlocked": total_xp >= 500, "progress": min(total_xp,500), "target": 500},
        {"icon": "trophy", "name": "Quest Veteran", "desc": "Complete 50 quests", "unlocked": completions >= 50, "progress": min(completions,50), "target": 50},
    ]
    next_habit = next((h for h in habits if not h["done"]), None)
    timeline_today = datetime.now(TZ).strftime('%H:%M')
    next_routine = next((r for r in routines if r['scheduled_time'] >= timeline_today), None)
    hour = datetime.now(TZ).hour
    greeting = 'Good morning' if hour < 12 else 'Good afternoon' if hour < 17 else 'Good evening'
    week_average = round(sum(day['count'] for day in week) / 7, 1)
    active_days = sum(day['active'] for day in week)
    recent_achievements = achievements[:]
    now_minutes = hour*60 + datetime.now(TZ).minute
    return dict(profile=profile, habits=habits, done=done, count=len(habits), percent=percent,
                total_xp=total_xp, today_xp=entries.get(day, {}).get("xp",0),
                level=level, level_xp=total_xp % 200, level_percent=(total_xp%200)/2,
                streak=streak, week=week, rank=rank, achievements=achievements,
                completions=completions, next_habit=next_habit,
                readable_date=now.strftime("%A, %d %B %Y"),
                categories=CATEGORIES, xp_options=XP_VALUES, avatar_choices=AVATARS,
                routines=routines, next_routine=next_routine, now_minutes=now_minutes,
                greeting=greeting, week_average=week_average, active_days=active_days,
                category_totals=category_totals, category_minutes=category_minutes,
                recent_achievements=recent_achievements)


@app.get("/")
def dashboard():
    return render_template("index.html", page="dashboard", **player_stats())


@app.get("/profile")
def profile():
    return render_template("profile.html", page="profile", **player_stats())


@app.get('/routine')
def routine():
    return render_template('routine.html', page='routine', **player_stats())


@app.get('/habits')
def habits_page():
    return render_template('habits.html', page='habits', **player_stats())


@app.get('/quests')
def quests_page():
    return render_template('quests.html', page='quests', **player_stats())


@app.get('/analytics')
def analytics():
    return render_template('analytics.html', page='analytics', **player_stats())


@app.get('/achievements')
def achievements_page():
    return render_template('achievements.html', page='achievements', **player_stats())


@app.get('/settings')
def settings_page():
    return render_template('settings.html', page='settings', **player_stats())


def parse_routine(form):
    title = form.get('title', '').strip()
    clock = form.get('scheduled_time', '18:00')
    symbol = form.get('symbol', 'clock')
    if not 1 <= len(title) <= 70:
        return None, 'Routine name must be 1–70 characters.'
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',clock):
        return None, 'Choose a valid time.'
    if symbol not in ('clock', 'book', 'code', 'flame', 'sparkles', 'target'):
        return None, 'Choose a valid routine icon.'
    return (title,clock,symbol), None


@app.post('/routine/add')
def routine_add():
    item, error = parse_routine(request.form)
    if error: flash(error, 'error')
    else:
        with connection() as db:
            db.execute('INSERT INTO routine_items(title, scheduled_time, symbol) VALUES(?,?,?)', item)
        flash('Schedule updated.', 'success')
    return redirect(url_for('routine'))


@app.post('/routine/<int:item_id>/edit')
def routine_edit(item_id):
    item, error = parse_routine(request.form)
    if error: flash(error, 'error')
    else:
        with connection() as db:
            changed = db.execute('UPDATE routine_items SET title=?,scheduled_time=?,symbol=? WHERE id=?', (*item,item_id))
            if changed.rowcount == 0: abort(404)
        flash('Routine item updated.', 'success')
    return redirect(url_for('routine'))


@app.post('/routine/<int:item_id>/remove')
def routine_remove(item_id):
    with connection() as db:
        changed = db.execute('DELETE FROM routine_items WHERE id=?',(item_id,))
        if changed.rowcount == 0: abort(404)
    flash('Routine item removed.', 'success')
    return redirect(url_for('routine'))


def parse_habit(form):
    title = form.get("title", "").strip()
    category = form.get("category", "Life")
    clock = form.get("scheduled_time", "18:00")
    try:
        xp = int(form.get("xp", "20"))
    except ValueError:
        xp = -1
    try:
        duration = int(form.get("duration_minutes", "30"))
    except ValueError:
        duration = -1
    if not 5 <= duration <= 600:
        return None, "Planned duration must be between 5 and 600 minutes."
    if not 1 <= len(title) <= 70:
        return None, "Quest name must be 1–70 characters."
    if category not in CATEGORIES:
        return None, "Choose a valid category."
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
        return None, "Choose a valid time."
    if xp not in XP_VALUES:
        return None, "Choose a valid XP reward."
    return (title,category,clock,xp,duration), None


@app.post("/habits")
def add_habit():
    item, error = parse_habit(request.form)
    if error:
        flash(error, "error")
    else:
        with connection() as db:
            db.execute("""INSERT INTO habits(title,category,scheduled_time,xp,duration_minutes,created_on)
                          VALUES(?,?,?,?,?,?)""", (*item, today().isoformat()))
        flash("New daily quest added.", "success")
    return redirect(url_for("dashboard") + "#quests")


@app.post("/habits/<int:habit_id>/edit")
def edit_habit(habit_id):
    item, error = parse_habit(request.form)
    if error:
        flash(error, "error")
    else:
        with connection() as db:
            changed = db.execute("""
                UPDATE habits SET title=?, category=?, scheduled_time=?, xp=?, duration_minutes=?
                WHERE id=? AND archived=0
            """, (*item, habit_id))
            if changed.rowcount == 0:
                abort(404)
        flash("Quest updated. Past XP is preserved.", "success")
    return redirect(url_for("dashboard") + "#quests")


@app.post("/habits/<int:habit_id>/toggle")
def toggle_habit(habit_id):
    day = today().isoformat()
    with connection() as db:
        habit = db.execute("SELECT * FROM habits WHERE id=? AND archived=0", (habit_id,)).fetchone()
        if habit is None:
            abort(404)
        completed = db.execute("SELECT id FROM completions WHERE habit_id=? AND completed_on=?",
                               (habit_id,day)).fetchone()
        if completed:
            db.execute("DELETE FROM completions WHERE id=?", (completed["id"],))
        else:
            db.execute("INSERT INTO completions(habit_id,completed_on,earned_xp,completed_minutes) VALUES(?,?,?,?)",
                       (habit_id,day,habit["xp"],habit["duration_minutes"]))
    return redirect(url_for("dashboard") + "#quests")


@app.post("/habits/<int:habit_id>/archive")
def archive_habit(habit_id):
    with connection() as db:
        changed = db.execute("UPDATE habits SET archived=1 WHERE id=? AND archived=0", (habit_id,))
        if changed.rowcount == 0:
            abort(404)
    flash("Quest archived; earned XP remains.", "success")
    return redirect(url_for("dashboard") + "#quests")


@app.post("/profile")
def update_profile():
    name = request.form.get("display_name", "").strip()
    title = request.form.get("title", "").strip()
    bio = request.form.get("bio", "").strip()
    focus = request.form.get("focus", "").strip()
    avatar = request.form.get("avatar", "ronin")
    if not 1 <= len(name) <= 32:
        flash("Display name must be 1–32 characters.", "error")
        return redirect(url_for("profile") + "#edit-profile")
    if not 1 <= len(title) <= 45 or len(bio) > 240 or len(focus) > 80:
        flash("Check your title (45), bio (240), and focus (80) character limits.", "error")
        return redirect(url_for("profile") + "#edit-profile")
    if avatar not in AVATARS or request.files:
        abort(400, "Choose one of the built-in demo avatars.")
    with connection() as db:
        db.execute("""
            UPDATE profile SET display_name=?, title=?, bio=?, focus=?, avatar=? WHERE id=1
        """, (name,title,bio,focus,avatar))
    flash("Character profile saved.", "success")
    return redirect(url_for("profile"))


@app.get("/health")
def health():
    return {"app":"MONOQUEST","status":"ok","today":today().isoformat(),"version":"4.3"}


initialize()

import sys
from v4 import install
install(sys.modules[__name__])

if PUBLIC_DEMO:
    from public_demo import install_demo
    install_demo(sys.modules[__name__])

if __name__ == "__main__":
    app.run(host="127.0.0.1",port=5000,debug=os.getenv("MONOQUEST_DEBUG") == "1")
