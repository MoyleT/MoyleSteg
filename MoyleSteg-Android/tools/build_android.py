#!/usr/bin/env python3
"""Bootstrap pinned official Gradle, generate its genuine wrapper, then build.

This is a development helper, not code shipped in the Android application.
No release signing keys are created or uploaded.
"""
from __future__ import annotations
import argparse, hashlib, os, shutil, subprocess, sys, urllib.request, zipfile
from pathlib import Path

VERSION='8.13'
SHA256='20f1b1176237254a6fc204d8434196fa11a4cfb387567519c61556e8710aed78'
ROOT=Path(__file__).resolve().parents[1]

def run(args: list[str],cwd: Path)->None:
    subprocess.run(args,cwd=cwd,check=True)

def main()->None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wrapper-only',action='store_true')
    parser.add_argument('--runtime-root',type=Path,default=ROOT/'.android-build',
        help='Temporary files, Gradle cache and Android user files stay here.')
    parser.add_argument('tasks',nargs='*')
    args=parser.parse_args()
    if not shutil.which('java') and not os.environ.get('JAVA_HOME'):
        raise RuntimeError('JDK 17 or later is required; set JAVA_HOME first.')
    runtime=args.runtime_root.resolve()
    for folder in ['temp','home','gradle-cache','android-user','appdata','localappdata']:
        (runtime/folder).mkdir(parents=True,exist_ok=True)
    # Only this helper and its children inherit the project-local environment.
    os.environ.update(TEMP=str(runtime/'temp'),TMP=str(runtime/'temp'),TMPDIR=str(runtime/'temp'),
        USERPROFILE=str(runtime/'home'),APPDATA=str(runtime/'appdata'),LOCALAPPDATA=str(runtime/'localappdata'),
        GRADLE_USER_HOME=str(runtime/'gradle-cache'),ANDROID_USER_HOME=str(runtime/'android-user'),
        ANDROID_EMULATOR_HOME=str(runtime/'android-user'),ANDROID_AVD_HOME=str(runtime/'android-user/avd'),
        PYTHONDONTWRITEBYTECODE='1',
        JAVA_TOOL_OPTIONS=f'-Djava.io.tmpdir="{runtime / "temp"}" -Duser.home="{runtime / "home"}" -XX:-UsePerfData')
    cache=ROOT/'.bootstrap';cache.mkdir(exist_ok=True)
    archive=cache/f'gradle-{VERSION}-bin.zip'
    if not archive.exists():
        temp=archive.with_suffix('.download')
        try:
            with urllib.request.urlopen(f'https://services.gradle.org/distributions/gradle-{VERSION}-bin.zip',timeout=45) as source, temp.open('wb') as target:
                shutil.copyfileobj(source,target)
            temp.rename(archive)
        finally:
            temp.unlink(missing_ok=True)
    with archive.open('rb') as stream:
        h=hashlib.sha256()
        for block in iter(lambda: stream.read(1024*1024),b''):
            h.update(block)
        digest=h.hexdigest()
    if digest!=SHA256:
        raise RuntimeError(f'Gradle SHA-256 mismatch. Remove {archive} and re-download from the official server.')
    home=cache/f'gradle-{VERSION}'
    if not home.exists():
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                dest=(cache/member.filename).resolve()
                if cache.resolve() not in dest.parents:
                    raise RuntimeError('Unsafe Gradle archive path.')
            z.extractall(cache)
    gradle=home/'bin'/('gradle.bat' if os.name=='nt' else 'gradle')
    if os.name!='nt':gradle.chmod(0o755)
    # Generate the official wrapper in a tiny isolated project, without configuring Android.
    wrapper=ROOT/'gradle/wrapper/gradle-wrapper.jar'
    if not wrapper.exists():
        bootstrap=cache/'wrapper-project';bootstrap.mkdir(exist_ok=True)
        (bootstrap/'settings.gradle.kts').write_text('rootProject.name = "wrapper-bootstrap"\n')
        run([str(gradle),'--no-daemon','wrapper','--gradle-version',VERSION,'--distribution-type','bin','--gradle-distribution-sha256-sum',SHA256],bootstrap)
        shutil.copytree(bootstrap/'gradle',ROOT/'gradle',dirs_exist_ok=True)
        for n in ['gradlew','gradlew.bat']:shutil.copy2(bootstrap/n,ROOT/n)
    if args.wrapper_only:
        print('Official Gradle wrapper generated. Open the project in Android Studio.');return
    if not os.environ.get('ANDROID_HOME') and not (ROOT/'local.properties').exists():
        raise RuntimeError('Android SDK missing. Explicitly set ANDROID_HOME or sdk.dir in local.properties; no user-profile SDK is selected automatically.')
    run([str(gradle),'--no-daemon',*(args.tasks or [':core:check',':app:testDebugUnitTest',':app:assembleDebug'])],ROOT)

if __name__=='__main__':
    try:main()
    except Exception as error:
        print(f'Build not completed: {error}',file=sys.stderr);sys.exit(2)
