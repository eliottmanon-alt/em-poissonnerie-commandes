"""EM Poissonnerie V10.6: original pages with a real order API."""
import hashlib
import json
import os
import re
import secrets
import unicodedata
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, send_from_directory, redirect
from storage import Store, StorageUnavailable
import order_mail
import payments
from contact import contact, configured as contact_configured

BASE = Path(__file__).resolve().parent
SITE = BASE / 'site'
SEED = json.loads((BASE / 'catalog_seed.json').read_text(encoding='utf-8'))
PRODUCTS = {p['name']: p for p in SEED['products']}
SPECIALS = {'Araignée cuite ½', 'Homard cuit ½', 'Langouste cuite ½'}
API_KEY = os.environ.get('EM_SITE_API_KEY', '').strip()
store = Store()
app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024
app.register_blueprint(contact)

from appearance import render_images
from admin import register_admin
admin_store = register_admin(app, store, SITE)


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
    if request.path.startswith('/api/') and not request.path.startswith('/api/appearance/media/'):
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
                   email_configured=order_mail.configured(), contact_email_configured=contact_configured())


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


def _normalize_promotions(payload):
    rows = payload.get('promotions') if isinstance(payload, dict) else None
    if rows is None and isinstance(payload, dict) and payload.get('id'):
        current = store.promotions().get('promotions', [])
        rows = [x for x in current if isinstance(x, dict) and x.get('id') != payload.get('id')] + [payload]
    if not isinstance(rows, list) or len(rows) > 2:
        raise ValueError('invalid_promotions')
    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid_promotions')
        promo_id = str(row.get('id') or '').strip()
        if promo_id not in ('promo-1', 'promo-2') or promo_id in seen:
            raise ValueError('invalid_promotions')
        seen.add(promo_id)
        slot = 1 if promo_id == 'promo-1' else 2
        title = str(row.get('title') or '').strip()[:160]
        price = str(row.get('price') or '').strip()[:80]
        unit = str(row.get('unit') or '€/kg').strip()
        if unit not in ('€/kg', 'le lot'):
            raise ValueError('invalid_promotion_unit')
        origin = str(row.get('origin') or '').strip()[:200]
        photo = str(row.get('photo') or '').strip()
        if photo and (not photo.startswith('data:image/') or ';base64,' not in photo or len(photo) > 3_500_000):
            raise ValueError('invalid_promotion_photo')
        start_date = str(row.get('start_date') or '').strip()
        end_date = str(row.get('end_date') or '').strip()
        if start_date or end_date:
            try:
                start_day = datetime.strptime(start_date, '%Y-%m-%d').date()
                end_day = datetime.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                raise ValueError('invalid_promotion_dates')
            if end_day < start_day:
                raise ValueError('invalid_promotion_dates')
        active = bool(row.get('active'))
        if active and (not title or not price or not start_date or not end_date):
            raise ValueError('incomplete_promotion')
        normalized.append({
            'id': promo_id, 'slot': slot, 'active': active, 'title': title, 'price': price,
            'unit': unit, 'origin': origin, 'photo': photo, 'start_date': start_date, 'end_date': end_date,
            'updated_at': str(row.get('updated_at') or now())[:80]
        })
    for promo_id, slot in [('promo-1', 1), ('promo-2', 2)]:
        if promo_id not in seen:
            normalized.append({'id': promo_id, 'slot': slot, 'active': False, 'title': '', 'price': '',
                               'unit': '€/kg', 'origin': '', 'photo': '', 'start_date': '', 'end_date': '', 'updated_at': now()})
    normalized.sort(key=lambda x: x['slot'])
    return {'promotions': normalized, 'updated_at': now()}


