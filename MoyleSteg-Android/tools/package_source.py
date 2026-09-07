"""Package an explicit source whitelist, excluding caches, private outputs and signing keys."""
from pathlib import Path
import argparse, hashlib, json, zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.3.2-alpha'
TOP = {'.gitignore','README.md','THIRD_PARTY.md','Build-Android.ps1','build.ps1','build.sh',
       'build.gradle.kts','settings.gradle.kts','gradle.properties','gradlew','gradlew.bat'}
PREFIXES = ('app/src/', 'core/src/', 'tools/', '.github/', 'gradle/wrapper/')
EXTRA = {'app/build.gradle.kts', 'core/build.gradle.kts'}
# Documentation and evidence are deliberately enumerated. A newly added work
# plan or local diagnostic report must not become public just by its directory.
PUBLIC_DOCS = {
    'AUTO_EXPAND_0_1_2.md', 'DESIGN.md', 'DEVICE_ACCEPTANCE.md', 'GIF_PROTOCOL.md',
    'IMPLEMENTATION_PLAN.md', 'LARGE_FILES_0_3_0.md', 'JPEG_CARRIER_0_3_1.md', 'PROTOCOL.md',
    'RELIABILITY_0_1_1.md', 'SOURCES.md', 'DOWNLOAD_RESTORE_0_3_2.md',
}
PUBLIC_EVIDENCE = {
    'android-build-attempt.log', 'autoexpand_0_1_2_results.json', 'core-compile.log',
    'core-tests-final.log', 'kotlin-to-python-final.json', 'reference.json', 'summary.json',
    'TEST_REPORT.md', 'TEST_REPORT_0_1_1.md', 'TEST_REPORT_0_1_2.md',
    'TEST_REPORT_0_2_0.md', 'TEST_REPORT_0_3_0.md', 'TEST_REPORT_0_3_1.md', 'TEST_REPORT_0_3_2.md',
    '0.3.2-alpha/validation.json',
    '0.3.1-alpha/validation.json', '0.3.1-alpha/jpeg-python.json',
    *(f'0.3.0-alpha/{name}' for name in (
        'apk-signature.log', 'gradle.log', 'interop.json', 'large-1gib.log', 'validation.json')),
    *(f'kotlin-generated/{label}_{mode}.{suffix}'
      for label in ('empty', 'random', 'compressed', 'unicode')
      for mode in ('key', 'password') for suffix in ('png', 'saes')),
}
EXCLUDED_PARTS = {
    '.git', '.gradle', '.idea', '.bootstrap', '.android-build', 'build', 'release',
    '__pycache__', 'artifacts', 'superpowers',
}
EXCLUDED_SUFFIXES = {'.pyc', '.jks', '.keystore', '.p12', '.pfx', '.pem', '.key'}

def public_files():
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file() or path.is_symlink(): continue
        relative=path.relative_to(ROOT)
        if any(part.lower() in EXCLUDED_PARTS for part in relative.parts): continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES: continue
        if path.name.lower() in {'local.properties', '.env', 'key.properties', 'keystore.properties'}: continue
        name=relative.as_posix()
        if (name in TOP or name in EXTRA or name.startswith(PREFIXES)
                or name in {f'docs/{n}' for n in PUBLIC_DOCS}
                or name in {f'verification/{n}' for n in PUBLIC_EVIDENCE}):
            yield name,path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory',type=Path,default=ROOT/'release')
    args=parser.parse_args()
    files={name:path.read_bytes() for name,path in public_files()}
    release_manifest={
        'schema_version':1, 'project':'MoyleSteg-Android', 'version':VERSION,
        'kind':'public-source', 'file_count':len(files),
        'scope':'Source, public documentation and synthetic test evidence. This manifest excludes itself and SHA256SUMS.txt; SHA256SUMS.txt also covers this manifest.',
        'files':[{'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                 for name,data in sorted(files.items())],
    }
    manifest_bytes=(json.dumps(release_manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    (ROOT/'RELEASE_MANIFEST.json').write_bytes(manifest_bytes)
    files['RELEASE_MANIFEST.json']=manifest_bytes
    sums=''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name,data in sorted(files.items()))
    (ROOT/'SHA256SUMS.txt').write_text(sums,encoding='utf-8',newline='\n')
    files['SHA256SUMS.txt']=sums.encode('utf-8')
    args.output_directory.mkdir(parents=True,exist_ok=True)
    output=args.output_directory/f'MoyleSteg-Android-{VERSION}-Source.zip'
    prefix=f'MoyleSteg-Android-{VERSION}/'
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(files.items()):
            entry=zipfile.ZipInfo(prefix+name,date_time=(2026,1,1,0,0,0))
            entry.compress_type=zipfile.ZIP_DEFLATED
            entry.create_system=3
            mode=0o755 if name in {'gradlew','build.sh'} else 0o644
            entry.external_attr=(0o100000 | mode)<<16
            archive.writestr(entry,data,compresslevel=9)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(files)
        for line in sums.splitlines():
            digest,name=line.split('  ',1)
            assert hashlib.sha256(archive.read(prefix+name)).hexdigest()==digest,name
        for item in release_manifest['files']:
            data=archive.read(prefix+item['path'])
            assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256']
    print(f'Verified {release_manifest["file_count"]} public files plus two manifests: {output}')
    print('SHA256',hashlib.sha256(output.read_bytes()).hexdigest())

if __name__=='__main__':main()
