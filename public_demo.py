"""Temporary, isolated sample boards for the single-worker public showcase."""
from datetime import timedelta
import os
import re
import secrets
import shutil
import sqlite3
import time

from flask import g, redirect, request, session, url_for

MAX_BOARDS = 256
IDLE_SECONDS = 24 * 60 * 60


def install_demo(m):
    app = m.app
    boards = m.DATA_DIR / 'demo-boards'
    boards.mkdir(exist_ok=True)
    app.config.update(
        MAX_CONTENT_LENGTH=16 * 1024,
        SESSION_COOKIE_NAME='monoquest_demo',
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('MONOQUEST_DEMO_HTTPS', '1') == '1',
    )

    def seed_board(path):
        # One synchronous Gunicorn worker serializes creation, cleanup and resets.
        staging = path.with_suffix('.tmp')
        try:
            shutil.copyfile(m.DATABASE, staging)
            day = m.today()
            with sqlite3.connect(staging, factory=m.LocalConnection) as db:
                db.execute("UPDATE profile SET display_name='Wanderer' WHERE id=1")
                db.execute("UPDATE habits SET created_on=?", ((day-timedelta(days=7)).isoformat(),))
                db.execute("UPDATE habits SET title='Study a new topic' WHERE id=2")
                db.executemany("""
                    INSERT INTO completions
                        (habit_id, completed_on, earned_xp, completed_minutes, category_snapshot, title_snapshot)
                    SELECT id, ?, xp, duration_minutes, category, title FROM habits WHERE id=?
                """, [((day - timedelta(days=offset)).isoformat(), habit_id)
                      for offset, habit_id in [(0, 5), (1, 4), (1, 5), (2, 2), (3, 5), (5, 4)]])
                db.execute("""
                    INSERT INTO habits
                        (title, category, scheduled_time, xp, duration_minutes, created_on, kind, first_step)
                    VALUES ('Plan the next chapter', 'Life', '19:00', 20, 15, ?, 'task',
                            'Write down one thing you want to finish tomorrow.')
                """, (day.isoformat(),))
                db.execute("""
                    INSERT INTO daily_notes(day, main_habit_id) VALUES (?, 3)
                """, (day.isoformat(),))
            staging.replace(path)
        finally:
            staging.unlink(missing_ok=True)

    @app.before_request
    def select_demo_board():
        if request.endpoint in {None, 'static', 'health'}:
            return

        token = session.get('demo_board', '')
        if not re.fullmatch(r'[0-9a-f]{32}', token):
            token = secrets.token_hex(16)
            session['demo_board'] = token
        path = boards / f'{token}.sqlite'
        now = time.time()
        if path.exists() and now - path.stat().st_mtime <= IDLE_SECONDS:
            path.touch()
        else:
            recent = []
            for board in boards.glob('*.sqlite'):
                modified = board.stat().st_mtime
                if now - modified > IDLE_SECONDS:
                    board.unlink()
                else:
                    recent.append((modified, board))
            if len(recent) >= MAX_BOARDS:
                min(recent)[1].unlink()
            seed_board(path)
        g.demo_database = path

    @app.after_request
    def demo_response(response):
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/demo/reset')
    def reset_demo():
        seed_board(g.demo_database)
        session.pop('celebration', None)
        return redirect(url_for('dashboard'))

    @app.errorhandler(413)
    def demo_request_too_large(_error):
        return 'The demo only accepts small form submissions.', 413

    @app.errorhandler(sqlite3.OperationalError)
    def demo_database_error(error):
        if error.sqlite_errorcode == sqlite3.SQLITE_FULL:
            return 'This demo board is full. Reset it from Demo Settings.', 409
        app.logger.error('Demo database operation failed', exc_info=error)
        return 'The demo board is temporarily unavailable.', 500
