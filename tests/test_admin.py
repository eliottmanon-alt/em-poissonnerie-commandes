import base64
import importlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch


class AdminTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'EM_LOCAL_DB':self.temp.name+'/db.sqlite3','EM_SITE_API_KEY':'pc-only-key'})
        self.env.start()
        os.environ.pop('DATABASE_URL', None)
        os.environ.pop('RENDER', None)
        import app
        self.module = importlib.reload(app)
        self.client = self.module.app.test_client()
        self.client.get('/api/admin/session')
        self.token = self.module.admin_store.bootstrap()
        reply = self.client.post('/api/admin/setup',json={'token':self.token,'password':'test-admin-password-123'})
        self.assertEqual(reply.status_code,200)
        self.headers = {'X-CSRF-Token':reply.json['csrf']}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def put(self, state, revision, page='accueil'):
        return self.client.put('/api/admin/page/'+page,json={'revision':revision,'state':state,'panel':{'x':20,'y':30}},headers=self.headers)

    def test_protected_writes_csrf_and_auth_survives_restart(self):
        outsider=self.module.app.test_client()
        for path in ['/api/admin/publish','/api/admin/restore','/api/admin/media']:
            self.assertEqual(outsider.post(path,json={}).status_code,401)
        self.assertEqual(outsider.get('/api/admin/backup').status_code,401)
        self.assertEqual(self.client.put('/api/admin/page/accueil',json={}).status_code,403)
        self.assertEqual(self.client.post('/api/admin/publish',json={},headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/admin/setup',json={'token':self.token,'password':'new-password-123'}).status_code,403)
        # A new worker recovers its signing key before opening an existing cookie.
        cookie=self.client.get_cookie('em_admin_session').value
        self.module=importlib.reload(self.module)
        restarted=self.module.app.test_client()
        restarted.set_cookie('em_admin_session',cookie)
        self.assertTrue(restarted.get('/api/admin/session').json['authenticated'])
        self.assertEqual(restarted.get('/api/sync/ping').status_code,401)
        self.assertEqual(restarted.get('/api/sync/ping',headers={'X-EM-API-Key':'pc-only-key'}).status_code,200)

    def test_durable_images_pages_checkpoints_and_conflicts(self):
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jGWoAAAAASUVORK5CYII=')
        image=self.client.post('/api/admin/media',json={'data':base64.b64encode(png).decode()},headers=self.headers)
        self.assertEqual(image.status_code,200)
        state={'texts':{'title':'Nouveau <strong>texte</strong>'},'styles':{'bloc':{'width':'300px','height':'120px','transform':'translate(15px, 20px)','zIndex':'20'}},'images':{'photo':{'url':image.json['url'],'pos':'20% 30%','filter':'brightness(90%) contrast(110%) saturate(80%)'}},'hidden':{'other':True},'orders':{'parent':['b','a']},'groups':{'loyalty':{'width':100,'height':200}}}
        rev=0
        for page in ['accueil','commandes','commandes-informations','commandes-confirmation']:
            result=self.put(state,rev,page);self.assertEqual(result.status_code,200);rev=result.json['revision']
        self.assertEqual(self.put({},0).status_code,409)
        frozen=self.client.post('/api/admin/publish',json={'revision':rev},headers=self.headers)
        self.assertEqual(frozen.status_code,200);rev=frozen.json['revision']
        self.assertEqual(self.put({},rev).status_code,200);rev+=1
        restored=self.client.post('/api/admin/restore',json={'revision':rev,'id':frozen.json['published']},headers=self.headers)
        self.assertEqual(restored.status_code,200)
        public=self.module.app.test_client()
        doc=public.get('/api/appearance').json
        self.assertEqual(doc['pages']['accueil'],state)
        self.assertEqual(doc['panel'],{'x':20,'y':30})
        self.assertEqual(public.get(image.json['url']).data,png)
        self.assertFalse(public.get('/api/admin/session').json['authenticated'])
        backup=self.client.get('/api/admin/backup').json
        self.assertEqual(len(backup['versions']),2)
        self.assertEqual(len(backup['media']),1)
        self.module=importlib.reload(self.module)
        self.assertEqual(self.module.app.test_client().get('/api/appearance').json,doc)
        self.assertEqual(self.module.app.test_client().get(image.json['url']).data,png)

    def test_invalid_input_and_html_safety(self):
        self.assertEqual(self.put([],0).status_code,400)
        self.assertEqual(self.put({'styles':{'x':{'background':'url(https://evil)'}}},0).status_code,400)
        result=self.put({'texts':{'x':'<span onclick="alert(1)">Bonjour</span><script>alert(1)</script><a href="javascript:alert(1)">x</a>'}},0)
        self.assertEqual(result.status_code,200)
        text=result.json['pages']['accueil']['texts']['x']
        self.assertNotIn('onclick',text);self.assertNotIn('<script',text);self.assertNotIn('javascript:',text)
        self.assertEqual(self.client.post('/api/admin/media',json={'data':base64.b64encode(b'<svg onload="x"/>').decode()},headers=self.headers).status_code,400)
        self.assertEqual(self.put({'images':{'x':{'url':'/api/appearance/media/missing'}}},1).status_code,400)

    def test_html_contains_current_public_settings_before_body(self):
        import re
        value = '</script><img src=x onerror=alert(1)> & "photos"'
        def edit(db, doc):
            doc['pages']['accueil'] = {'texts': {'title': value}, 'images': {'photo': {'url': '/api/appearance/media/example'}}}
            doc['pages']['commandes'] = {'texts': {'other': 'other page'}}
        self.module.admin_store.change(0, edit)
        response = self.client.get('/')
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        match = re.search(r'<script id="emAppearanceBootstrap" type="application/json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(match)
        self.assertLess(match.start(), html.index('<body'))
        public = json.loads(match.group(1))
        self.assertEqual(public['pages']['accueil']['texts']['title'], value)
        self.assertEqual(set(public['pages']), {'accueil'})
        self.assertEqual(set(public), {'pages', 'revision', 'panel'})
        self.assertNotIn('</script>', match.group(1))
        self.assertNotIn(self.module.admin_store.auth()['secret'], html)
        response.close()
        for path, page in [('/commandes/', 'commandes'), ('/commandes/informations.html', 'commandes-informations'), ('/commandes/confirmation.html', 'commandes-confirmation')]:
            response = self.client.get(path)
            payload = re.search(r'<script id="emAppearanceBootstrap" type="application/json">(.*?)</script>', response.get_data(as_text=True), re.S)
            self.assertEqual(set(json.loads(payload.group(1))['pages']), {page})
            response.close()

    def test_first_html_request_initializes_storage_without_admin_login(self):
        # A new worker can serve current appearance before any session API request.
        self.module = importlib.reload(self.module)
        response = self.module.app.test_client().get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('emAppearanceBootstrap', response.get_data(as_text=True))
        response.close()

    def test_saved_photos_are_in_the_initial_html_without_javascript(self):
        from html.parser import HTMLParser
        class Tags(HTMLParser):
            def __init__(self):super().__init__();self.images={};self.backgrounds=[]
            def handle_starttag(self, tag, attrs):
                a=dict(attrs)
                if tag=='img':self.images[a.get('data-em-admin-id')]=a
                if 'banner-bg' in a.get('class','').split():self.backgrounds.append(a.get('style',''))
            handle_startendtag=handle_starttag
        url='/api/appearance/media/'+'a'*64
        # The renderer reads immutable URLs; this isolates it from image encoding.
        self.module.admin_store.change(0,lambda db,doc:doc['pages'].update({
            'accueil':{'images':{'accueil:img:x:1':{'url':url},'accueil:img:x:7':{'url':url,'pos':'20% 30%','filter':'brightness(90%) contrast(110%) saturate(80%)'}}},
            'commandes':{'images':{'commandes:img:banner-full:0':{'url':url}}}}))
        response=self.client.get('/');tags=Tags();tags.feed(response.get_data(as_text=True))
        self.assertEqual(tags.images['accueil:img:x:1']['src'],url+'/display.webp')
        self.assertEqual(tags.images['accueil:img:x:1']['data-em-original-src'],'assets/img/21_bateaux_de_peche_port.jpg')
        self.assertEqual(tags.images['accueil:img:x:7']['src'],url+'/display.webp')
        self.assertIn('object-position:20% 30%',tags.images['accueil:img:x:7']['style'])
        self.assertEqual(tags.images['accueil:img:x:1']['fetchpriority'],'high')
        self.assertEqual(tags.images['accueil:img:x:1']['data-em-server-image'],'true')
        response.close()
        response=self.client.get('/commandes/');tags=Tags();tags.feed(response.get_data(as_text=True))
        self.assertEqual(tags.images['commandes:img:banner-full:0']['src'],url+'/display.webp')
        self.assertIn(url+'/display.webp',tags.backgrounds[0]);response.close()

    def test_lightweight_media_preserves_original_alpha_and_survives_restart(self):
        import io
        from PIL import Image
        source=Image.new('RGBA',(600,400),(20,130,230,90));buffer=io.BytesIO();source.save(buffer,format='PNG');raw=buffer.getvalue()
        reply=self.client.post('/api/admin/media',json={'data':base64.b64encode(raw).decode()},headers=self.headers)
        url=reply.json['url'];display=url+'/display.webp'
        reply=self.client.get(display)
        self.assertEqual(reply.status_code,200)
        self.assertLess(len(reply.data),len(raw))
        image=Image.open(io.BytesIO(reply.data));self.assertEqual(image.convert('RGBA').getpixel((20,20))[3],90)
        self.assertEqual(self.client.get(url).data,raw)
        self.assertEqual(self.client.get(display,headers={'If-None-Match':reply.headers['ETag']}).status_code,304)
        self.module=importlib.reload(self.module)
        visitor=self.module.app.test_client()
        with patch('PIL.Image.open',side_effect=AssertionError('must reuse persistent derivative')):
            again=visitor.get(display)
        self.assertEqual(again.data,reply.data)
        self.assertEqual(visitor.get(url).data,raw)
        self.assertEqual(visitor.get('/api/appearance/media/missing/display.webp').status_code,404)


if __name__=='__main__':
    unittest.main()
