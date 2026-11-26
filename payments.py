"""Card deposits through hosted Stripe Checkout; disabled until explicitly enabled.

Unpaid attempts stay separate from confirmed orders. Never trust a browser's
amount or success URL. A signed Stripe event is required for fulfillment.
"""
import hashlib
import json
import os
import re
import secrets
import time
from collections import defaultdict, deque
from threading import Lock
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse

import stripe
from flask import jsonify, request
import order_mail


def enabled():
    return os.environ.get('EM_DEPOSIT_ENABLED', '').strip() == '1'


def settings():
    secret = os.environ.get('STRIPE_SECRET_KEY', '').strip()
    webhook = os.environ.get('STRIPE_WEBHOOK_SECRET', '').strip()
    mode = os.environ.get('EM_STRIPE_MODE', 'test').strip()
    base = os.environ.get('EM_PUBLIC_URL', 'https://commandes.empoissonnerie.com').rstrip('/')
    parsed = urlparse(base)
    ready = (mode in ('test', 'live') and secret.startswith('sk_' + mode + '_')
             and webhook.startswith('whsec_') and parsed.scheme == 'https'
             and bool(parsed.netloc) and not parsed.username and not parsed.query
             and not parsed.fragment and parsed.path in ('', '/'))
    return secret, webhook, mode, base, bool(ready)


def plain(value):
    return value if isinstance(value, dict) else value.to_dict()


