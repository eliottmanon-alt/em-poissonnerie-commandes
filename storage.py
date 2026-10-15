"""PostgreSQL on Render; SQLite only for local development and tests."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class StorageUnavailable(Exception):
    pass


class Store:
    def __init__(self):
        self.url = os.environ.get('DATABASE_URL', '').strip()
        self.disabled = bool(os.environ.get('RENDER') and not self.url)
        self.path = Path(os.environ.get('EM_LOCAL_DB', 'data/orders.sqlite3'))
        self.initialized = False

    @contextmanager
    def connect(self):
        if self.disabled:
            raise StorageUnavailable('DATABASE_URL required on Render')
        if self.url:
            import psycopg
            db = psycopg.connect(self.url, connect_timeout=10)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=10)
        try:
            if not self.initialized:
                db.execute('CREATE TABLE IF NOT EXISTS em_orders (id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL, payload TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS em_settings (name TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                db.commit()
                self.initialized = True
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def run(self, db, sql, params=()):
        return db.execute(sql.replace('?', '%s') if self.url else sql, params)

    def insert(self, record, request_id, digest):
        with self.connect() as db:
            self.run(db, 'INSERT INTO em_orders (id,request_id,request_hash,payload) VALUES (?,?,?,?) ON CONFLICT(request_id) DO NOTHING',
                     (record['id'], request_id, digest, json.dumps(record, ensure_ascii=False)))
            row = self.run(db, 'SELECT request_hash,payload FROM em_orders WHERE request_id=?', (request_id,)).fetchone()
            if row[0] != digest:
                raise ValueError('idempotency_conflict')
            saved = json.loads(row[1])
            return saved, saved['id'] == record['id']

    def orders(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in self.run(db, 'SELECT payload FROM em_orders ORDER BY id').fetchall()]

    def set_status(self, order_id, status, timestamp):
        with self.connect() as db:
            # Serialize status updates so the full history is preserved.
            if not self.url:
                db.execute('BEGIN IMMEDIATE')
            sql = 'SELECT payload FROM em_orders WHERE id=?' + (' FOR UPDATE' if self.url else '')
            row = self.run(db, sql, (order_id,)).fetchone()
            if not row:
                return False
            record = json.loads(row[0])
            record['status'] = status
            record['status_updated_at'] = timestamp
            record.setdefault('status_history', []).append({'status': status, 'at': timestamp})
            self.run(db, 'UPDATE em_orders SET payload=? WHERE id=?', (json.dumps(record, ensure_ascii=False), order_id))
            return True

    def catalog(self, default):
        with self.connect() as db:
            row = self.run(db, 'SELECT payload FROM em_settings WHERE name=?', ('catalog',)).fetchone()
            return json.loads(row[0]) if row else default

    def save_catalog(self, value):
        with self.connect() as db:
            self.run(db, 'INSERT INTO em_settings (name,payload) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload',
                     ('catalog', json.dumps(value, ensure_ascii=False)))
