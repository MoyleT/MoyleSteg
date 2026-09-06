#!/usr/bin/env python3
"""Independent PNG scanline vectors, including every filter and rejected modes."""
from pathlib import Path
import struct,zlib
from PIL import Image
R=Path(__file__).resolve().parents[1]/'core/src/test/resources/interop'
def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
def png(w,h,kind,scan,interlace=0,extra=b''):
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,kind,0,0,interlace))+extra+chunk(b'IDAT',zlib.compress(scan))+chunk(b'IEND',b'')
w,h=17,11
raw=bytes((i*41+i//7)%256 for i in range(w*h*4));(R/'filters.rgba').write_bytes(raw)
def paeth(a,b,c):
 p=a+b-c;d=[abs(p-a),abs(p-b),abs(p-c)];return (a,b,c)[d.index(min(d))]
for f in range(5):
 rows=[]
 for y in range(h):
  row=raw[y*w*4:(y+1)*w*4];prev=raw[(y-1)*w*4:y*w*4] if y else bytes(w*4);enc=[]
  for i,v in enumerate(row):
   a=row[i-4] if i>=4 else 0;b=prev[i];c=prev[i-4] if i>=4 else 0
   pred=(0,a,b,(a+b)//2,paeth(a,b,c))[f];enc.append((v-pred)&255)
  rows.append(bytes([f])+bytes(enc))
 (R/f'filter{f}.png').write_bytes(png(w,h,6,b''.join(rows)))
Image.new('P',(17,11),0).save(R/'palette.png');Image.new('L',(17,11),123).save(R/'gray.png')
(R/'interlaced.png').write_bytes(png(17,11,6,bytes(11*(17*4+1)),interlace=1))
p=bytearray((R/'filter0.png').read_bytes());p[30]^=1;(R/'badcrc.png').write_bytes(p)
(R/'truncated.png').write_bytes((R/'filter0.png').read_bytes()[:-9])
(R/'apng.png').write_bytes(png(17,11,6,bytes(11*(17*4+1)),extra=chunk(b'acTL',struct.pack('>II',1,0))))
# RGB and truecolor tRNS compatibility.
rgb=bytes((i*29)%256 for i in range(9*7*3));scan=b''.join(b'\0'+rgb[y*27:(y+1)*27] for y in range(7))
(R/'rgb.png').write_bytes(png(9,7,2,scan))
(R/'rgb-trns.png').write_bytes(png(9,7,2,scan,extra=chunk(b'tRNS',struct.pack('>HHH',*rgb[:3]))))
for n in ['rgb','rgb-trns']:(R/(n+'.rgba')).write_bytes(Image.open(R/(n+'.png')).convert('RGBA').tobytes())
print('PNG fixture generation completed')