def promotion_is_current(row):
    if not isinstance(row, dict) or not row.get('active'):
        return False
    start_text = str(row.get('start_date') or '').strip()
    end_text = str(row.get('end_date') or '').strip()
    # Backward compatibility: promotions published by older desktop versions
    # had no validity dates. Keep them visible until they are republished with dates.
    if not start_text and not end_text:
        return True
    if not start_text or not end_text:
        return False
    try:
        today = datetime.now(ZoneInfo('Europe/Paris')).date()
        start_day = datetime.strptime(start_text, '%Y-%m-%d').date()
        end_day = datetime.strptime(end_text, '%Y-%m-%d').date()
        return start_day <= today <= end_day
    except ValueError:
        return False


@app.get('/api/promotions')
def public_promotions():
    if store.disabled:
        return jsonify(promotions=[])
    document = store.promotions()
    rows = [x for x in document.get('promotions', []) if promotion_is_current(x)]
    rows.sort(key=lambda x: int(x.get('slot') or 99))
    return jsonify(promotions=rows, updated_at=document.get('updated_at', ''))


@app.route('/api/sync/promotions', methods=['PUT', 'POST'])
def sync_promotions():
    rejected = denied()
    if rejected:
        return rejected
    payload = request.get_json(silent=True)
    try:
        document = _normalize_promotions(payload)
    except ValueError as error:
        return jsonify(ok=False, error=str(error)), 400
    store.save_promotions(document)
    return jsonify(ok=True, promotions_received=len(document['promotions']),
                   active=sum(1 for x in document['promotions'] if x.get('active')))


def promotion_price(value):
    text = str(value or '').strip().replace('\u202f', '').replace(' ', '').replace(',', '.')
    match = re.search(r'(\d+(?:\.\d{1,2})?)', text)
    if not match:
        raise ValueError('invalid_promotion_price')
    amount = Decimal(match.group(1))
    if amount <= 0 or amount > Decimal('10000'):
        raise ValueError('invalid_promotion_price')
    return amount


def active_promotions():
    if store.disabled:
        return {}
    document = store.promotions()
    return {
        str(row.get('id')): row
        for row in document.get('promotions', [])
        if promotion_is_current(row) and row.get('id')
    }


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
    if not isinstance(items, list) or not isinstance(special, list) or len(items) > len(PRODUCTS) + 2 or len(special) > len(SPECIALS):
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
    promos = active_promotions()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('invalid_items')
        quantity = item.get('quantity')
        promo_id = str(item.get('promoId') or '').strip()
        if promo_id:
            if type(quantity) not in (int, float) or isinstance(quantity, bool) or not 0 < quantity <= 1000:
                raise ValueError('invalid_items')
            promo = promos.get(promo_id)
            if not promo or promo_id in seen:
                raise ValueError('invalid_promotion')
            seen.add(promo_id)
            price = promotion_price(promo.get('price'))
            line = price * quantity
            total += line
            unit = 'kg' if promo.get('unit') == '€/kg' else 'lot'
            normalized.append({
                'name': str(promo.get('title') or 'Promotion')[:160],
                'unit': unit,
                'price': float(price),
                'quantity': quantity,
                'lineTotal': float(line),
                'promoId': promo_id,
                'promotion': True,
                'origin': str(promo.get('origin') or '')[:200]
            })
            continue

        if type(quantity) is not int or not 1 <= quantity <= 1000:
            raise ValueError('invalid_items')
        if not isinstance(item.get('name'), str):
            raise ValueError('invalid_items')
        product = PRODUCTS.get(item['name'])
        if not product or item['name'] in seen:
            raise ValueError('invalid_items')
        seen.add(item['name'])
        price = Decimal(str(product['price']))
        line = price * quantity
        total += line
        normalized.append({'name': product['name'], 'unit': product['unit'], 'price': float(price), 'quantity': quantity, 'lineTotal': float(line)})
    clean = dict(order)
    clean.update(items=normalized, specialRequests=list(dict.fromkeys(special)), total=float(total), average=round(float(total) / guests, 2), giftUnlocked=total >= 80)
    return clean, customer


