import json
import os
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import URLError
from flask import Flask
import contact


class ContactTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(contact.contact)
        self.client = self.app.test_client()
        self.env = patch.dict(os.environ, {'EM_CONTACT_RESEND_KEY': 'unit-test-key',
                         'EM_CONTACT_FROM': 'Website <site@example.com>', 'EM_CONTACT_TO': 'owner@example.com'})
        self.env.start()
        contact._attempts.clear()
        self.fields = dict(name='Test technique', email='visitor@example.org', phone='0600000000',
                           subject='Question <test>', message='Bonjour\nUne question.', website='')
        self.headers = {'Idempotency-Key':'contact-test-0000000001', 'Origin':'http://localhost'}

    def tearDown(self):
        self.env.stop()

    def post(self, fields=None, headers=None):
        return self.client.post('/api/contact', json=self.fields if fields is None else fields,
                                headers=self.headers if headers is None else headers)

    def test_actual_provider_acknowledgment_and_fixed_recipient(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"id":"provider-test-id"}'
        with patch('contact.urlopen', return_value=response) as send:
            result = self.post()
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json['message_id'], 'provider-test-id')
            request = send.call_args.args[0]
            body = json.loads(request.data)
            self.assertEqual(body['to'], ['owner@example.com'])
            self.assertEqual(body['reply_to'], self.fields['email'])
            self.assertEqual(request.get_header('Idempotency-key'), 'em-contact/contact-test-0000000001')
            self.assertNotIn('html', body)

    def test_never_claim_success_on_provider_failure(self):
        with patch('contact.urlopen', side_effect=URLError('test failure')):
            result = self.post()
        self.assertEqual(result.status_code, 502)
        self.assertFalse(result.json['ok'])
        with patch.dict(os.environ, {'EM_CONTACT_RESEND_KEY':''}):
            self.assertEqual(self.post().status_code,503)

    def test_validation_honeypot_origin_and_header_injection(self):
        with patch('contact.urlopen') as send:
            for data in [[], {}, {**self.fields,'email':'invalid'}, {**self.fields,'phone':'1'},
                         {**self.fields,'website':'spam'}, {**self.fields,'subject':'hello\r\nBcc: unwanted@example.com'},
                         {**self.fields,'message':'a'*6001}]:
                self.assertEqual(self.post(data).status_code,400)
            self.assertEqual(self.post(headers={**self.headers,'Origin':'https://foreign.example'}).status_code,403)
            self.assertEqual(self.post(headers={}).status_code,400)
            send.assert_not_called()

    def test_rate_limits_are_bounded_and_do_not_send(self):
        with patch('contact.send_contact',return_value='test') as send:
            for _ in range(5):
                self.assertEqual(self.post().status_code,200)
            self.assertEqual(self.post().status_code,429)
            self.assertEqual(send.call_count,5)
