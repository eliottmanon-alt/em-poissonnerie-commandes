"""EM Poissonnerie V10.6: original pages with a real order API."""
import hashlib
import json
import os
import re
import secrets
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, send_from_directory, redirect
from storage import Store, StorageUnavailable
from contact import contact, configured as contact_configured

BASE = Path(__file__).resolve().parent
SITE = BASE / 'site'
SEED = json.loads((BASE / 'catalog_seed.json').read_text(encoding='utf-8'))
PRODUCTS = {p['name']: p for p in SEED['products']}
SPECIALS = {'Araignée cuite ½', 'Homard cuit ½', 'Langouste cuite ½'}
API_KEY = os.environ.get('EM_SITE_API_KEY', '').strip()
store = Store()
app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 512 * 1024
app.register_blueprint(contact)


def now():
    return datetime.now(ZoneInfo('Europe/Paris')).isoformat(timespec='microseconds')


def denied():
    if API_KEY and secrets.compare_digest(request.headers.get('X-EM-API-Key', ''), API_KEY):
        return None
    return jsonify(ok=False, error='unauthorized'), 401


@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.errorhandler(StorageUnavailable)
def storage_missing(error):
    return jsonify(ok=False, error='storage_unavailable', message='L’enregistrement des commandes de test n’est pas encore activé. Aucune commande n’a été confirmée.'), 503


@app.errorhandler(413)
def too_large(error):
    return jsonify(ok=False, error='payload_too_large'), 413


@app.get('/api/health')
def health():
    return jsonify(ok=True, name='EM Poissonnerie V10.6', orders_configured=not store.disabled,
                   storage='postgres' if store.url else ('unconfigured' if store.disabled else 'local-sqlite'),
                   email_configured=False, contact_email_configured=contact_configured())


@app.get('/api/sync/ping')
def ping():
    rejected = denied()
    if rejected:
        return rejected
    return jsonify(ok=True, status='authorized', name='EM Poissonnerie Site API')


@app.get('/api/catalog')
def catalog():
    if store.disabled:
        return jsonify(SEED)
    return jsonify(store.catalog(SEED))


@app.put('/api/sync/catalog')
def sync_catalog():
    rejected = denied()
    if rejected:
        return rejected
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get('products'), list):
        return jsonify(ok=False, error='invalid_catalog'), 400
    store.save_catalog(payload)
    return jsonify(ok=True, products_received=len(payload['products']))


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError('invalid_order')
    order, customer = payload.get('order'), payload.get('customer')
    if not isinstance(order, dict) or not isinstance(customer, dict):
        raise ValueError('invalid_order')
    for field in ['firstName', 'lastName', 'phone', 'pickupDate', 'pickupTime']:
        if not isinstance(customer.get(field), str) or not customer[field].strip() or len(customer[field]) > 150:
            raise ValueError('missing_customer')
    for field, max_length in [('email', 254), ('comment', 5000)]:
        value = customer.get(field, '')
        if not isinstance(value, str) or len(value) > max_length:
            raise ValueError('invalid_customer')
    if customer.get('email') and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', customer['email']):
        raise ValueError('invalid_email')
    if len(re.sub(r'\D', '', customer['phone'])) < 8:
        raise ValueError('invalid_phone')
    try:
        day = datetime.strptime(customer['pickupDate'], '%Y-%m-%d').date()
        pickup = datetime.strptime(customer['pickupDate'] + ' ' + customer['pickupTime'], '%Y-%m-%d %H:%M').replace(tzinfo=ZoneInfo('Europe/Paris'))
    except ValueError:
        raise ValueError('invalid_pickup')
    if day.weekday() not in (1, 3, 5) or pickup <= datetime.now(ZoneInfo('Europe/Paris')):
        raise ValueError('invalid_pickup')
    if not re.fullmatch(r'(0[7-9]|1[0-3]):(00|30)', customer['pickupTime']):
        raise ValueError('invalid_pickup')
    items, special = order.get('items', []), order.get('specialRequests', [])
    if not isinstance(items, list) or not isinstance(special, list) or len(items) > len(PRODUCTS) or len(special) > len(SPECIALS):
        raise ValueError('invalid_items')
    if not items and not special:
        raise ValueError('empty_order')
    if any(not isinstance(s, str) or s not in SPECIALS for s in special):
        raise ValueError('invalid_special_request')
    guests = order.get('guests')
    if type(guests) is not int or not 1 <= guests <= 1000:
        raise ValueError('invalid_guests')
    total = Decimal('0')
    normalized = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise ValueError('invalid_items')
        product = PRODUCTS.get(item['name'])
        quantity = item.get('quantity')
        if not product or item['name'] in seen or type(quantity) is not int or not 1 <= quantity <= 1000:
            raise ValueError('invalid_items')
        seen.add(item['name'])
        price = Decimal(str(product['price']))
        line = price * quantity
        total += line
        normalized.append({'name': product['name'], 'unit': product['unit'], 'price': float(price), 'quantity': quantity, 'lineTotal': float(line)})
    clean = dict(order)
    clean.update(items=normalized, specialRequests=list(dict.fromkeys(special)), total=float(total), average=round(float(total) / guests, 2), giftUnlocked=total >= 80)
    return clean, customer