def make_order_record(order, customer):
    timestamp = now()
    client_name = unicodedata.normalize('NFKD', customer['lastName']).encode('ascii', 'ignore').decode().upper()
    client_name = re.sub(r'[^A-Z0-9]+', '-', client_name).strip('-')[:40] or 'CLIENT'
    record = {'id': 'WEB-' + datetime.now(ZoneInfo('Europe/Paris')).strftime('%Y%m%d') + '-' + client_name + '-' + secrets.token_hex(4).upper(),
              'created_at': timestamp, 'status': 'new', 'order': order, 'customer': customer,
              'confirmedAt': timestamp, 'status_history': [{'status': 'new', 'at': timestamp}], 'source': 'site-v10.6-test'}
    return record


@app.post('/api/orders')
def create_order():
    if payments.enabled():
        return jsonify(ok=False, error='deposit_required', message='Le paiement de l’acompte est requis avant validation.'), 402
    payload = request.get_json(silent=True)
    try:
        order, customer = validate(payload)
    except ValueError as error:
        return jsonify(ok=False, error=str(error), message='Vérifiez les produits, vos coordonnées et le créneau de retrait.'), 400
    request_id = request.headers.get('Idempotency-Key', '') or payload.get('requestId')
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', request_id):
        return jsonify(ok=False, error='missing_request_id'), 400
    digest = hashlib.sha256(json.dumps({'order': order, 'customer': customer}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    record = make_order_record(order, customer)
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
    email_sent = order_mail.deliver(store, saved, app.logger)
    return jsonify(ok=True, order_id=saved['id'], status=saved['status'], email_sent=email_sent), (201 if created else 200)


@app.get('/api/sync/orders')
def sync_orders():
    rejected = denied()
    if rejected:
        return rejected
    for pending in store.pending_mail(limit=1):
        order_mail.deliver(store, pending, app.logger)
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


APPEARANCE_PAGES = {
    'index.html': 'accueil',
    'commandes/index.html': 'commandes',
    'commandes/informations.html': 'commandes-informations',
    'commandes/confirmation.html': 'commandes-confirmation',
}


def site_page(name):
    """Ship the current public settings in the HTML, avoiding a second round trip."""
    page = APPEARANCE_PAGES[name]
    document = admin_store.read()
    public = {'revision': document['revision'], 'panel': document['panel'],
              'pages': {page: document['pages'].get(page, {})}}
    # Escape HTML delimiters so even text containing </script> stays inert JSON.
    encoded = json.dumps(public, ensure_ascii=True).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    bootstrap = (
        '<script id="emAppearanceBootstrap" type="application/json">' + encoded + '</script>'
    )
    content = render_images((SITE / name).read_text(encoding='utf-8'), page, public['pages'][page]).replace('</head>', bootstrap + '</head>', 1)
    return app.response_class(content, mimetype='text/html', headers={'Cache-Control': 'no-store'})


@app.get('/')
def index():
    return site_page('index.html')


@app.get('/<path:name>')
def static_site(name):
    path = (SITE / name).resolve()
    if SITE.resolve() not in path.parents:
        return 'Not found', 404
    if path.is_dir() and (path / 'index.html').is_file():
        if not request.path.endswith('/'):
            return redirect(request.path + '/')
        name = str(Path(name) / 'index.html')
    if name in APPEARANCE_PAGES:
        return site_page(name)
    return send_from_directory(SITE, name)


payment_store = payments.register_payments(app, store, validate, make_order_record)

# Temporary startup diagnostic: only non-sensitive promotion metadata.
try:
    _promo_doc = store.promotions()
    _promo_rows = []
    for _p in _promo_doc.get('promotions', []) if isinstance(_promo_doc, dict) else []:
        if isinstance(_p, dict):
            _promo_rows.append({
                'id': _p.get('id'), 'active': bool(_p.get('active')), 'title': _p.get('title'),
                'start_date': _p.get('start_date'), 'end_date': _p.get('end_date')
            })
    app.logger.warning('PROMO_DIAG %s', json.dumps(_promo_rows, ensure_ascii=False))
except Exception as _promo_diag_error:
    app.logger.warning('PROMO_DIAG_ERROR %s', type(_promo_diag_error).__name__)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '8765')))
