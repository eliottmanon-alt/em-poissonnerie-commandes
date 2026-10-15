import base64,io,zipfile
from pathlib import Path
root=Path(__file__).resolve().parent
data=''.join(p.read_text() for p in sorted((root/'deploy_assets').glob('part-*.b64')))
with zipfile.ZipFile(io.BytesIO(base64.b64decode(data))) as z:
    for name in z.namelist():
        target=(root/name).resolve()
        if root not in target.parents or not name.startswith('site/assets/'):
            raise ValueError('Invalid asset path')
    z.extractall(root)
print('Original V10.6 images restored')
