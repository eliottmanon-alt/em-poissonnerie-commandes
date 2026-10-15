import copy
import importlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


class OrdersTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ['EM_LOCAL_DB'] = self.temp.name + '/orders.sqlite3'
        os.environ['EM_SITE_API_KEY'] = 'local-test-key'
        os.environ.pop('RENDER', None)
        os.environ.pop('DATABASE_URL', None)
        import app
        self.module = importlib.reload(app)
        self.client = self.module.app.test_client()
        date = datetime.now(ZoneInfo('Europe/Paris')).date() + timedelta(days=1)
        while date.weekday() not in (1, 3, 5):
            date += timedelta(days=1)
        self.payload = {'order': {'guests': 2, 'items': [{'name':'Crevettes Équateur','quantity':2,'price':0.01,'lineTotal':0.02}], 'specialRequests':['Homard cuit ½'], 'total':0.02},
                        'customer': {'firstName':'TEST', 'lastName':'NE PAS PREPARER', 'phone':'0600000000','email':'','pickupDate':str(date),'pickupTime':'10:00','comment':'Test technique'}}
        self.key = {'Idempotency-Key':'test_request_0000000001'}
        self.auth = {'X-EM-API-Key':'local-test-key'}

    def tearDown(self):
        self.temp.cleanup()

    def test_persistence_retry_and_status_history(self):
        response = self.client.post('/api/orders', json=self.payload, headers=self.key)
        self.assertEqual(response.status_code, 201)
        oid = response.json['order_id']
        # A retry creates no second order, including after an application restart.
        self.module = importlib.reload(self.module)
        self.client = self.module.app.test_client()
        again = self.client.post('/api/orders', json=self.payload, headers=self.key)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json['order_id'], oid)
        records = self.client.get('/api/sync/orders', headers=self.auth).json['orders']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['order']['total'], 5.0)
        self.assertEqual(records[0]['order']['specialRequests'], ['Homard cuit ½'])
        for state in ['preparing','ready']:
            self.assertEqual(self.client.post('/api/sync/orders/'+oid+'/status',json={'status':state},headers=self.auth).status_code,200)
        record = self.client.get('/api/sync/orders', headers=self.auth).json['orders'][0]
        self.assertEqual([x['status'] for x in record['status_history']], ['new','preparing','ready'])
        self.assertEqual(record['customer'], self.payload['customer'])
        changed=copy.deepcopy(self.payload);changed['customer']['firstName']='Different'
        self.assertEqual(self.client.post('/api/orders',json=changed,headers=self.key).status_code,409)

    def test_private_data_and_source_are_not_public(self):
        self.assertEqual(self.client.get('/api/sync/orders').status_code,401)
        self.assertEqual(self.client.get('/api/sync/orders',headers={'X-EM-API-Key':'bad'}).status_code,401)
        for path in ['/data/orders.sqlite3','/app.py','/.env','/../app.py','/requirements.txt','/storage.py']:
            self.assertEqual(self.client.get(path).status_code,404,path)
        for path in ['/','/commandes/','/commandes/index.html','/commandes/informations.html','/commandes/confirmation.html','/assets/admin/admin.js','/assets/checkout.js']:
            self.assertEqual(self.client.get(path).status_code,200,path)

    def test_validation_and_unconfigured_render(self):
        self.assertEqual(self.client.post('/api/orders',json=[]).status_code,400)
        broken=copy.deepcopy(self.payload);broken['order']['items'][0]['quantity']=-1
        self.assertEqual(self.client.post('/api/orders',json=broken,headers=self.key).status_code,400)
        broken=copy.deepcopy(self.payload);broken['customer']['pickupDate']='2020-01-01'
        self.assertEqual(self.client.post('/api/orders',json=broken,headers=self.key).status_code,400)
        self.module.store.disabled=True
        response=self.client.post('/api/orders',json=self.payload,headers=self.key)
        self.assertEqual(response.status_code,503)
        self.assertFalse(response.json['ok'])
        self.assertFalse(self.client.get('/api/health').json['orders_configured'])


if __name__ == '__main__':
    unittest.main()
