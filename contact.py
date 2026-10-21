"""Contact-only mail delivery. No access to orders or PC synchronization."""
import hashlib
import json
import os
import re
import threading
import time
from collections import defaultdict, deque
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from flask import Blueprint, current_app, jsonify, request

contact = Blueprint('contact', __name__)
_lock = threading.Lock()
_attempts = defaultdict(deque)


def configured():
    return all(os.environ.get(key, '').strip() for key in
               ('EM_CONTACT_RESEND_KEY', 'EM_CONTACT_FROM', 'EM_CONTACT_TO'))


def limited(email):
    # Bounded, process-local protection for the existing single-worker deployment.
    # No spoofable forwarded-IP header, no contact content retained or logged.
    now = time.monotonic()
    with _lock:
        for key in list(_attempts):
            while _attempts[key] and _attempts[key][0] <= now - 600:
                _attempts[key].popleft()
            if not _attempts[key]:
                del _attempts[key]
        key = hashlib.sha256(email.lower().encode()).hexdigest()
        if len(_attempts.get('*', ())) >= 30 or len(_attempts.get(key, ())) >= 5:
            return True
        _attempts['*'].append(now)
        _attempts[key].append(now)
        return False


def send_contact(fields, request_id):
    payload = {
        'from': os.environ['EM_CONTACT_FROM'],
        'to': [os.environ['EM_CONTACT_TO']],
        'reply_to': fields['email'],
        'subject': '[Contact site EM] ' + fields['subject'],
        'text': '\n'.join(['Nouveau message depuis le formulaire du site EM Poissonnerie.', '',
                           'Nom : ' + fields['name'], 'E-mail : ' + fields['email'],
                           'Téléphone : ' + fields['phone'], 'Objet : ' + fields['subject'],
                           '', fields['message']])
    }
    req = Request('https://api.resend.com/emails', data=json.dumps(payload).encode(), method='POST', headers={
        'Authorization': 'Bearer ' + os.environ['EM_CONTACT_RESEND_KEY'],
        'Content-Type': 'application/json', 'User-Agent': 'EM-Contact/1.0',
        'Idempotency-Key': 'em-contact/' + request_id
    })
    with urlopen(req, timeout=15) as response:
        result = json.load(response)
        if not isinstance(result, dict) or not result.get('id'):
            raise ValueError('Missing provider acknowledgment')
        return result['id']


@contact.post('/api/contact')
def submit():
    origin = request.headers.get('Origin')
    if origin and (urlsplit(origin).netloc != request.host or urlsplit(origin).scheme not in ('http', 'https')):
        return jsonify(ok=False, message='Origine du formulaire invalide.'), 403
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get('website'):
        return jsonify(ok=False, message='Vérifiez le formulaire avant de réessayer.'), 400
    fields = {}
    for key, maximum in [('name', 120), ('email', 254), ('phone', 40), ('subject', 180), ('message', 6000)]:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\x00' in value:
            return jsonify(ok=False, message='Complétez tous les champs du formulaire.'), 400
        fields[key] = value.strip()
        if key != 'message' and ('\r' in value or '\n' in value):
            return jsonify(ok=False, message='Un champ contient un caractère invalide.'), 400
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', fields['email']):
        return jsonify(ok=False, message='Indiquez une adresse e-mail valide.'), 400
    if not 8 <= len(re.sub(r'\D', '', fields['phone'])) <= 18:
        return jsonify(ok=False, message='Indiquez un numéro de téléphone valide.'), 400
    request_id = request.headers.get('Idempotency-Key', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', request_id):
        return jsonify(ok=False, message='Rechargez la page puis réessayez.'), 400
    if not configured():
        return jsonify(ok=False, message='Le formulaire est momentanément indisponible. Écrivez à eliott.manon@empoissonnerie.com.'), 503
    if limited(fields['email']):
        return jsonify(ok=False, message='Trop de tentatives. Merci de réessayer dans dix minutes.'), 429
    try:
        email_id = send_contact(fields, request_id)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        current_app.logger.warning('Contact email provider unavailable')
        return jsonify(ok=False, message='L’envoi n’a pas été confirmé. Vos champs sont conservés : réessayez dans un instant.'), 502
    return jsonify(ok=True, message_id=email_id), 200
