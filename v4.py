"""Personal workflow features for MONOQUEST. All state stays in SQLite."""
from datetime import date, datetime, timedelta, timezone
import calendar
import time
from flask import request, render_template, redirect, url_for, flash, abort, session

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def install(m):
    app = m.app
    with m.connection() as db:
        additions = {
            'habits': [('kind', "TEXT NOT NULL DEFAULT 'habit'"), ('repeat_days', "TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6'"),
                       ('weekly_target', 'INTEGER'), ('due_on', 'TEXT'), ('minimum_action', "TEXT NOT NULL DEFAULT ''"),
                       ('first_step', "TEXT NOT NULL DEFAULT ''"), ('routine_id', 'INTEGER')],
            'completions': [('category_snapshot','TEXT'), ('title_snapshot','TEXT'),
                            ('state', "TEXT NOT NULL DEFAULT 'full'"), ('corrected_at','TEXT')],
        }
        for table, fields in additions.items():
            existing = {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
            for name, decl in fields:
                if name not in existing: db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')
        db.execute('UPDATE completions SET category_snapshot=(SELECT category FROM habits WHERE id=habit_id) WHERE category_snapshot IS NULL')
        db.execute('UPDATE completions SET title_snapshot=(SELECT title FROM habits WHERE id=habit_id) WHERE title_snapshot IS NULL')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS achievement_unlocks(name TEXT PRIMARY KEY, unlocked_on TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS focus_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT, habit_id INTEGER REFERENCES habits(id), title TEXT NOT NULL, category TEXT NOT NULL, planned_seconds INTEGER NOT NULL, elapsed_seconds INTEGER NOT NULL DEFAULT 0, started_at REAL, status TEXT NOT NULL DEFAULT 'running', session_on TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS daily_notes(day TEXT PRIMARY KEY, main_habit_id INTEGER, note TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS completion_events(id INTEGER PRIMARY KEY AUTOINCREMENT, habit_id INTEGER NOT NULL, day TEXT NOT NULL, action TEXT NOT NULL, recorded_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS completion_day_idx ON completions(completed_on);
        ''')
        db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('v4_schema','4')")
    def go_back(fallback='dashboard'):
        dest = request.form.get('return_to','')
        # Local paths only; do not permit external redirects.
        path = dest.split('?',1)[0].split('#',1)[0]
        allowed = {'/','/habits','/quests','/routine','/analytics','/history','/review','/focus','/settings','/achievements'}
        if path not in allowed or not dest.startswith('/') or dest.startswith('//') or '\\' in dest: dest=url_for(fallback)
        return redirect(dest)

    def scheduled(h, day, db):
        if h['created_on'] > day.isoformat(): return False
        if h['kind']=='task':
            existing=db.execute('SELECT completed_on FROM completions WHERE habit_id=? AND state=\'full\'',(h['id'],)).fetchone()
            return not existing or existing['completed_on']==day.isoformat()
        if str(day.weekday()) not in h['repeat_days'].split(','): return False
        if h['weekly_target']:
            start=(day-timedelta(days=day.weekday())).isoformat()
            n=db.execute("SELECT COUNT(*) FROM completions WHERE habit_id=? AND state='full' AND completed_on>=? AND completed_on<?",(h['id'],start,day.isoformat())).fetchone()[0]
            if n>=h['weekly_target']:
                return bool(db.execute('SELECT 1 FROM completions WHERE habit_id=? AND completed_on=?',(h['id'],day.isoformat())).fetchone())
        return True

    def describe(h):
        if h['kind']=='task': return 'One-time quest' + (' · Due '+h['due_on'] if h['due_on'] else '')
        names=[DAYS[int(d)] for d in h['repeat_days'].split(',') if d]
        return (f"{h['weekly_target']} times / week · " if h['weekly_target'] else '') + ('Every day' if len(names)==7 else ', '.join(names))

    base_stats=m.player_stats
    def stats():
        data=base_stats()
        day=m.today()
        with m.connection() as db:
            grid_start=day-timedelta(days=day.weekday()+77)
            activity_counts={r['completed_on']:r['n'] for r in db.execute('SELECT completed_on,COUNT(*) n FROM completions WHERE completed_on>=? GROUP BY completed_on',(grid_start.isoformat(),))}
            activity_grid=[]
            for offset in range(84):
                d=grid_start+timedelta(days=offset);n=activity_counts.get(d.isoformat(),0)
                activity_grid.append({'date':d.isoformat(),'count':n,'future':d>day,'intensity':0 if n==0 else 1 if n==1 else 2 if n<=3 else 3 if n<=5 else 4})
            all_habits=[dict(r) for r in db.execute('SELECT * FROM habits WHERE archived=0 ORDER BY scheduled_time,id')]
            states={r['habit_id']:r['state'] for r in db.execute('SELECT habit_id,state FROM completions WHERE completed_on=?',(day.isoformat(),))}
            for h in all_habits:
                h['state']=states.get(h['id'],'open')
                if h['kind']=='task' and db.execute("SELECT 1 FROM completions WHERE habit_id=? AND state='full'",(h['id'],)).fetchone(): h['state']='full'
                h['done']=h['state']=='full';h['schedule_label']=describe(h)
                h['due_today']=scheduled(h,day,db)
                h['routine_title']=next((r['title'] for r in data['routines'] if r['id']==h['routine_id']),None)
            due=[h for h in all_habits if h['due_today']]
            tasks=sorted([h for h in all_habits if h['kind']=='task'],key=lambda h:(h['due_on'] or '9999-12-31',h['scheduled_time'],h['id']))
            archived=[dict(r) for r in db.execute('SELECT * FROM habits WHERE archived=1 ORDER BY title')]
            completed_tasks=[dict(r) for r in db.execute("SELECT h.*,c.completed_on FROM habits h JOIN completions c ON c.habit_id=h.id WHERE h.kind='task' AND h.archived=0 AND c.state='full' ORDER BY c.completed_on DESC")]
            all_dates=[date.fromisoformat(r[0]) for r in db.execute('SELECT DISTINCT completed_on FROM completions ORDER BY completed_on')]
            longest=run=0;prev=None
            for d in all_dates:
                run=run+1 if prev and d==prev+timedelta(days=1) else 1
                longest=max(longest,run);prev=d
            full_total=db.execute("SELECT COUNT(*) FROM completions WHERE state='full'").fetchone()[0]
            for a in data['achievements']:
                if a['name'] in ('First Steps','Quest Veteran'):
                    a['progress']=min(full_total,a['target']);a['unlocked']=full_total>=a['target']
                if a['name']=='7-Day Warrior': a['progress']=min(longest,7);a['unlocked']=longest>=7
                if a['unlocked']:
                    db.execute('INSERT OR IGNORE INTO achievement_unlocks(name,unlocked_on) VALUES(?,?)',(a['name'],day.isoformat()))
            earned={r['name']:dict(r) for r in db.execute('SELECT * FROM achievement_unlocks')}
            for a in data['achievements']:
                a['unlocked']=a['name'] in earned
                a['unlocked_on']=earned.get(a['name'],{}).get('unlocked_on')
                if a['unlocked']: a['progress']=a['target']
            note=db.execute('SELECT * FROM daily_notes WHERE day=?',(day.isoformat(),)).fetchone()
            main_id=note['main_habit_id'] if note else None
            main=next((h for h in all_habits if h['id']==main_id),None)
            active=db.execute("SELECT * FROM focus_sessions WHERE status IN ('running','paused') ORDER BY id DESC LIMIT 1").fetchone()
            sessions=[dict(r) for r in db.execute("SELECT * FROM focus_sessions WHERE status='finished' ORDER BY id DESC LIMIT 10")]
            actual=db.execute("SELECT COALESCE(SUM(elapsed_seconds),0) FROM focus_sessions WHERE status='finished'").fetchone()[0]
        data.update(activity_grid=activity_grid,completions=full_total,active_habit_count=sum(h['kind']=='habit' for h in all_habits),habits=due,all_habits=all_habits,habit_library=[h for h in all_habits if h['kind']=='habit'],
                    tasks=[h for h in tasks if h['due_today']],completed_tasks=completed_tasks,
                    archived_habits=archived,done=sum(h['done'] for h in due),count=len(due),
                    percent=round(sum(h['done'] for h in due)/len(due)*100) if due else 0,
                    minimum_count=sum(h['state']=='minimum' for h in due),main_quest=main,
                    journal_note=note['note'] if note else '',today_iso=day.isoformat(),weekday_names=DAYS,
                    active_focus=dict(active) if active else None,focus_sessions=sessions,actual_minutes=round(actual/60,1),
                    new_achievements=sum(not r['seen'] for r in earned.values()),
                    recent_achievements=sorted(data['achievements'],key=lambda a:not a['unlocked']))
        return data
    m.player_stats=stats

    @app.context_processor
    def visual_feedback():
        return {'celebration':session.pop('celebration',None)}

    # Replace category joins with recorded categories. Editing a habit never
    # reclassifies an old completion. Legacy rows are snapshotted during migration.
    def habit_values():
        item,error=m.parse_habit(request.form)
        if error: raise ValueError(error)
        kind=request.form.get('kind','habit')
        if kind not in ('habit','task'): raise ValueError('Choose Habit or One-time quest.')
        days=request.form.getlist('repeat_days')
        if kind=='habit' and (not days or any(d not in list(map(str,range(7))) for d in days)):
            raise ValueError('Choose at least one repeat day.')
        target=request.form.get('weekly_target','').strip()
        if target and (not target.isdigit() or not 1<=int(target)<=len(set(days))):
            raise ValueError('Weekly target must be between 1 and the number of selected days.')
        due=request.form.get('due_on','').strip()
        if due: date.fromisoformat(due)
        minimum=request.form.get('minimum_action','').strip()
        step=request.form.get('first_step','').strip()
        if len(minimum)>100 or len(step)>140: raise ValueError('Keep the minimum action under 100 characters and first step under 140.')
        rid=request.form.get('routine_id','').strip()
        with m.connection() as db:
            if rid and (not rid.isdigit() or not db.execute('SELECT 1 FROM routine_items WHERE id=?',(int(rid),)).fetchone()): raise ValueError('Choose an existing routine block.')
            linked=db.execute('SELECT scheduled_time FROM routine_items WHERE id=?',(rid,)).fetchone() if rid else None
        vals=list(item)
        if linked: vals[2]=linked['scheduled_time']
        return (*vals,kind,','.join(sorted(set(days))) if kind=='habit' else '0,1,2,3,4,5,6',int(target) if target and kind=='habit' else None,due if kind=='task' and due else None,minimum if kind=='habit' else '',step,int(rid) if rid else None)

    def add():
        try:
            values=habit_values()
            with m.connection() as db:
                db.execute('INSERT INTO habits(title,category,scheduled_time,xp,duration_minutes,kind,repeat_days,weekly_target,due_on,minimum_action,first_step,routine_id,created_on) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(*values,m.today().isoformat()))
            flash('Added to your personal quest board.','success')
        except (ValueError,OverflowError): flash('Check your task details, selected repeat days, and weekly target.','error')
        return go_back()

    def edit(habit_id):
        try:
            values=habit_values()
            with m.connection() as db:
                old=db.execute('SELECT * FROM habits WHERE id=? AND archived=0',(habit_id,)).fetchone()
                if not old: abort(404)
                if old['kind']!=values[5]: raise ValueError('Keep the existing task type; create a new item to change it.')
                db.execute('UPDATE habits SET title=?,category=?,scheduled_time=?,xp=?,duration_minutes=?,kind=?,repeat_days=?,weekly_target=?,due_on=?,minimum_action=?,first_step=?,routine_id=? WHERE id=?',(*values,habit_id))
            flash('Updated. Past XP, titles and categories are preserved.','success')
        except (ValueError,OverflowError): flash('Check your task details. Existing items keep their Habit or Quest type.','error')
        return go_back()

    def record(habit_id, day, action, corrected=False):
        if day>m.today(): raise ValueError('Future check-ins are not allowed.')
        if action not in ('full','minimum','undo'): raise ValueError('Choose a valid check-in state.')
        with m.connection() as db:
            xp_before=db.execute('SELECT COALESCE(SUM(earned_xp),0) FROM completions').fetchone()[0]
            h=db.execute('SELECT * FROM habits WHERE id=?',(habit_id,)).fetchone()
            if not h: abort(404)
            if h['created_on']>day.isoformat(): raise ValueError('This item did not exist on that day.')
            old=db.execute('SELECT * FROM completions WHERE habit_id=? AND completed_on=?',(habit_id,day.isoformat())).fetchone()
            if action=='minimum' and old and old['state']=='full' and not corrected: raise ValueError('This habit is already fully completed.')
            if action=='minimum' and (h['kind']!='habit' or not h['minimum_action']): raise ValueError('Set a minimum action on this habit first.')
            if action!='undo' and h['archived'] and not old: raise ValueError('Restore the archived item before adding a check-in.')
            if action!='undo' and h['kind']=='task' and db.execute("SELECT 1 FROM completions WHERE habit_id=? AND completed_on<>?",(habit_id,day.isoformat())).fetchone(): raise ValueError('A one-time quest can only be completed once. Undo its existing check-in first.')
            if action=='undo': db.execute('DELETE FROM completions WHERE habit_id=? AND completed_on=?',(habit_id,day.isoformat()))
            else:
                # Keep original snapshots when changing minimum/full states.
                cat=old['category_snapshot'] if old else h['category'];title=old['title_snapshot'] if old else h['title']
                xp=(old['earned_xp'] if old and old['state']=='full' else h['xp']) if action=='full' else 0
                mins=(old['completed_minutes'] if old and old['state']=='full' else h['duration_minutes']) if action=='full' else 0
                db.execute('INSERT INTO completions(habit_id,completed_on,earned_xp,completed_minutes,category_snapshot,title_snapshot,state,corrected_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(habit_id,completed_on) DO UPDATE SET earned_xp=excluded.earned_xp,completed_minutes=excluded.completed_minutes,state=excluded.state,corrected_at=excluded.corrected_at',(habit_id,day.isoformat(),xp,mins,cat,title,action,datetime.now(m.TZ).isoformat() if corrected else None))
            db.execute('INSERT INTO completion_events(habit_id,day,action,recorded_at) VALUES(?,?,?,?)',(habit_id,day.isoformat(),('correction: ' if corrected else '')+action,datetime.now(m.TZ).isoformat()))
            xp_after=db.execute('SELECT COALESCE(SUM(earned_xp),0) FROM completions').fetchone()[0]
        if not corrected and action=='full' and xp_after>xp_before:
            session['celebration']={'xp':xp_after-xp_before,'level':xp_after//200+1,'level_up':xp_after//200>xp_before//200}
        stats()  # Latch achievements at the moment they are earned, before undo.

    def toggle(habit_id):
        with m.connection() as db:
            h=db.execute('SELECT * FROM habits WHERE id=? AND archived=0',(habit_id,)).fetchone()
            if not h: abort(404)
            current=db.execute('SELECT state FROM completions WHERE habit_id=? AND completed_on=?',(habit_id,m.today().isoformat())).fetchone()
        try: record(habit_id,m.today(),'undo' if current and current['state']=='full' else 'full')
        except ValueError as e: flash(str(e),'error')
        return go_back()

    @app.post('/habits/<int:habit_id>/minimum')
    def minimum(habit_id):
        try: record(habit_id,m.today(),'minimum');flash('Small start recorded. Upgrade to full whenever you are ready.','success')
        except ValueError as e: flash(str(e),'error')
        return go_back()

    def archive(habit_id):
        with m.connection() as db:
            changed=db.execute('UPDATE habits SET archived=1 WHERE id=? AND archived=0',(habit_id,))
            if not changed.rowcount: abort(404)
        flash('Archived. You can restore it from Habits.','success');return go_back()

    @app.post('/habits/<int:habit_id>/restore')
    def restore_habit(habit_id):
        with m.connection() as db:
            changed=db.execute('UPDATE habits SET archived=0 WHERE id=? AND archived=1',(habit_id,))
            if not changed.rowcount: abort(404)
        flash('Restored.','success');return go_back('habits_page')

    @app.post('/main-quest')
    def main_quest():
        raw=request.form.get('habit_id','')
        with m.connection() as db:
            if raw and (not raw.isdigit() or not db.execute('SELECT 1 FROM habits WHERE id=? AND archived=0',(raw,)).fetchone()): abort(400)
            db.execute('INSERT INTO daily_notes(day,main_habit_id) VALUES(?,?) ON CONFLICT(day) DO UPDATE SET main_habit_id=excluded.main_habit_id',(m.today().isoformat(),int(raw) if raw else None))
        return go_back()

    def achievements():
        data=stats()
        with m.connection() as db: db.execute('UPDATE achievement_unlocks SET seen=1')
        data['new_achievements']=0
        return render_template('achievements.html',page='achievements',**data)

    @app.get('/history')
    def history():
        try:
            selected=date.fromisoformat(request.args.get('day',m.today().isoformat()))
            if selected>m.today() or selected.year<1900: raise ValueError()
        except ValueError: flash('Choose today or an earlier date.','error');return redirect(url_for('history'))
        start=selected.replace(day=1);end=(start+timedelta(days=32)).replace(day=1)-timedelta(days=1)
        with m.connection() as db:
            counts={r['completed_on']:r['n'] for r in db.execute('SELECT completed_on,COUNT(*) n FROM completions WHERE completed_on BETWEEN ? AND ? GROUP BY completed_on',(start.isoformat(),end.isoformat()))}
            records=[dict(r) for r in db.execute('SELECT c.*,h.archived FROM completions c JOIN habits h ON h.id=c.habit_id WHERE completed_on=? ORDER BY c.id',(selected.isoformat(),))]
            eligible=[dict(r) for r in db.execute('SELECT * FROM habits WHERE created_on<=? ORDER BY archived,title',(selected.isoformat(),))]
            audit=[dict(r) for r in db.execute('SELECT e.*,h.title FROM completion_events e JOIN habits h ON h.id=e.habit_id WHERE day=? ORDER BY e.id DESC LIMIT 20',(selected.isoformat(),))]
        cells=calendar.Calendar().monthdatescalendar(selected.year,selected.month)
        return render_template('history.html',page='history',selected=selected,month_name=selected.strftime('%B %Y'),calendar_weeks=cells,month_counts=counts,records=records,eligible=eligible,audit=audit,prev_month=(start-timedelta(days=1)).isoformat(),next_month=(end+timedelta(days=1)).isoformat(),**stats())

    @app.post('/history/check-in')
    def history_checkin():
        try:
            d=date.fromisoformat(request.form.get('day',''))
            record(int(request.form.get('habit_id','0')),d,request.form.get('state',''),True)
            flash('History corrected. The correction is recorded below.','success')
        except (ValueError,OverflowError) as e: flash(str(e) or 'Check the selected day and item.','error')
        return go_back('history')

    @app.get('/review')
    def review():
        now=m.today();start=now-timedelta(days=6);data=stats();suggestions=[]
        with m.connection() as db:
            rows=[dict(r) for r in db.execute("SELECT category_snapshot category,COUNT(*) n FROM completions WHERE state='full' AND completed_on BETWEEN ? AND ? GROUP BY category_snapshot",(start.isoformat(),now.isoformat()))]
            full=db.execute("SELECT COUNT(*) FROM completions WHERE state='full' AND completed_on BETWEEN ? AND ?",(start.isoformat(),now.isoformat())).fetchone()[0]
            small=db.execute("SELECT COUNT(*) FROM completions WHERE state='minimum' AND completed_on BETWEEN ? AND ?",(start.isoformat(),now.isoformat())).fetchone()[0]
            seconds=db.execute("SELECT COALESCE(SUM(elapsed_seconds),0) FROM focus_sessions WHERE status='finished' AND session_on BETWEEN ? AND ?",(start.isoformat(),now.isoformat())).fetchone()[0]
            for h in data['habit_library']:
                planned=sum(1 for i in range(7) if (d:=start+timedelta(days=i)).isoformat()>=h['created_on'] and str(d.weekday()) in h['repeat_days'].split(','))
                if h['weekly_target']: planned=min(planned,h['weekly_target'])
                n=db.execute("SELECT COUNT(*) FROM completions WHERE habit_id=? AND state='full' AND completed_on BETWEEN ? AND ?",(h['id'],start.isoformat(),now.isoformat())).fetchone()[0]
                if planned>n: suggestions.append({'title':h['title'],'missed':planned-n,'done':n,'planned':planned})
            note=db.execute("SELECT value FROM settings WHERE key='review_note'").fetchone()
        return render_template('review.html',page='review',review_start=start,review_full=full,review_small=small,review_minutes=round(seconds/60,1),review_categories=rows,suggestions=sorted(suggestions,key=lambda r:-r['missed']),review_note=note['value'] if note else '',**data)

    @app.post('/review/note')
    def review_note():
        note=request.form.get('note','').strip()
        if len(note)>2000: abort(400)
        with m.connection() as db: db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('review_note',?)",(note,))
        flash('Review note saved.','success');return redirect(url_for('review'))

    def elapsed(row):
        value=row['elapsed_seconds']+(max(0,int(time.time()-row['started_at'])) if row['status']=='running' and row['started_at'] else 0)
        return min(row['planned_seconds'],value)

    @app.get('/focus')
    def focus():
        data=stats();active=data['active_focus']
        if active: active['remaining']=active['planned_seconds']-elapsed(active)
        return render_template('focus.html',page='focus',**data)

    @app.post('/focus/start')
    def focus_start():
        try:
            mins=int(request.form.get('minutes','25'));hid=int(request.form.get('habit_id','0'))
            if not 1<=mins<=180: raise ValueError()
            with m.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                h=db.execute('SELECT * FROM habits WHERE id=? AND archived=0',(hid,)).fetchone()
                if not h: raise ValueError()
                if db.execute("SELECT 1 FROM focus_sessions WHERE status IN ('running','paused')").fetchone(): flash('Finish the current session first.','error')
                else: db.execute('INSERT INTO focus_sessions(habit_id,title,category,planned_seconds,started_at,session_on) VALUES(?,?,?,?,?,?)',(hid,h['title'],h['category'],mins*60,time.time(),m.today().isoformat()))
        except (ValueError,OverflowError): flash('Choose a task and a duration of 1–180 minutes.','error')
        return redirect(url_for('focus'))

    @app.post('/focus/<int:focus_id>/<action>')
    def focus_action(focus_id,action):
        if action not in ('pause','resume','finish'): abort(404)
        with m.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM focus_sessions WHERE id=? AND status IN ('running','paused')",(focus_id,)).fetchone()
            if not row: return redirect(url_for('focus'))
            value=elapsed(row)
            if action=='finish': status='finished';started=None
            elif action=='pause': status='paused';started=None
            else: status='running';started=time.time()
            db.execute('UPDATE focus_sessions SET elapsed_seconds=?,status=?,started_at=? WHERE id=?',(value,status,started,focus_id))
        if action=='finish': flash('Actual focus time saved. Mark the task complete separately when it is done.','success')
        return redirect(url_for('focus'))

    app.view_functions.update(add_habit=add,edit_habit=edit,toggle_habit=toggle,archive_habit=archive,
                              achievements_page=achievements)
    old_routine_edit=app.view_functions['routine_edit']
    def edit_routine(item_id):
        result=old_routine_edit(item_id)
        with m.connection() as db:
            db.execute('UPDATE habits SET scheduled_time=(SELECT scheduled_time FROM routine_items WHERE id=?) WHERE routine_id=?',(item_id,item_id))
        return result
    app.view_functions['routine_edit']=edit_routine
    old_routine_remove=app.view_functions['routine_remove']
    def remove_routine(item_id):
        result=old_routine_remove(item_id)
        with m.connection() as db: db.execute('UPDATE habits SET routine_id=NULL WHERE routine_id=?',(item_id,))
        return result
    app.view_functions['routine_remove']=remove_routine
