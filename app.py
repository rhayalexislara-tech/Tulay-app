from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, jsonify
import sqlite3, hashlib, json, os
from datetime import datetime
from functools import wraps
from authlib.integrations.flask_client import OAuth

app = Flask(__name__)
app.secret_key = os.environ.get('TULAY_SECRET', 'tulay_secret_2025_change_in_prod')

DB = 'tulay.db'
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'avatars')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# ── OAuth setup ───────────────────────────────────────────────────────────────
oauth = OAuth(app)

oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID', 'YOUR_GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET', 'YOUR_GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)


def allowed_file(f):
    return '.' in f and f.rsplit('.', 1)[1].lower() in ALLOWED_EXT

# ── DB helpers ────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_unread_count(user_id):
    conn = get_db()
    n = conn.execute('SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0', (user_id,)).fetchone()[0]
    conn.close()
    return n

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def set_session(user):
    if user is None:
        return
    try:
        user_dict = dict(user)
    except:
        user_dict = {}
    session.update({
        'user_id':       user_dict.get('id'),
        'user_name':     user_dict.get('name',''),
        'user_role':     user_dict.get('role','resident'),
        'user_barangay': user_dict.get('barangay',''),
        'user_avatar':   user_dict.get('avatar', None),
    })

def upsert_oauth_user(email, name, avatar_url, provider):
    """Find existing user by email or create one. Returns user row."""
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    if user:
        # Update avatar if provider gave one and user has none
        if avatar_url and not user['avatar']:
            conn.execute('UPDATE users SET avatar=? WHERE id=?', (avatar_url, user['id']))
            conn.commit()
        conn.close()
        return conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone() if False else user
    # New user — needs role selection
    conn.close()
    return None  # Signal: redirect to role-selection

