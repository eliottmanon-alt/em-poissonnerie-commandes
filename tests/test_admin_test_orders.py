import copy
import importlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import order_mail


class AdminTestOrderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'EM_LOCAL_DB':self.temp.name+'/test.sqlite3',
            'DATABASE_URL':'', 'RENDER':'', 'EM_SITE_API_KEY':'pc-test-key',
            'EM_DEPOSIT_ENABLED':'1', 'EM_ORDER_RESEND_KEY':'test-key',
            'EM_ORDER_FROM':'EM <test@example.com>'})
        env.start(); self.addCleanup(env.stop)
        self.mail = patch('order_mail.send', return_value='test-message').start()
        self.stripe = patch('payments.stripe.StripeClient').start()
        self.addCleanup(patch.stopall)
        import app
        self.module = importlib.reload(app)
        self.client = self.module.app.test_client()
        self.client.get('/api/admin/session')
        token = self.module.admin_store.bootstrap()
        result = self.client.post('/api/admin/setup',json={'token':token,'password':'test-admin-password-123'})
        self.assertEqual(result.status_code,200)
        self.headers = {'X-CSRF-Token':result.json['csrf'],'Idempotency-Key':'admin_test_order_0001'}
        day = datetime.now(ZoneInfo('Europe/Paris')).date()+timedelta(days=8)
        while day.weekday() not in (1,3,5): day += timedelta(days=1)
        self.payload = {'order':{'guests':2,'items':[{'name':'Crevettes Équateur','quantity':2}], 'specialRequests':[]},
            'customer':{'firstName':'Eliott','lastName':' TEST ','phone':'0600000000',
                'email':'Eliott.Manon@empoissonnerie.com','pickupDate':str(day),'pickupTime':'10:00','comment':'Vérification'}}

    def post(self, payload=None, headers=None):
        return self.client.post('/api/admin/test-order',json=self.payload if payload is None else payload,
            headers=self.headers if headers is None else headers)

    def test_admin_test_order_is_marked_mailed_synced_and_deduplicated(self):
        result = self.post()
        self.assertEqual(result.status_code,201,result.json)
        self.assertTrue(result.json['is_test'])
        self.assertTrue(result.json['email_sent'])
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.mail.call_count,2)
        record = self.client.get('/api/sync/orders',headers={'X-EM-API-Key':'pc-test-key'}).json['orders'][0]
        self.assertTrue(record['is_test'])
        self.assertEqual(record['source'],'admin-test-order')
        self.assertEqual(record['payment']['status'],'test_no_charge')
        self.assertEqual(record['payment']['balance_due_cents'],0)
        self.assertEqual(record['order']['total'],5.0)
        self.assertIn('NE PAS PRÉPARER',record['customer']['lastName'])
        for call in self.mail.call_args_list:
            message = call.args[0]
            self.assertIn('[TEST — NE PAS PRÉPARER]',message['subject'])
            self.assertIn('AUCUN PAIEMENT RÉEL',message['text'])
            self.assertEqual(message['to'],[order_mail.PRO_EMAIL])
        self.stripe.assert_not_called()
        self.assertEqual(len(self.module.store.orders()),1)
        changed=copy.deepcopy(self.payload);changed['customer']['comment']='modifié'
        self.assertEqual(self.post(changed).status_code,409)

    def test_anonymous_csrf_and_wrong_identity_never_bypass_payment(self):
        outsider=self.module.app.test_client()
        self.assertEqual(outsider.post('/api/admin/test-order',json=self.payload,headers=self.headers).status_code,401)
        self.assertEqual(self.post(headers={'Idempotency-Key':'admin_test_order_0001'}).status_code,403)
        self.assertEqual(self.post(headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)
        for field,value in [('lastName','TEST CLIENT'),('email','elsewhere@example.org')]:
            invalid=copy.deepcopy(self.payload);invalid['customer'][field]=value
            self.assertEqual(self.post(invalid).status_code,400)
        forged=copy.deepcopy(self.payload);forged.update(is_test=True)
        self.assertEqual(outsider.post('/api/orders',json=forged,headers=self.headers).status_code,402)
        self.assertEqual(self.module.store.orders(),[])
        self.mail.assert_not_called(); self.stripe.assert_not_called()

    def test_saved_admin_session_still_works_after_worker_restart(self):
        cookie = self.client.get_cookie('em_admin_session').value
        self.module=importlib.reload(self.module)
        self.client=self.module.app.test_client()
        self.client.set_cookie('em_admin_session',cookie)
        self.assertEqual(self.post().status_code,201)
        self.stripe.assert_not_called()