@app.post('/api/orders')
def create_order():
    payload = request.get_json(silent=True)
    try:
        order, customer = validate(payload)
    except ValueError as error:
        return jsonify(ok=False, error=str(error), message='Vérifiez les produits, vos coordonnées et le créneau de retrait.'), 400
    request_id = request.headers.get('Idempotency-Key', '') or payload.get('requestId')
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', request_id):
        return jsonify(ok=False, error='missing_request_id'), 400
    digest = hashlib.sha256(json.dumps({'order': order, 'customer': customer}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    timestamp = now()
    record = {'id': 'WEB-' + datetime.now(ZoneInfo('Europe/Paris')).strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(4).upper(),
              'created_at': timestamp, 'status': 'new', 'order': order, 'customer': customer,
              'confirmedAt': timestamp, 'status_history': [{'status': 'new', 'at': timestamp}], 'source': 'site-v10.6-test'}
    try:
        saved, created = store.insert(record, request_id, digest)
    except ValueError:
        return jsonify(ok=False, error='idempotency_conflict'), 409
    except StorageUnavailable:
        raise
    except Exception:
        # Never put customer data or database credentials into the application log.
        app.logger.error('Order persistence unavailable')
        return jsonify(ok=False, error='storage_unavailable', message='Le serveur ne peut pas enregistrer la commande. Réessayez dans un instant.'), 503
    return jsonify(ok=True, order_id=saved['id'], status=saved['status'], email_sent=False), (201 if created else 200)


@app.get('/api/sync/orders')
def sync_orders():
    rejected = denied()
    if rejected:
        return rejected
    records = store.orders()
    since = request.args.get('since', '').strip()
    if since:
        try:
            threshold = datetime.fromisoformat(since.replace('Z', '+00:00'))
            if threshold.tzinfo is None:
                threshold = threshold.replace(tzinfo=ZoneInfo('Europe/Paris'))
            records = [r for r in records if datetime.fromisoformat(r.get('status_updated_at', r['created_at'])) >= threshold]
        except ValueError:
            return jsonify(ok=False, error='invalid_since'), 400
    return jsonify(ok=True, orders=records)


@app.post('/api/sync/orders/<order_id>/status')
def status(order_id):
    rejected = denied()
    if rejected:
        return rejected
    payload = request.get_json(silent=True)
    value = payload.get('status') if isinstance(payload, dict) else None
    if value not in ('new', 'preparing', 'ready', 'collected', 'cancelled'):
        return jsonify(ok=False, error='invalid_status'), 400
    if not store.set_status(order_id, value, now()):
        return jsonify(ok=False, error='not_found'), 404
    return jsonify(ok=True, id=order_id, status=value)


@app.get('/robots.txt')
def robots():
    return 'User-agent: *\nDisallow: /\n', 200, {'Content-Type': 'text/plain'}


@app.get('/')
def index():
    return send_from_directory(SITE, 'index.html')


@app.get('/<path:name>')
def static_site(name):
    path = (SITE / name).resolve()
    if SITE.resolve() not in path.parents:
        return 'Not found', 404
    if path.is_dir() and (path / 'index.html').is_file():
        if not request.path.endswith('/'):
            return redirect(request.path + '/')
        name = str(Path(name) / 'index.html')
    return send_from_directory(SITE, name)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '8765')))
