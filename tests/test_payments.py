import copy
import hashlib
import hmac
import importlib
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import payments


class DepositTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {
            'EM_LOCAL_DB':self.temp.name+'/orders.sqlite3','EM_SITE_API_KEY':'test-sync-key',
            'EM_DEPOSIT_ENABLED':'1','EM_STRIPE_MODE':'test',
            'STRIPE_SECRET_KEY':'sk_test_fake_not_a_real_key','STRIPE_WEBHOOK_SECRET':'whsec_test_fixture',
            'EM_PUBLIC_URL':'https://commandes.empoissonnerie.com',
        })
        self.env.start(); self.addCleanup(self.env.stop)
        self.removed = {k:os.environ.pop(k,None) for k in ('RENDER','DATABASE_URL')}
        self.addCleanup(lambda: [os.environ.__setitem__(k,v) for k,v in self.removed.items() if v is not None])
        import app
        self.module = importlib.reload(app)
        self.client = self.module.app.test_client()
        day = datetime.now(ZoneInfo('Europe/Paris')).date() + timedelta(days=8)
        while day.weekday() not in (1,3,5): day += timedelta(days=1)
        self.payload = {'order':{'guests':4,'items':[{'name':'Crevettes Équateur','quantity':4,'price':.01}],
                                 'specialRequests':['Homard cuit ½'],'total':.01},
                        'customer':{'firstName':'TEST','lastName':'NE PAS PREPARER','phone':'0600000000',
                                    'email':'test@example.invalid','pickupDate':str(day),'pickupTime':'10:00'}}
        self.headers = {'Idempotency-Key':'deposit_test_request_0001'}
        self.gateway = MagicMock()
        self.mock_stripe = patch('payments.stripe.StripeClient',return_value=self.gateway)
        self.mock_stripe.start(); self.addCleanup(self.mock_stripe.stop)
        self.mail = patch('payments.order_mail.deliver',return_value=True).start()
        self.addCleanup(patch.stopall)
        self.session = {'id':'cs_test_12345678901234567890','url':'https://checkout.stripe.com/c/pay/test_session',
                        'currency':'eur','amount_total':200,'mode':'payment','livemode':False,
                        'status':'complete','payment_status':'paid','payment_intent':'pi_test_fixture'}
        def create(params, options):
            self.session['metadata'] = params['metadata']
            return dict(self.session)
        self.gateway.v1.checkout.sessions.create.side_effect=create
        self.gateway.v1.checkout.sessions.retrieve.side_effect=lambda _: dict(self.session)

    def checkout(self):
        return self.client.post('/api/payments/checkout',json=self.payload,headers=self.headers)

    def webhook(self, session=None, age=0, secret='whsec_test_fixture'):
        data=json.dumps({'id':'evt_test_fixture','type':'checkout.session.completed',
                         'data':{'object':session or self.session}}).encode()
        stamp=int(time.time())-age
        signature=hmac.new(secret.encode(),str(stamp).encode()+b'.'+data,hashlib.sha256).hexdigest()
        return self.client.post('/api/payments/webhook',data=data,content_type='application/json',
                                headers={'Stripe-Signature':f't={stamp},v1={signature}'})

    def test_disabled_and_incomplete_configuration_never_charge(self):
        with patch.dict(os.environ,{'EM_DEPOSIT_ENABLED':'0'}):
            self.assertFalse(self.client.get('/api/payments/config').json['enabled'])
            self.assertEqual(self.checkout().status_code,503)
        with patch.dict(os.environ,{'STRIPE_WEBHOOK_SECRET':''}):
            self.assertFalse(self.client.get('/api/payments/config').json['ready'])
            self.assertEqual(self.checkout().status_code,503)
            self.assertEqual(self.webhook().status_code,503)
        self.gateway.v1.checkout.sessions.create.assert_not_called()

    def test_server_price_rounding_and_unpaid_attempt_not_synced(self):
        response=self.checkout()
        self.assertEqual(response.status_code,200,response.json)
        params=self.gateway.v1.checkout.sessions.create.call_args.args[0]
        self.assertEqual(params['line_items'][0]['price_data']['unit_amount'],200)
        self.assertEqual(params['allowed_payment_method_types'],['card'])
        self.assertNotIn('payment_method_types',params)
        self.assertEqual(self.module.store.orders(),[])
        self.mail.assert_not_called()
        self.assertEqual(payments.amounts({'total':7.9}),(790,158,632))
        self.assertEqual(payments.amounts({'total':12.99}),(1299,260,1039))
        self.assertEqual(self.client.post('/api/orders',json=self.payload,headers=self.headers).status_code,402)

    def test_signed_paid_webhook_atomically_confirms_once_and_mails(self):
        self.checkout()
        response=self.webhook()
        self.assertEqual(response.status_code,200,response.json)
        record=self.module.store.orders()[0]
        self.assertEqual(record['order']['total'],10)
        self.assertEqual(record['payment']['deposit_paid_cents'],200)
        self.assertEqual(record['payment']['balance_due_cents'],800)
        self.assertEqual(record['status'],'new')
        self.mail.assert_called_once()
        self.assertEqual(self.webhook().status_code,200)
        self.assertEqual(len(self.module.store.orders()),1)
        # Mail delivery itself is idempotent using the existing durable outbox.
        status=self.client.get('/api/payments/status?session_id='+self.session['id']).json
        self.assertTrue(status['paid'])
        self.assertEqual(status['order_id'],record['id'])
        self.assertNotIn('customer',status)
        self.assertNotIn('email',json.dumps(status))
        outbox=self.module.store.pending_mail()
        self.assertEqual(len(outbox),1)

    def test_forged_stale_and_wrong_amount_events_rejected(self):
        self.checkout()
        self.assertEqual(self.webhook(secret='wrong').status_code,400)
        self.assertEqual(self.webhook(age=301).status_code,400)
        self.session['amount_total']=1
        self.assertEqual(self.webhook().status_code,400)
        self.session['amount_total']=200
        self.session['livemode']=True
        self.assertEqual(self.webhook().status_code,400)
        self.assertEqual(self.module.store.orders(),[])
        self.mail.assert_not_called()

    def test_unpaid_and_return_url_never_confirm(self):
        self.checkout(); self.session['payment_status']='unpaid'
        self.assertEqual(self.webhook().status_code,200)
        status=self.client.get('/api/payments/status?session_id='+self.session['id'])
        self.assertFalse(status.json['paid'])
        self.assertEqual(self.module.store.orders(),[])
        self.mail.assert_not_called()

    def test_provider_failure_keeps_order_unconfirmed_and_retry_key(self):
        self.gateway.v1.checkout.sessions.create.side_effect=TimeoutError()
        self.assertEqual(self.checkout().status_code,502)
        key=self.gateway.v1.checkout.sessions.create.call_args.kwargs['options']['idempotency_key']
        self.assertEqual(self.checkout().status_code,502)
        self.assertEqual(self.gateway.v1.checkout.sessions.create.call_args.kwargs['options']['idempotency_key'],key)
        self.assertEqual(self.module.store.orders(),[])

    def test_retry_and_changed_payload_and_expired_session(self):
        self.checkout()
        self.session['status']='open';self.session['payment_status']='unpaid'
        self.assertEqual(self.checkout().status_code,200)
        self.assertEqual(self.gateway.v1.checkout.sessions.create.call_count,1)
        changed=copy.deepcopy(self.payload);changed['order']['items'][0]['quantity']=5
        self.assertEqual(self.client.post('/api/payments/checkout',json=changed,headers=self.headers).status_code,409)
        self.session['status']='expired'
        response=self.checkout()
        self.assertEqual(response.status_code,409)
        self.assertEqual(response.json['error'],'payment_expired')

    def test_email_and_tiny_unpriced_requests(self):
        self.payload['customer']['email']=''
        self.assertEqual(self.checkout().status_code,400)
        self.payload['customer']['email']='test@example.invalid'
        self.payload['order']['items']=[]
        self.assertEqual(self.checkout().status_code,400)
        self.gateway.v1.checkout.sessions.create.assert_not_called()

    def test_parallel_fulfillment_and_real_sdk_object(self):
        self.checkout()
        from concurrent.futures import ThreadPoolExecutor
        import stripe
        session = stripe.StripeObject.construct_from(dict(self.session), 'test')
        with ThreadPoolExecutor(max_workers=4) as pool:
            records = list(pool.map(lambda _: self.module.payment_store.fulfill(session), range(4)))
        self.assertEqual(len({record['id'] for record in records}), 1)
        self.assertEqual(len(self.module.store.orders()), 1)

    def test_cross_origin_and_rate_limit(self):
        headers = dict(self.headers, Origin='https://unrelated.example')
        self.assertEqual(self.client.post('/api/payments/checkout',json=self.payload,headers=headers).status_code,403)
        with patch.dict(os.environ,{'EM_DEPOSIT_ENABLED':'0'}):
            for _ in range(60): self.checkout()
            self.assertEqual(self.checkout().status_code,429)
        self.gateway.v1.checkout.sessions.create.assert_not_called()

    def test_email_contains_deposit_balance_and_cash_card(self):
        self.checkout();self.webhook()
        import order_mail
        messages=order_mail.messages(self.module.store.orders()[0])
        for payload in messages.values():
            self.assertIn('Acompte de 20 % payé par carte : 2,00 €',payload['text'])
            self.assertIn('Solde à régler au retrait : 8,00 €',payload['text'])
            self.assertIn('carte bancaire ou en espèces',payload['text'])

if __name__=='__main__': unittest.main()
