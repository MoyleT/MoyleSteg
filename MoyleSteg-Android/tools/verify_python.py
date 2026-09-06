#!/usr/bin/env python3
"""Verify Kotlin-produced containers using the unmodified desktop 1.4.1 core."""
import sys,importlib.util,json,hashlib
from pathlib import Path
from PIL import Image
root=Path(__file__).resolve().parents[1]
fixtures=root/'core/src/test/resources/interop'
outputs=Path(sys.argv[1]) if len(sys.argv)>1 else root/'core/build/interop-output'
spec=importlib.util.spec_from_file_location('moyle_reference',root/'tools/reference/desktop_1_4_1.py')
r=importlib.util.module_from_spec(spec);sys.modules[spec.name]=r;spec.loader.exec_module(r)
results=[]
for line in (fixtures/'cases.tsv').read_text(encoding='utf-8').splitlines():
 base,source,name,mode=line.split('\t');expected=(fixtures/source).read_bytes()
 c=r.Credential.from_key_file(fixtures/'key.stegkey') if mode=='key' else r.Credential.from_password((fixtures/'password.txt').read_text(encoding='utf-8'))
 for extension in ['png','saes']:
  file=outputs/f'{base}.{extension}'
  decoded=r.decode_image(file,credential=c) if extension=='png' else r.decode_encrypted_file(file,credential=c)
  assert decoded.filename==name and decoded.data==expected
  if extension=='png':
   before=Image.open(fixtures/'cover.png').convert('RGBA');after=Image.open(file).convert('RGBA')
   assert before.size==after.size
   b=before.tobytes();a=after.tobytes()
   assert a[3::4]==b[3::4]
   assert all(abs(x-y)<=1 for x,y in zip(a,b))
  results.append({'file':file.name,'mode':mode,'bytes':len(expected),'restored_sha256':hashlib.sha256(decoded.data).hexdigest(),'pass':True})
print(json.dumps({'kotlin_to_python_cases':len(results),'all_passed':True,'results':results},ensure_ascii=False,indent=2))
