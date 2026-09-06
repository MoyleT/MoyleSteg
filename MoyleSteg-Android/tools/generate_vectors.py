#!/usr/bin/env python3
"""Synthetic only. Generate desktop v1.4.1 containers and known-value fixtures."""
from pathlib import Path
import sys, importlib.util, hashlib, json, struct, zlib, random
from PIL import Image
ROOT = Path(__file__).resolve().parents[1]
ref = ROOT / 'tools/reference/desktop_1_4_1.py'
spec = importlib.util.spec_from_file_location('moyle_reference',ref)
r=importlib.util.module_from_spec(spec);sys.modules[spec.name]=r;spec.loader.exec_module(r)
out=ROOT/'core/src/test/resources/interop';out.mkdir(parents=True,exist_ok=True)
key=hashlib.sha256(b'MOYLE PUBLIC SYNTHETIC FIXTURE KEY - NOT FOR SECRETS').digest()
(out/'key.stegkey').write_bytes((r.KEY_FILE_HEADER+'\n'+__import__('base64').urlsafe_b64encode(key).decode()+'\n').encode())
password='跨端口令-test-α-🔐'
(out/'password.txt').write_text(password,encoding='utf-8')
w,h=384,256
rgba=bytes(c for y in range(h) for x in range(w) for c in ((x*13+y*7)%256,(x+y*3)%256,(x*29+y*5)%256,(x+y)%256))
Image.frombytes('RGBA',(w,h),rgba).save(out/'cover.png')
(out/'cover.rgba').write_bytes(rgba)
records=[]
rng=random.Random(7141)
for label,data,name in [('empty',b'','empty.bin'),('random',rng.randbytes(3073),'样本_δ.bin'),('compressed',b'protocol\x00'*1500,'notes.txt'),('unicode','离线隐写与跨端恢复。\n'.encode()*20,'测试_🙂.txt')]:
 (out/(label+'.bin')).write_bytes(data)
 # Generate a temporary filename matching the intended payload basename.
 tmp=out/'inputs';tmp.mkdir(exist_ok=True);src=tmp/name;src.write_bytes(data)
 for mode,cred in [('key',r.Credential.from_key_bytes(key)),('password',r.Credential.from_password(password))]:
  base=label+'_'+mode
  r.encrypt_file(src,out/(base+'.saes'),credential=cred,force=True)
  r.hide_file(out/'cover.png',src,out/(base+'.png'),credential=cred,force=True)
  records.append('\t'.join([base,label+'.bin',name,mode]))
 src.unlink()
(out/'inputs').rmdir()
(out/'cases.tsv').write_text('\n'.join(records)+'\n',encoding='utf-8')
salt=bytes(range(16));nonce=bytes(range(12));props={}
for mode,cred in [('key',r.Credential.from_key_bytes(key)),('password',r.Credential.from_password(password))]:
 head=r._build_header(cred.mode,salt,nonce,128)
 enc,layout=r._derive_keys(cred,head)
 props[mode+'.header']=r._serialize_header(head).hex();props[mode+'.enc']=enc.hex();props[mode+'.layout']=layout.hex()
for total,needed in [(256,256),(8193,617),(4096,4096),(10000,1),(11,0),(4500,4499)]:
 poses=list(r.iter_scattered_positions(total_positions=total,needed=needed,layout_key=key))
 props[f'positions.{total}.{needed}']=hashlib.sha256(b''.join(struct.pack('>I',x) for x in poses)).hexdigest()
(out/'known.tsv').write_text(''.join(f'{k}\t{v}\n' for k,v in props.items()),encoding='utf-8')
(ROOT/'verification/reference.json').write_text(json.dumps({'reference_sha256':hashlib.sha256(ref.read_bytes()).hexdigest(),'python':sys.version,'synthetic_cases':len(records),'note':'PUBLIC test key; NEVER use it for private data'},indent=2),encoding='utf-8')
print('Generated',len(records),'synthetic cross-language cases')
