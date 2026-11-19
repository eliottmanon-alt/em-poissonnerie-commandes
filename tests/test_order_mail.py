import os
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(__file__))
from test_orders import OrdersTest
import order_mail

class OrderMailTest(OrdersTest):
    def setUp(self):
        super().setUp()
        self.env = patch.dict(os.environ, {'EM_ORDER_RESEND_KEY':'test-key','EM_ORDER_FROM':'EM <test@example.com>'})
        self.env.start()
        self.payload['customer']['email']='customer@example.org'

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def test_both_recipients_and_no_duplicates_after_restart(self):
        with patch('order_mail.send', return_value='provider-id') as send:
            r=self.client.post('/api/orders',json=self.payload,headers=self.key)
            self.assertEqual(r.status_code,201)
            self.assertTrue(r.json['email_sent'])
            self.assertEqual(send.call_count,2)
            self.assertEqual(send.call_args_list[0].args[0]['to'],[order_mail.PRO_EMAIL])
            self.assertEqual(send.call_args_list[1].args[0]['to'],['customer@example.org'])
            self.assertIn('5,00 €',send.call_args_list[1].args[0]['text'])
            self.client.post('/api/orders',json=self.payload,headers=self.key)
            self.client.get('/api/sync/orders',headers=self.auth)
            self.assertEqual(send.call_count,2)

    def test_partial_failure_keeps_order_and_retries_only_failed_recipient(self):
        with patch('order_mail.send', side_effect=['pro-id',TimeoutError()]):
            r=self.client.post('/api/orders',json=self.payload,headers=self.key)
        self.assertEqual(r.status_code,201)
        self.assertFalse(r.json['email_sent'])
        with patch('order_mail.send',return_value='client-id') as send:
            r=self.client.get('/api/sync/orders',headers=self.auth)
            self.assertEqual(len(r.json['orders']),1)
            self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[0]['to'],['customer@example.org'])
        self.assertEqual(self.module.store.pending_mail(),[])

    def test_no_client_address_still_notifies_professional(self):
        self.payload['customer']['email']=''
        with patch('order_mail.send',return_value='pro-id') as send:
            r=self.client.post('/api/orders',json=self.payload,headers=self.key)
            self.assertTrue(r.json['email_sent'])
            self.assertEqual(send.call_count,1)
