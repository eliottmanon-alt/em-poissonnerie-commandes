"""Transactional order receipts, with persistent per-recipient delivery state."""
import json
import os
import time
from decimal import Decimal
from urllib.request import Request, urlopen

PRO_EMAIL = 'eliott.manon@empoissonnerie.com'


def settings():
    return (os.environ.get('EM_ORDER_RESEND_KEY') or os.environ.get('EM_CONTACT_RESEND_KEY', ''),
            os.environ.get('EM_ORDER_FROM') or os.environ.get('EM_CONTACT_FROM', ''))


def configured():
    return all(settings())


def messages(record):
    order, customer = record['order'], record['customer']
    amount = lambda v: f'{Decimal(str(v)):.2f}'.replace('.', ',') + ' €'
    lines = ['EM Poissonnerie — commande enregistrée', '', 'Référence : ' + record['id'],
             'Client : ' + customer['firstName'] + ' ' + customer['lastName'],
             'Retrait : ' + customer['pickupDate'] + ' à ' + customer['pickupTime'],
             'Lieu : marché couvert de Rochefort, 73 rue Toufaire, 17300 Rochefort', '', 'Votre sélection :']
    for item in order['items']:
        lines.append(f"• {item['quantity']} × {item['name']} ({item['unit']}) : {amount(item['lineTotal'])}")
    if order.get('specialRequests'):
        lines += ['', 'PRODUITS SPÉCIAUX DEMANDÉS — À PRÉVOIR :']
        for special in order['specialRequests']:
            lines.append('• ' + special + ' — 1 demi-pièce, prix à confirmer')
        lines.append('')
    lines += ['', 'Total des articles chiffrés : ' + amount(order['total'])]
    payment = record.get('payment', {})
    if payment.get('status') == 'deposit_paid':
        lines += ['', 'Acompte de 20 % payé par carte : ' + amount(Decimal(payment['deposit_paid_cents']) / 100),
                  'Solde à régler au retrait : ' + amount(Decimal(payment['balance_due_cents']) / 100),
                  'Règlement du solde par carte bancaire ou en espèces.']
        if order.get('specialRequests'):
            lines.append('Pièces sur demande : prix à confirmer, non inclus dans le calcul de l’acompte.')
    if order.get('giftUnlocked'):
        lines.append('Une bouteille de Jean Dellac Sauvignon est offerte avec ce plateau.')
    if customer.get('comment'):
        lines += ['', 'Commentaire : ' + customer['comment']]
    lines += ['', 'Pour toute question : ' + PRO_EMAIL]
    if record.get('is_test'):
        lines = ['TEST — NE PAS PRÉPARER — AUCUN PAIEMENT RÉEL', 'Cette commande est un essai. Aucun acompte ni solde ne doit être encaissé.', ''] + lines
    text = '\n'.join(lines)
    sender = settings()[1]
    result = {'professional': {'from': sender, 'to': [PRO_EMAIL],
              'subject': 'Nouvelle commande EM — ' + record['id'],
              'text': text + '\n\nTéléphone client : ' + customer['phone'] + '\nE-mail client : ' + customer.get('email', '')}}
    if customer.get('email'):
        result['professional']['reply_to'] = customer['email']
        result['customer'] = {'from': sender, 'to': [customer['email']], 'reply_to': PRO_EMAIL,
                              'subject': 'Votre commande EM Poissonnerie — ' + record['id'], 'text': text}
    if record.get('is_test'):
        for message in result.values():
            message['subject'] = '[TEST — NE PAS PRÉPARER] ' + message['subject']
    return result


def send(payload, key):
    req = Request('https://api.resend.com/emails', data=json.dumps(payload).encode(), method='POST', headers={
        'Authorization': 'Bearer ' + settings()[0], 'Content-Type': 'application/json',
        'User-Agent': 'EM-Orders/1.0', 'Idempotency-Key': key})
    with urlopen(req, timeout=8) as response:
        data = json.load(response)
        if not isinstance(data, dict) or not data.get('id'):
            raise ValueError('Missing provider acknowledgment')
        return data['id']


def deliver(store, record, logger):
    """Each recipient commits separately; an error cannot undo the saved order."""
    if not configured():
        return False
    all_sent = True
    for role, payload in messages(record).items():
        try:
            with store.connect() as db:
                # Serialise competing retries, including multiple Gunicorn threads.
                if not store.url:
                    db.execute('BEGIN IMMEDIATE')
                sql = 'SELECT state,provider_id,first_attempt FROM em_order_mail WHERE order_id=? AND role=?'
                row = store.run(db, sql + (' FOR UPDATE' if store.url else ''), (record['id'], role)).fetchone()
                if row is None:
                    # Old orders are only mailed when explicitly retried; no blanket backfill.
                    all_sent = False
                    continue
                if row[0] == 'sent':
                    continue
                first = row[2] or time.time()
                # Never blindly retry an ambiguous send past the provider's dedupe window.
                if time.time() - first > 23 * 3600:
                    all_sent = False
                    continue
                try:
                    provider_id = send(payload, 'em-order/' + record['id'] + '/' + role)
                except Exception:
                    store.run(db, 'UPDATE em_order_mail SET state=?,first_attempt=? WHERE order_id=? AND role=?',
                              ('pending', first, record['id'], role))
                    all_sent = False
                    logger.warning('Order email pending: %s %s', record['id'], role)
                else:
                    store.run(db, 'UPDATE em_order_mail SET state=?,provider_id=?,first_attempt=? WHERE order_id=? AND role=?',
                              ('sent', provider_id, first, record['id'], role))
                    logger.info('Order email accepted: %s %s %s', record['id'], role, provider_id)
        except Exception:
            all_sent = False
            logger.warning('Order email state unavailable: %s %s', record['id'], role)
    return all_sent
