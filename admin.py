"""Durable visual editor storage, isolated from orders and PC sync."""
import base64
import hashlib
import io
import bleach
from bleach.css_sanitizer import CSSSanitizer
import json
import secrets
import threading
import time
from datetime import timedelta
from flask.sessions import SecureCookieSessionInterface

from flask import Blueprint, jsonify, request, session, send_file, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

PAGES = {'accueil', 'commandes', 'commandes-informations', 'commandes-confirmation'}
EMPTY = {'styles': {}, 'texts': {}, 'images': {}, 'orders': {}, 'hidden': {}, 'groups': {}}
LOCK = threading.RLock()


class Conflict(Exception):
    pass


class AdminStore:
    def __init__(self, store):
        self.store = store

    def init(self):
        with LOCK, self.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS em_admin_document (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS em_admin_media (id TEXT PRIMARY KEY, mime TEXT NOT NULL, data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS em_admin_versions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL, kind TEXT NOT NULL DEFAULT \'published\')')
            db.execute('CREATE TABLE IF NOT EXISTS em_admin_private (name TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            self.store.run(db, 'INSERT INTO em_admin_document (id,revision,payload) VALUES (1,0,?) ON CONFLICT(id) DO NOTHING', (json.dumps({'pages': {}, 'panel': None}),))
            self.store.run(db, 'INSERT INTO em_admin_private (name,payload) VALUES (?,?) ON CONFLICT(name) DO NOTHING', ('auth', json.dumps({'secret': secrets.token_hex(32)})))

    def auth(self):
        with self.store.connect() as db:
            return json.loads(self.store.run(db, 'SELECT payload FROM em_admin_private WHERE name=?', ('auth',)).fetchone()[0])

    def read(self):
        with self.store.connect() as db:
            row = db.execute('SELECT revision,payload FROM em_admin_document WHERE id=1').fetchone()
            return {'revision': row[0], **json.loads(row[1])}

    def change(self, revision, edit):
        with LOCK, self.store.connect() as db:
            if not self.store.url:
                db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision,payload FROM em_admin_document WHERE id=1' + (' FOR UPDATE' if self.store.url else '')).fetchone()
            if row[0] != revision:
                raise Conflict()
            data = json.loads(row[1])
            edit(db, data)
            self.store.run(db, 'UPDATE em_admin_document SET revision=?,payload=? WHERE id=1', (revision + 1, json.dumps(data, ensure_ascii=False)))
            return {'revision': revision + 1, **data}

    def bootstrap(self):
        """Run ONLY from the authenticated Render console; expires after 30 min."""
        token = secrets.token_urlsafe(32)
        with LOCK, self.store.connect() as db:
            auth = self.auth()
            if auth.get('password'):
                raise ValueError('Admin already configured')
            auth.update(setup_hash=hashlib.sha256(token.encode()).hexdigest(), setup_expires=time.time() + 1800)
            self.store.run(db, 'UPDATE em_admin_private SET payload=? WHERE name=?', (json.dumps(auth), 'auth'))
        return token


SAFE_TAGS = {'h1','h2','h3','h4','h5','h6','p','span','a','button','li','strong','small','label','em','b','i','u','br','div','ul','ol','s','sup','sub','img'}
CLEANER_CSS = CSSSanitizer(allowed_css_properties=['color','background-color','font-size','font-weight','font-style','text-decoration','text-align','line-height','letter-spacing'])


def clean_state(value):
    value = json.loads(json.dumps(value))
    for key, html in value.get('texts', {}).items():
        if not isinstance(html, str):
            raise ValueError('invalid_text')
        value['texts'][key] = bleach.clean(html, tags=SAFE_TAGS, attributes={'*': ['class','style','title'], 'a':['href','target','rel'], 'img':['src','alt','width','height']}, protocols={'https','http','mailto','tel'}, css_sanitizer=CLEANER_CSS, strip=True)
    allowed = {'width','height','transform','position','zIndex','left','right','top','bottom'}
    for styles in value.get('styles', {}).values():
        if not isinstance(styles, dict) or set(styles) - allowed:
            raise ValueError('invalid_style')
        for text in styles.values():
            if not isinstance(text, str) or len(text)>150 or any(x in text.lower() for x in ('url','expression','@',';','<','>','\\')):
                raise ValueError('invalid_style')
    for image in value.get('images', {}).values():
        if not isinstance(image, dict):
            raise ValueError('invalid_image')
        src = image.get('src')
        if src and (not isinstance(src, str) or src.startswith(('//','/api/')) or not src.startswith(('/', 'assets/', '../assets/'))):
            raise ValueError('invalid_image_source')
    return value


def valid_state(value):
    if not isinstance(value, dict) or set(value) - (set(EMPTY) | {'panel'}):
        return False
    for key in EMPTY:
        if not isinstance(value.get(key, {}), dict):
            return False
    if len(json.dumps(value)) > 2_000_000:
        return False
    return True


def register_admin(app, store, site):
    data = AdminStore(store)
    ready = False
    bp = Blueprint('visual_admin', __name__)
    app.config.update(SESSION_COOKIE_NAME='em_admin_session', SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_SECURE=bool(store.url),
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8))

    def ensure_ready():
        nonlocal ready
        if not ready:
            with LOCK:
                data.init()
                app.secret_key = data.auth()['secret']
                ready = True

    class AdminSessions(SecureCookieSessionInterface):
        def open_session(self, application, req):
            if req.path == '/admin' or req.path.startswith(('/api/admin/', '/api/appearance')):
                ensure_ready()
            return super().open_session(application, req)

    app.session_interface = AdminSessions()

    @bp.before_request
    def guard():
        ensure_ready()
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            # JSON + exact Origin + CSRF prevents cross-site writes. No permissive CORS.
            origin = request.headers.get('Origin')
            if origin and origin != (('https://' + request.host) if store.url else request.host_url.rstrip('/')):
                return jsonify(error='invalid_origin'), 403
            if not request.is_json:
                return jsonify(error='json_required'), 415
            if not isinstance(request.get_json(silent=True), dict):
                return jsonify(error='invalid_json'), 400
            if request.path not in ('/api/admin/login', '/api/admin/setup'):
                if not session.get('admin'):
                    return jsonify(error='unauthorized'), 401
                if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), session.get('csrf', 'missing')):
                    return jsonify(error='invalid_csrf'), 403
        if request.path.startswith('/api/admin/') and request.path not in ('/api/admin/login', '/api/admin/setup', '/api/admin/session'):
            if not session.get('admin'):
                return jsonify(error='unauthorized'), 401

    @bp.after_request
    def no_cache(response):
        if not request.path.startswith('/api/appearance/media/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @bp.errorhandler(Conflict)
    def conflict(_):
        return jsonify(error='conflict', message='Une autre session a modifié le site. Exportez vos modifications puis rechargez.'), 409

    @bp.get('/admin')
    def admin_page():
        return send_from_directory(site, 'assets/admin/login.html')

    @bp.get('/api/admin/session')
    def session_info():
        return jsonify(authenticated=bool(session.get('admin')), csrf=session.get('csrf') if session.get('admin') else None,
                       configured=bool(data.auth().get('password')))

    def establish():
        session.clear()
        session.update(admin=True, csrf=secrets.token_urlsafe(32))
        session.permanent = True
        return jsonify(ok=True, csrf=session['csrf'])

    def rate_limit(db):
        # Persisted across restarts, keyed by a digest of the remote IP.
        key = 'attempt:' + hashlib.sha256((request.remote_addr or 'unknown').encode()).hexdigest()
        row = store.run(db, 'SELECT payload FROM em_admin_private WHERE name=?', (key,)).fetchone()
        v = json.loads(row[0]) if row else {'time': time.time(), 'count': 0}
        if time.time() - v['time'] > 900:
            v = {'time': time.time(), 'count': 0}
        v['count'] += 1
        store.run(db, 'INSERT INTO em_admin_private (name,payload) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload', (key, json.dumps(v)))
        return v['count'] <= 15

    @bp.post('/api/admin/login')
    def login():
        with LOCK, store.connect() as db:
            allowed = rate_limit(db)
        if not allowed:
            return jsonify(error='rate_limited'), 429
        password = (request.get_json(silent=True) or {}).get('password', '')
        auth = data.auth()
        if not isinstance(password, str) or len(password) > 256 or not auth.get('password') or not check_password_hash(auth['password'], password):
            return jsonify(error='unauthorized'), 401
        return establish()

    @bp.post('/api/admin/setup')
    def setup():
        body = request.get_json(silent=True) or {}
        token, password = body.get('token', ''), body.get('password', '')
        if not isinstance(password, str) or not 12 <= len(password) <= 256 or not isinstance(token, str):
            return jsonify(error='invalid_setup'), 400
        with LOCK, store.connect() as db:
            row = store.run(db, 'SELECT payload FROM em_admin_private WHERE name=?' + (' FOR UPDATE' if store.url else ''), ('auth',)).fetchone()
            auth = json.loads(row[0])
            if auth.get('password') or auth.get('setup_expires', 0) < time.time() or not secrets.compare_digest(auth.get('setup_hash', ''), hashlib.sha256(token.encode()).hexdigest()):
                return jsonify(error='invalid_setup'), 403
            auth['password'] = generate_password_hash(password)
            auth.pop('setup_hash', None)
            auth.pop('setup_expires', None)
            store.run(db, 'UPDATE em_admin_private SET payload=? WHERE name=?', (json.dumps(auth), 'auth'))
        return establish()

    @bp.post('/api/admin/logout')
    def logout():
        session.clear()
        return jsonify(ok=True)

    @bp.get('/api/appearance')
    def appearance():
        return jsonify(data.read())

    @bp.put('/api/admin/page/<page>')
    def save_page(page):
        body = request.get_json(silent=True) or {}
        value = body.get('state')
        if page not in PAGES or type(body.get('revision')) is not int or not valid_state(value):
            return jsonify(error='invalid_settings'), 400
        try:
            value = clean_state(value)
        except (ValueError, TypeError, AttributeError):
            return jsonify(error='invalid_settings'), 400
        def edit(db, doc):
            # Media must already exist durably. Local keys are retained only as recovery metadata.
            for image in value.get('images', {}).values():
                if not isinstance(image, dict):
                    raise ValueError('invalid_image')
                url = image.get('url')
                if url and not (url.startswith('/api/appearance/media/') and store.run(db, 'SELECT id FROM em_admin_media WHERE id=?', (url.rsplit('/', 1)[-1],)).fetchone()):
                    raise ValueError('invalid_image')
            doc['pages'][page] = value
            if 'panel' in body:
                pos = body['panel']
                if pos is not None and (not isinstance(pos, dict) or any(type(pos.get(k)) not in (int, float) or not -10000 < pos[k] < 10000 for k in ('x', 'y'))):
                    raise ValueError('invalid_panel')
                doc['panel'] = pos
        try:
            return jsonify(data.change(body['revision'], edit))
        except ValueError:
            return jsonify(error='invalid_settings'), 400

    @bp.post('/api/admin/media')
    def upload():
        body = request.get_json(silent=True) or {}
        try:
            raw = base64.b64decode(body.get('data', ''), validate=True)
        except (ValueError, TypeError):
            return jsonify(error='invalid_image'), 400
        mime = 'image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else 'image/webp' if raw.startswith(b'RIFF') and raw[8:12] == b'WEBP' else None
        if not mime or not raw or len(raw) > 6 * 1024 * 1024:
            return jsonify(error='invalid_image'), 400
        key = hashlib.sha256(raw).hexdigest()
        with store.connect() as db:
            store.run(db, 'INSERT INTO em_admin_media (id,mime,data) VALUES (?,?,?) ON CONFLICT(id) DO NOTHING', (key, mime, base64.b64encode(raw).decode()))
        return jsonify(url='/api/appearance/media/' + key)

    @bp.get('/api/appearance/media/<key>')
    def media(key):
        with store.connect() as db:
            row = store.run(db, 'SELECT mime,data FROM em_admin_media WHERE id=?', (key,)).fetchone()
        if not row:
            return '', 404
        response = send_file(io.BytesIO(base64.b64decode(row[1])), mimetype=row[0])
        response.headers['Cache-Control'] = 'public,max-age=31536000,immutable'
        return response

    @bp.post('/api/admin/publish')
    def publish():
        body = request.get_json(silent=True) or {}
        key = secrets.token_hex(12)
        def edit(db, doc):
            from datetime import datetime, timezone
            store.run(db, 'INSERT INTO em_admin_versions (id,created_at,payload) VALUES (?,?,?)', (key, datetime.now(timezone.utc).isoformat(), json.dumps(doc, ensure_ascii=False)))
        result = data.change(body.get('revision'), edit)
        return jsonify(**result, published=key)

    @bp.get('/api/admin/versions')
    def versions():
        with store.connect() as db:
            rows = db.execute("SELECT id,created_at FROM em_admin_versions WHERE kind='published' ORDER BY created_at DESC LIMIT 30").fetchall()
        return jsonify(versions=[{'id': r[0], 'created_at': r[1]} for r in rows])

    @bp.post('/api/admin/restore')
    def restore():
        body = request.get_json(silent=True) or {}
        def edit(db, doc):
            row = store.run(db, 'SELECT payload FROM em_admin_versions WHERE id=?', (body.get('id', ''),)).fetchone()
            if not row:
                raise ValueError()
            # Preserve pre-restore state as another recoverable checkpoint.
            from datetime import datetime, timezone
            store.run(db, "INSERT INTO em_admin_versions (id,created_at,payload,kind) VALUES (?,?,?,'recovery')", (secrets.token_hex(12), datetime.now(timezone.utc).isoformat(), json.dumps(doc)))
            doc.clear()
            doc.update(json.loads(row[0]))
        try:
            return jsonify(data.change(body.get('revision'), edit))
        except ValueError:
            return jsonify(error='not_found'), 404

    @bp.get('/api/admin/backup')
    def backup():
        doc = data.read()
        with store.connect() as db:
            versions = [{'id': r[0], 'created_at': r[1], 'document': json.loads(r[2])} for r in db.execute('SELECT id,created_at,payload FROM em_admin_versions ORDER BY created_at').fetchall()]
            images = {r[0]: {'mime': r[1], 'data': r[2]} for r in db.execute('SELECT id,mime,data FROM em_admin_media').fetchall()}
        return jsonify(format='em-appearance-backup-v1', document=doc, versions=versions, media=images)

    # Limits for images apply only here; the order API keeps its original limit.
    @app.before_request
    def admin_upload_limit():
        if request.path == '/api/admin/media':
            request.max_content_length = 9 * 1024 * 1024

    app.register_blueprint(bp)
    return data
