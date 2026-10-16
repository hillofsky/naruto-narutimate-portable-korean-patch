import urllib.request,json
from pathlib import Path
url='httpLOCAL_PATH'
with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Codex-release-verification'}),timeout=30) as response:r=json.load(response)
assert r['draft'] is False
assets={a['name']:a for a in r['assets']}
p=assets['naruto-korean-v0.1.0.xdelta'];assert p['state']=='uploaded' and p['size']==724850977
assert p['digest']=='sha256:56c5d99e2d3c0ea13fb88931d1fd7503148ce0c8d6151154914532779041b306'
receipt={'repository':'httpLOCAL_PATH','release':r['html_url'],'patch':p['browser_download_url'],'patch_size':p['size'],'patch_digest':p['digest'],'roundtrip':'PASS','commit':'41b5c9e'}
Path(r'LOCAL_PATH').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('PUBLIC_RELEASE_VERIFIED',r['html_url'])