def create_oauth_user(email, name, avatar_url, role, barangay):
    conn = get_db()
    conn.execute(
        'INSERT INTO users (name,email,password,role,barangay,avatar) VALUES (?,?,?,?,?,?)',
        (name, email, hash_pw(os.urandom(32).hex()), role, barangay, avatar_url)
    )
    conn.commit()
    user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    conn.close()
    return user

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            barangay TEXT NOT NULL DEFAULT '',
            points INTEGER DEFAULT 0,
            bio TEXT DEFAULT '',
            avatar TEXT DEFAULT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL,
            barangay TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            volunteer_id INTEGER DEFAULT NULL,
            volunteer_rating INTEGER DEFAULT NULL,
            volunteer_feedback TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            accepted_at TEXT DEFAULT NULL,
            completed_at TEXT DEFAULT NULL,
            lat REAL DEFAULT NULL,
            lng REAL DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    # Migrations — run every startup to ensure all columns exist
    migrations = [
        "ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN bio TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN barangay TEXT DEFAULT ''",
        "ALTER TABLE requests ADD COLUMN lat REAL DEFAULT NULL",
        "ALTER TABLE requests ADD COLUMN lng REAL DEFAULT NULL",
        "ALTER TABLE requests ADD COLUMN accepted_at TEXT DEFAULT NULL",
        "ALTER TABLE requests ADD COLUMN completed_at TEXT DEFAULT NULL",
        "ALTER TABLE requests ADD COLUMN volunteer_feedback TEXT DEFAULT ''",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except: pass
    conn.commit()
    conn.close()

# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('dashboard') if 'user_id' in session else url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        pw    = hash_pw(request.form['password'])
        conn  = get_db()
        user  = conn.execute('SELECT * FROM users WHERE email=? AND password=?', (email, pw)).fetchone()
        conn.close()
        if user:
            set_session(user)
            flash(f"Maligayang pagbabalik, {user['name'].split()[0]}! 👋", 'success')
            return redirect(url_for('dashboard'))
        flash('Incorrect email or password.', 'error')
    return render_template('login.html')

# ── Google OAuth ──────────────────────────────────────────────────────────────

@app.route('/login/google')
def login_google():
    redirect_uri = url_for('google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
        info  = token.get('userinfo') or oauth.google.userinfo()
        email = info.get('email','').lower()
        name  = info.get('name','')
        avatar= info.get('picture','')
    except Exception as e:
        flash(f'Google login failed: {str(e)}', 'error')
        return redirect(url_for('login'))

    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    conn.close()

    if user:
        # Update avatar if needed
        if avatar and not user['avatar']:
            conn2 = get_db()
            conn2.execute('UPDATE users SET avatar=? WHERE id=?', (avatar, user['id']))
            conn2.commit()
            conn2.close()
            conn3 = get_db()
            user = conn3.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone()
            conn3.close()
        set_session(user)
        flash(f"Maligayang pagbabalik, {user['name'].split()[0]}! 👋", 'success')
        return redirect(url_for('dashboard'))

    # New user — save info to session and ask for role
    session['oauth_pending'] = {'email': email, 'name': name, 'avatar': avatar, 'provider': 'google'}
    return redirect(url_for('oauth_setup'))


# ── OAuth role-selection page (new users only) ────────────────────────────────

@app.route('/oauth-setup', methods=['GET', 'POST'])
def oauth_setup():
    pending = session.get('oauth_pending')
    if not pending:
        return redirect(url_for('login'))

    if request.method == 'POST':
        role     = request.form.get('role', 'resident')
        barangay = request.form.get('barangay', '').strip()
        if not barangay:
            flash('Please enter your barangay.', 'error')
            return render_template('oauth_setup.html', pending=pending)
        user = create_oauth_user(pending['email'], pending['name'], pending['avatar'], role, barangay)
        session.pop('oauth_pending', None)
        set_session(user)
        flash(f"Welcome to TULAY, {user['name'].split()[0]}! 🎉", 'success')
        return redirect(url_for('dashboard'))

    return render_template('oauth_setup.html', pending=pending)

# ── Register (email/password) ─────────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name     = request.form['name'].strip()
        email    = request.form['email'].strip().lower()
        pw       = request.form['password']
        confirm  = request.form['confirm']
        role     = request.form['role']
        barangay = request.form['barangay'].strip()
        if pw != confirm:
            flash('Passwords do not match.', 'error')
            return render_template('register.html')
        if len(pw) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return render_template('register.html')
        conn = get_db()
        if conn.execute('SELECT 1 FROM users WHERE email=?', (email,)).fetchone():
            flash('An account with that email already exists.', 'error')
            conn.close()
            return render_template('register.html')
        conn.execute('INSERT INTO users (name,email,password,role,barangay) VALUES (?,?,?,?,?)',
                     (name, email, hash_pw(pw), role, barangay))
        conn.commit()
        conn.close()
        flash('Account created! You can now log in. 🎉', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    conn       = get_db()
    open_count = conn.execute("SELECT COUNT(*) FROM requests WHERE status='open'").fetchone()[0]
    vol_count  = conn.execute("SELECT COUNT(*) FROM users WHERE role='volunteer'").fetchone()[0]
    resolved   = conn.execute("SELECT COUNT(*) FROM requests WHERE status='completed'").fetchone()[0]
    recent     = conn.execute("""
        SELECT r.*, u.name as requester, u.avatar as req_avatar FROM requests r
        JOIN users u ON r.user_id=u.id ORDER BY r.id DESC LIMIT 4
    """).fetchall()
    unread = get_unread_count(session['user_id'])
    conn.close()
    return render_template('dashboard.html', open_count=open_count, vol_count=vol_count,
                           resolved=resolved, recent=recent, unread=unread)

# ── Requests ──────────────────────────────────────────────────────────────────

@app.route('/requests')
@login_required
def requests_page():
    cat  = request.args.get('category', 'All')
    prio = request.args.get('priority', 'All')
    conn = get_db()
    q = "SELECT r.*, u.name as requester, u.avatar as req_avatar FROM requests r JOIN users u ON r.user_id=u.id WHERE r.status='open'"
    p = []
    if cat  != 'All': q += ' AND r.category=?'; p.append(cat)
    if prio != 'All': q += ' AND r.priority=?';  p.append(prio)
    q += " ORDER BY CASE r.priority WHEN 'Urgent' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, r.id DESC"
    reqs   = conn.execute(q, p).fetchall()
    unread = get_unread_count(session['user_id'])
    conn.close()
    return render_template('requests.html', requests=reqs, selected=cat, priority=prio, unread=unread)

@app.route('/accept/<int:req_id>', methods=['POST'])
@login_required
def accept_request(req_id):
    if session['user_role'] != 'volunteer':
        flash('Only volunteers can accept requests.', 'error')
        return redirect(url_for('requests_page'))
    conn = get_db()
    try:
        req = conn.execute('SELECT * FROM requests WHERE id=?', (req_id,)).fetchone()
        if req and req['status'] == 'open':
            conn.execute("UPDATE requests SET status='accepted', volunteer_id=?, accepted_at=? WHERE id=?",
                         (session['user_id'], datetime.now().strftime('%Y-%m-%d %H:%M'), req_id))
            conn.execute('INSERT INTO notifications (user_id, message) VALUES (?,?)',
                         (req['user_id'], f"✅ A volunteer accepted your request: \"{req['title']}\""))
            conn.commit()
            flash('You accepted this request! ✅', 'success')
        else:
            flash('This request is no longer available.', 'error')
    except Exception as e:
        conn.rollback(); flash(f'Error: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(url_for('requests_page'))

@app.route('/complete/<int:req_id>', methods=['POST'])
@login_required
def complete_request(req_id):
    conn = get_db()
    try:
        req = conn.execute('SELECT * FROM requests WHERE id=? AND user_id=?',
                           (req_id, session['user_id'])).fetchone()
        if req and req['status'] == 'accepted':
            conn.execute("UPDATE requests SET status='completed', completed_at=? WHERE id=?",
                         (datetime.now().strftime('%Y-%m-%d %H:%M'), req_id))
            if req['volunteer_id']:
                pts = 10 if req['priority'] == 'Urgent' else 7 if req['priority'] == 'Medium' else 5
                conn.execute('UPDATE users SET points=points+? WHERE id=?', (pts, req['volunteer_id']))
                conn.execute('INSERT INTO notifications (user_id, message) VALUES (?,?)',
                             (req['volunteer_id'], f"🏅 You earned {pts} points for completing \"{req['title']}\"!"))
            conn.commit()
            flash('Request completed! Please rate the volunteer. 🙏', 'success')
        else:
            flash('Could not complete this request.', 'error')
    except Exception as e:
        conn.rollback(); flash(f'Error: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(url_for('my_requests'))

@app.route('/rate/<int:req_id>', methods=['POST'])
@login_required
def rate_volunteer(req_id):
    rating   = int(request.form.get('rating', 5))
    feedback = request.form.get('feedback', '').strip()
    conn = get_db()
    try:
        req = conn.execute('SELECT * FROM requests WHERE id=? AND user_id=?',
                           (req_id, session['user_id'])).fetchone()
        if req and req['status'] == 'completed' and req['volunteer_rating'] is None:
            conn.execute('UPDATE requests SET volunteer_rating=?, volunteer_feedback=? WHERE id=?',
                         (rating, feedback, req_id))
            if req['volunteer_id']:
                conn.execute('INSERT INTO notifications (user_id, message) VALUES (?,?)',
                             (req['volunteer_id'], f"⭐ You received a {rating}-star rating for \"{req['title']}\"!"))
            conn.commit()
            flash('Rating submitted! Salamat. 🙏', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error: {str(e)}', 'error')
    finally:
        conn.close()
    return redirect(url_for('my_requests'))

# ── My Requests ───────────────────────────────────────────────────────────────

@app.route('/my-requests')
@login_required
def my_requests():
    conn = get_db()
    if session['user_role'] == 'resident':
        reqs = conn.execute("""
            SELECT r.*, u.name as vol_name, u.avatar as vol_avatar FROM requests r
            LEFT JOIN users u ON r.volunteer_id=u.id
            WHERE r.user_id=? ORDER BY r.id DESC
        """, (session['user_id'],)).fetchall()
    else:
        reqs = conn.execute("""
            SELECT r.*, u.name as requester, u.avatar as req_avatar FROM requests r
            JOIN users u ON r.user_id=u.id
            WHERE r.volunteer_id=? ORDER BY r.id DESC
        """, (session['user_id'],)).fetchall()
    unread = get_unread_count(session['user_id'])
    conn.close()
    return render_template('my_requests.html', requests=reqs, unread=unread)

# ── Submit ────────────────────────────────────────────────────────────────────

@app.route('/submit', methods=['GET', 'POST'])
@login_required
def submit():
    if session['user_role'] != 'resident':
        flash('Only residents can submit help requests.', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        lat = request.form.get('lat') or None
        lng = request.form.get('lng') or None
        lat = float(lat) if lat else None
        lng = float(lng) if lng else None
        conn = get_db()
        conn.execute('INSERT INTO requests (user_id,title,description,category,priority,barangay,lat,lng) VALUES (?,?,?,?,?,?,?,?)',
                     (session['user_id'], request.form['title'], request.form['description'],
                      request.form['category'], request.form['priority'], request.form['barangay'], lat, lng))
        volunteers = conn.execute("SELECT id FROM users WHERE role='volunteer'").fetchall()
        title = request.form['title']; barangay = request.form['barangay']; priority = request.form['priority']
        for vol in volunteers:
            conn.execute('INSERT INTO notifications (user_id, message) VALUES (?,?)',
                         (vol['id'], f"🆕 New help request: \"{title}\" in {barangay} — Priority: {priority}"))
        conn.commit(); conn.close()
        flash('Request submitted! Volunteers have been notified. 🙌', 'success')
        return redirect(url_for('my_requests'))
    unread = get_unread_count(session['user_id'])
    return render_template('submit.html', barangay=session.get('user_barangay', ''), unread=unread)

# ── Map ───────────────────────────────────────────────────────────────────────

@app.route('/map')
@login_required
def map_page():
    unread = get_unread_count(session['user_id'])
    return render_template('map.html', unread=unread)

@app.route('/api/map-requests')
@login_required
def map_requests():
    conn = get_db()
    reqs = conn.execute("""
        SELECT r.id, r.title, r.category, r.priority, r.barangay,
               r.status, r.lat, r.lng, u.name as requester, u.avatar as req_avatar
        FROM requests r JOIN users u ON r.user_id=u.id
        WHERE r.status='open' AND r.lat IS NOT NULL AND r.lng IS NOT NULL
    """).fetchall()
    conn.close()
    return Response(json.dumps([dict(r) for r in reqs]), mimetype='application/json')

# ── Profile ───────────────────────────────────────────────────────────────────

@app.route('/profile')
@login_required
def profile():
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if user is None:
        session.clear()
        flash('Session expired. Please log in again.', 'error')
        conn.close()
        return redirect(url_for('login'))
    if session['user_role'] == 'volunteer':
        completed = conn.execute("SELECT COUNT(*) FROM requests WHERE volunteer_id=? AND status='completed'", (session['user_id'],)).fetchone()[0]
        accepted  = conn.execute("SELECT COUNT(*) FROM requests WHERE volunteer_id=? AND status='accepted'", (session['user_id'],)).fetchone()[0]
        avg_r     = conn.execute("SELECT AVG(volunteer_rating) FROM requests WHERE volunteer_id=? AND volunteer_rating IS NOT NULL", (session['user_id'],)).fetchone()[0]
        stats = {'completed': completed, 'accepted': accepted, 'avg_rating': round(avg_r,1) if avg_r else None}
    else:
        submitted = conn.execute("SELECT COUNT(*) FROM requests WHERE user_id=?", (session['user_id'],)).fetchone()[0]
        completed = conn.execute("SELECT COUNT(*) FROM requests WHERE user_id=? AND status='completed'", (session['user_id'],)).fetchone()[0]
        stats = {'submitted': submitted, 'completed': completed}
    unread = get_unread_count(session['user_id'])
    conn.close()
    return render_template('profile.html', user=user, stats=stats, unread=unread)

@app.route('/profile/edit', methods=['POST'])
@login_required
def edit_profile():
    bio      = request.form.get('bio', '').strip()
    barangay = request.form.get('barangay', '').strip()
    avatar_url = None
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"avatar_{session['user_id']}.{ext}"
            file.save(os.path.join(UPLOAD_FOLDER, filename))
            avatar_url = f"/static/avatars/{filename}"
    conn = get_db()
    if avatar_url:
        conn.execute('UPDATE users SET bio=?, barangay=?, avatar=? WHERE id=?',
                     (bio, barangay, avatar_url, session['user_id']))
        session['user_avatar'] = avatar_url
    else:
        conn.execute('UPDATE users SET bio=?, barangay=? WHERE id=?', (bio, barangay, session['user_id']))
    conn.commit(); conn.close()
    session['user_barangay'] = barangay
    flash('Profile updated! ✅', 'success')
    return redirect(url_for('profile'))

# ── Notifications ─────────────────────────────────────────────────────────────

@app.route('/notifications')
@login_required
def notifications():
    conn   = get_db()
    notifs = conn.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC', (session['user_id'],)).fetchall()
    conn.execute('UPDATE notifications SET is_read=1 WHERE user_id=?', (session['user_id'],))
    conn.commit(); conn.close()
    return render_template('notifications.html', notifications=notifs, unread=0)

@app.route('/api/unread')
@login_required
def api_unread():
    return jsonify({'count': get_unread_count(session['user_id'])})

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
