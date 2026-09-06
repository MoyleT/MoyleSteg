param(
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$AndroidSdk = $env:ANDROID_HOME,
    [string]$RuntimeRoot = (Join-Path $PSScriptRoot '.android-build'),
    [string[]]$Tasks = @(':core:check', ':app:testDebugUnitTest', ':app:assembleDebug'),
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath (Join-Path $JavaHome 'bin/java.exe'))) { throw 'Specify -JavaHome with a JDK 17 or later.' }
if (-not (Test-Path -LiteralPath $AndroidSdk)) { throw 'Specify -AndroidSdk with Android SDK 36 and Build Tools 35.0.0 installed.' }
$buildRoot = [IO.Path]::GetFullPath($RuntimeRoot)
foreach ($part in @('temp','home','gradle-cache','android-user','appdata','localappdata')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $buildRoot $part) | Out-Null
}
# Process-scoped settings: do not change Windows environment variables or global tools.
$settings = @{
    JAVA_HOME=$JavaHome; ANDROID_HOME=$AndroidSdk
    TEMP=(Join-Path $buildRoot 'temp'); TMP=(Join-Path $buildRoot 'temp'); TMPDIR=(Join-Path $buildRoot 'temp')
    USERPROFILE=(Join-Path $buildRoot 'home'); APPDATA=(Join-Path $buildRoot 'appdata'); LOCALAPPDATA=(Join-Path $buildRoot 'localappdata')
    GRADLE_USER_HOME=(Join-Path $buildRoot 'gradle-cache'); ANDROID_USER_HOME=(Join-Path $buildRoot 'android-user')
    ANDROID_EMULATOR_HOME=(Join-Path $buildRoot 'android-user'); ANDROID_AVD_HOME=(Join-Path $buildRoot 'android-user/avd')
    PYTHONDONTWRITEBYTECODE='1'
    JAVA_TOOL_OPTIONS=('-Djava.io.tmpdir="{0}" -Duser.home="{1}" -XX:-UsePerfData' -f (Join-Path $buildRoot 'temp'),(Join-Path $buildRoot 'home'))
    PATH=((Join-Path $JavaHome 'bin') + ';' + $env:PATH)
}
$previous = @{}
Push-Location $PSScriptRoot
try {
    foreach ($name in $settings.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $settings[$name], 'Process')
    }
    if (-not (Test-Path -LiteralPath './gradlew.bat')) {
        & $Python tools/build_android.py --wrapper-only --runtime-root $buildRoot
        if ($LASTEXITCODE -ne 0) { throw "Wrapper generation failed: $LASTEXITCODE" }
    }
    & ./gradlew.bat --no-daemon --console=plain --max-workers=4 '-Pkotlin.compiler.execution.strategy=in-process' @Tasks
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $LASTEXITCODE" }
} finally {
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
    Pop-Location
}
