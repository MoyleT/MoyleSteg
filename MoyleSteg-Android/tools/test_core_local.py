#!/usr/bin/env python3
"""Compile and run real Kotlin core tests without Android SDK or Gradle.
Pass a local Bouncy Castle jar explicitly; no network downloads are performed.
"""
from pathlib import Path
import argparse,subprocess,os,shutil
p=argparse.ArgumentParser();p.add_argument('--bc-jar',required=True,type=Path);a=p.parse_args()
r=Path(__file__).resolve().parents[1];out=r/'core/build';out.mkdir(parents=True,exist_ok=True)
if not a.bc_jar.is_file():p.error('Bouncy Castle jar was not found')
sources=sorted((r/'core/src/main/kotlin').rglob('*.kt'))+sorted((r/'core/src/test/kotlin').rglob('*.kt'))
compiler=shutil.which('kotlinc') or shutil.which('kotlinc.bat')
if not compiler:p.error('Kotlin command-line compiler is required')
jar=out/'local-core-tests.jar'
runtime=r/'.android-build'
for folder in ['temp','home']:(runtime/folder).mkdir(parents=True,exist_ok=True)
os.environ.update(TEMP=str(runtime/'temp'),TMP=str(runtime/'temp'),TMPDIR=str(runtime/'temp'),
    JAVA_TOOL_OPTIONS=f'-Djava.io.tmpdir="{runtime / "temp"}" -Duser.home="{runtime / "home"}" -XX:-UsePerfData')
subprocess.run([compiler,*map(str,sources),'-cp',str(a.bc_jar),'-jvm-target','17','-include-runtime','-d',str(jar)],check=True)
subprocess.run(['java','-Xmx512m','-cp',str(jar)+os.pathsep+str(a.bc_jar),'com.moyle.steg.core.CoreRegression',str(r/'core/src/test/resources/interop'),str(out/'interop-output')],check=True)
for main,args in [('CaptureRegression',[str(out/'capture-regression')]),('FingerprintRegression',[])]+[
    ('PngMemoryRegression',[scenario]) for scenario in ['wide','normal','budgets','filters','encode']]:
    subprocess.run(['java','-Xmx128m','-cp',str(jar)+os.pathsep+str(a.bc_jar),'com.moyle.steg.core.'+main,*args],check=True)
subprocess.run(['java','-Xmx512m','-cp',str(jar)+os.pathsep+str(a.bc_jar),'com.moyle.steg.core.AutoExpandRegression',str(out/'autoexpand-output')],check=True)
subprocess.run(['java','-Xmx512m','-cp',str(jar)+os.pathsep+str(a.bc_jar),'com.moyle.steg.core.GifRegression',str(out/'gif-output'),str(r/'core/src/test/resources/gif')],check=True)
subprocess.run(['java','-Xmx128m','-cp',str(jar)+os.pathsep+str(a.bc_jar),'com.moyle.steg.core.SaesFilesRegression',str(out/'saes-files-output')],check=True)
subprocess.run(['java','-Xmx48m','-cp',str(jar)+os.pathsep+str(a.bc_jar),'com.moyle.steg.core.SaesFilesRegression',str(out/'saes-files-output'),'lowheap'],check=True)
for scenario in ['pixels','png-aes','payload-budget','payload-heap','gif-copy','authentication']:
    heap='64m' if scenario=='payload-heap' else '128m'
    subprocess.run(['java','-Xmx'+heap,'-cp',str(jar)+os.pathsep+str(a.bc_jar),'com.moyle.steg.core.ImageMemoryRegression',scenario],check=True)
for scenario in ['growth','copy','initial','normal','cancel']:
    subprocess.run(['java','-Xmx64m','-cp',str(jar)+os.pathsep+str(a.bc_jar),'com.moyle.steg.core.BoundedReadMemoryRegression',scenario],check=True)

subprocess.run(['java','-Xmx128m','-cp',str(jar)+os.pathsep+str(a.bc_jar),'com.moyle.steg.core.PixelCarrierRegression'],check=True)

bundle_cases = [
    ('BundleDiskRegression', '128m', [str(out/'bundle-disk-output')]),
    ('MultiFileBundleRegression', '128m', [
        str(out/'bundle-output'), str(r/'core/src/test/resources/bundle/python-bundle.zip')]),
    ('MultiFileBundleRegression', '32m', [str(out/'bundle-output'), 'lowheap']),
    ('BundleEnvelopeRegression', '256m', [
        str(r/'core/src/test/resources/bundle'), str(r/'core/src/test/resources/gif/cover.gif'),
        str(out/'bundle-envelope-output')]),
]
for main, heap, args in bundle_cases:
    subprocess.run(['java', '-Xmx'+heap, '-cp', str(jar)+os.pathsep+str(a.bc_jar),
                    'com.moyle.steg.core.'+main, *args], check=True)