def amounts(order):
    total = int((Decimal(str(order['total'])) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    deposit = int((Decimal(total) * Decimal('.20')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    if deposit < 50:
        raise ValueError('deposit_too_small')
    return total, deposit, total - deposit


class Payments:
    def __init__(self, store):
        self.store = store

    def schema(self, db):
        db.execute('CREATE TABLE IF NOT EXISTS em_payment_attempts ('
                   'ref TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, digest TEXT NOT NULL, '
                   'payload TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, '
                   'session_id TEXT UNIQUE, checkout_url TEXT, order_id TEXT)')

    def read(self, ref=None, session_id=None):
        with self.store.connect() as db:
            self.schema(db)
            column, value = ('ref', ref) if ref else ('session_id', session_id)
            row = self.store.run(db, 'SELECT ref,request_id,digest,payload,created,session_id,checkout_url,order_id '
                                 'FROM em_payment_attempts WHERE ' + column + '=?', (value,)).fetchone()
            return self.decode(row)

    @staticmethod
    def decode(row):
        if not row:
            return None
        result = dict(zip(('ref','request_id','digest','record','created','session_id','url','order_id'), row))
        result['record'] = json.loads(result['record'])
        return result

    def draft(self, record, request_id, digest):
        with self.store.connect() as db:
            self.schema(db)
            self.store.run(db, 'INSERT INTO em_payment_attempts(ref,request_id,digest,payload,created) '
                           'VALUES(?,?,?,?,?) ON CONFLICT(request_id) DO NOTHING',
                           (secrets.token_hex(24), request_id, digest, json.dumps(record, ensure_ascii=False), time.time()))
            row = self.store.run(db, 'SELECT ref,request_id,digest,payload,created,session_id,checkout_url,order_id '
                                'FROM em_payment_attempts WHERE request_id=?', (request_id,)).fetchone()
            if row[2] != digest:
                raise ValueError('idempotency_conflict')
            return self.decode(row)

    def bind(self, ref, session):
        with self.store.connect() as db:
            self.schema(db)
            self.store.run(db, 'UPDATE em_payment_attempts SET session_id=?,checkout_url=? '
                           'WHERE ref=? AND (session_id IS NULL OR session_id=?)',
                           (session['id'], session['url'], ref, session['id']))

    def fulfill(self, session):
        """One atomic transaction covers the receipt, order and email outbox."""
        session = plain(session)
        ref = (session.get('metadata') or {}).get('em_payment_ref', '')
        if not re.fullmatch(r'[a-f0-9]{48}', ref):
            return None  # Another integration on the same Stripe account.
        with self.store.connect() as db:
            self.schema(db)
            if not self.store.url:
                db.execute('BEGIN IMMEDIATE')
            suffix = ' FOR UPDATE' if self.store.url else ''
            row = self.store.run(db, 'SELECT ref,request_id,digest,payload,created,session_id,checkout_url,order_id '
                                'FROM em_payment_attempts WHERE ref=?' + suffix, (ref,)).fetchone()
            attempt = self.decode(row)
            if not attempt:
                raise ValueError('unknown_payment')
            record = attempt['record']
            total, deposit, balance = amounts(record['order'])
            expected_live = settings()[2] == 'live'
            if (session.get('payment_status') != 'paid' or session.get('status') != 'complete'
                    or session.get('currency') != 'eur' or type(session.get('amount_total')) is not int
                    or session['amount_total'] != deposit or session.get('livemode') is not expected_live
                    or not session.get('payment_intent') or session.get('mode') != 'payment'
                    or (attempt['session_id'] and attempt['session_id'] != session.get('id'))):
                raise ValueError('payment_mismatch')
            if attempt['order_id']:
                saved = self.store.run(db, 'SELECT payload FROM em_orders WHERE id=?', (attempt['order_id'],)).fetchone()
                return json.loads(saved[0])
            # Normalize the immutable saved draft, never client-supplied payment data.
            paid_at = datetime.now(ZoneInfo('Europe/Paris')).isoformat()
            record.update(confirmedAt=paid_at, created_at=paid_at, source='site-stripe-deposit',
                          status='new', status_history=[{'status':'new','at':paid_at}])
            record['payment'] = {'status':'deposit_paid','provider':'stripe','currency':'eur',
                                 'deposit_percent':20,'total_cents':total,'deposit_paid_cents':deposit,
                                 'balance_due_cents':balance,'paid_at':paid_at,
                                 'stripe_session_id':session['id'],'stripe_payment_intent':session['payment_intent'],
                                 'balance_methods':['card','cash']}
            self.store.run(db, 'INSERT INTO em_orders(id,request_id,request_hash,payload) VALUES(?,?,?,?)',
                           (record['id'], 'stripe-' + ref, attempt['digest'], json.dumps(record,ensure_ascii=False)))
            for role in ['professional'] + (['customer'] if record['customer'].get('email') else []):
                self.store.run(db, 'INSERT INTO em_order_mail(order_id,role,state) VALUES(?,?,?) ON CONFLICT(order_id,role) DO NOTHING',
                               (record['id'],role,'pending'))
            self.store.run(db, 'UPDATE em_payment_attempts SET order_id=?,session_id=? WHERE ref=?',
                           (record['id'],session['id'],ref))
            return record


def register_payments(app, store, validate, make_record):
    payments = Payments(store)
    attempts_by_ip = defaultdict(deque)
    rate_lock = Lock()

    @app.get('/api/payments/config')
    def payment_config():
        return jsonify(ok=True, enabled=enabled(), ready=settings()[4], deposit_percent=20,
                       mode=settings()[2] if enabled() else 'disabled')

    @app.post('/api/payments/checkout')
    def checkout():
        origin = request.headers.get('Origin')
        if origin and origin != settings()[3]:
            return jsonify(ok=False,error='invalid_origin'),403
        if not request.is_json:
            return jsonify(ok=False,error='json_required'),400
        with rate_lock:
            current = time.monotonic()
            for address in list(attempts_by_ip):
                if not attempts_by_ip[address] or attempts_by_ip[address][-1] < current - 60:
                    del attempts_by_ip[address]
            recent = attempts_by_ip[request.remote_addr or 'unknown']
            while recent and recent[0] < current - 60:
                recent.popleft()
            if len(recent) >= 60:
                return jsonify(ok=False,error='rate_limited',message='Trop de tentatives. Patientez une minute avant de réessayer.'),429
            recent.append(current)
        if not enabled() or not settings()[4]:
            return jsonify(ok=False,error='payment_unavailable',message='Le paiement en ligne n’est pas encore disponible.'),503
        payload = request.get_json(silent=True)
        try:
            order, customer = validate(payload)
            if not customer.get('email'):
                raise ValueError('email_required')
            amounts(order)
            request_id = request.headers.get('Idempotency-Key', '')
            if not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', request_id):
                raise ValueError('missing_request_id')
            digest = hashlib.sha256(json.dumps({'order':order,'customer':customer},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            attempt = payments.draft(make_record(order,customer), request_id, digest)
        except ValueError as error:
            code = str(error)
            message = ('Ajoutez une adresse e-mail pour recevoir votre confirmation.' if code == 'email_required' else
                       'Le panier est trop petit pour un acompte par carte (minimum 0,50 €).' if code == 'deposit_too_small' else
                       'Vérifiez votre sélection, vos coordonnées et le créneau de retrait.')
            return jsonify(ok=False,error=code,message=message), (409 if code=='idempotency_conflict' else 400)
        if attempt['order_id']:
            return jsonify(ok=True, paid=True, session_id=attempt['session_id'])
        key, _, _, base, _ = settings()
        if attempt['session_id']:
            try:
                existing = plain(stripe.StripeClient(key,max_network_retries=1,http_client=stripe.RequestsClient(timeout=12)).v1.checkout.sessions.retrieve(attempt['session_id']))
                if existing.get('payment_status') == 'paid':
                    return jsonify(ok=True,paid=True,session_id=attempt['session_id'])
                if existing.get('status') == 'expired':
                    return jsonify(ok=False,error='payment_expired',message='La session a expiré. Relancez le paiement.'),409
                return jsonify(ok=True,checkout_url=attempt['url'],session_id=attempt['session_id'])
            except Exception:
                return jsonify(ok=False,error='checkout_unavailable',message='Impossible de vérifier le paiement précédent. Ne payez pas une seconde fois ; réessayez dans un instant.'),502
        # Never recreate an ambiguous session outside its bounded retry window.
        if time.time() > attempt['created'] + 1750:
            return jsonify(ok=False,error='payment_review_required',message='Cette tentative doit être vérifiée avant de payer à nouveau. Contactez EM Poissonnerie.'),409
        _, deposit, _ = amounts(order)
        try:
            client = stripe.StripeClient(key, max_network_retries=1, http_client=stripe.RequestsClient(timeout=12))
            session = client.v1.checkout.sessions.create({
                'mode':'payment','payment_method_types':['card'],'locale':'fr',
                'customer_email':customer['email'],'client_reference_id':attempt['ref'],
                'metadata':{'em_payment_ref':attempt['ref']},
                'payment_intent_data':{'metadata':{'em_payment_ref':attempt['ref']}},
                'line_items':[{'price_data':{'currency':'eur','unit_amount':deposit,
                                           'product_data':{'name':'Acompte 20 % — EM Poissonnerie',
                                                           'description':'Réservation et préparation de votre plateau. Solde au retrait, par carte ou espèces.'}},'quantity':1}],
                'success_url':base+'/commandes/confirmation.html?session_id={CHECKOUT_SESSION_ID}',
                'cancel_url':base+'/commandes/confirmation.html?payment_cancelled=1',
                'expires_at':int(attempt['created'])+3600,
            }, options={'idempotency_key':'em-deposit-'+attempt['ref']})
            if urlparse(session['url']).scheme != 'https' or urlparse(session['url']).hostname != 'checkout.stripe.com':
                raise ValueError('invalid_checkout_url')
            payments.bind(attempt['ref'], session)
            return jsonify(ok=True,checkout_url=session['url'],session_id=session['id'])
        except Exception as error:
            # Log categories only: Stripe error messages can contain API secrets.
            category = type(error).__name__
            status = getattr(error, 'http_status', None)
            status = status if type(status) is int else None
            app.logger.warning('Stripe Checkout unavailable; no order confirmed (category=%s, http_status=%s)', category, status)
            return jsonify(ok=False,error='checkout_unavailable',message='Le paiement est temporairement indisponible. Votre panier est conservé ; réessayez.'),502

    @app.get('/api/payments/status')
    def payment_status():
        session_id = request.args.get('session_id','')
        if not re.fullmatch(r'cs_(?:test_|live_)?[A-Za-z0-9_]{16,200}',session_id):
            return jsonify(ok=False,error='invalid_session'),400
        attempt = payments.read(session_id=session_id)
        if not attempt:
            return jsonify(ok=False,error='not_found'),404
        total, deposit, balance = amounts(attempt['record']['order'])
        # No customer information is exposed through this capability URL.
        return jsonify(ok=True,paid=bool(attempt['order_id']),order_id=attempt['order_id'],
                       total_cents=total,deposit_paid_cents=deposit if attempt['order_id'] else 0,
                       balance_due_cents=balance if attempt['order_id'] else total)

    @app.post('/api/payments/webhook')
    def webhook():
        key, secret, _, _, ready = settings()
        if not ready:
            return jsonify(ok=False,error='payment_unavailable'),503
        try:
            event = stripe.Webhook.construct_event(request.get_data(),request.headers.get('Stripe-Signature',''),secret,tolerance=300)
        except (ValueError,stripe.SignatureVerificationError):
            return jsonify(ok=False,error='invalid_signature'),400
        if event['type'] not in ('checkout.session.completed','checkout.session.async_payment_succeeded'):
            return jsonify(ok=True)
        session = plain(event['data']['object'])
        if session.get('payment_status') != 'paid':
            return jsonify(ok=True)
        try:
            # Retrieve the authoritative session; do not rely on return-page flags.
            verified = stripe.StripeClient(key,max_network_retries=1,http_client=stripe.RequestsClient(timeout=12)).v1.checkout.sessions.retrieve(session['id'])
            saved = payments.fulfill(verified)
        except ValueError:
            app.logger.error('Stripe payment verification mismatch; not confirmed')
            return jsonify(ok=False,error='payment_mismatch'),400
        except Exception:
            app.logger.warning('Stripe fulfillment pending; webhook must retry')
            return jsonify(ok=False,error='fulfillment_pending'),503
        if saved:
            order_mail.deliver(store,saved,app.logger)
        return jsonify(ok=True)

    return payments
