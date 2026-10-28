# 실행: .\scripts\publish_github.ps1
# 코드만 비공개 프로젝트 저장소에 올립니다. 비밀 파일은 검사 후 제외합니다.
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
$remoteUrl = 'https://github.com/Emechani/ai-health-trainer.git'
$gitCommand = Get-Command git -ErrorAction SilentlyContinue
if ($gitCommand) {
    $gitExecutable = $gitCommand.Source
} else {
    # VS Code가 시작될 때 Git 경로를 받지 못한 경우 기존 설치본을 찾습니다.
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Git\cmd\git.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe'),
        (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe')
    )
    $gitExecutable = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $gitExecutable) { throw 'Git was not found. Install Git for Windows from git-scm.com, reopen the terminal and retry.' }
}
$env:PATH = (Split-Path -Parent $gitExecutable) + [IO.Path]::PathSeparator + $env:PATH

function Invoke-ProjectGit {
    & $gitExecutable -c "safe.directory=$projectRoot" @args
    if ($LASTEXITCODE -ne 0) { throw 'Git command failed. Review the preceding error.' }
}

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.git'))) {
    Invoke-ProjectGit init -b main
}
$branch = Invoke-ProjectGit symbolic-ref --short HEAD
if ($branch -ne 'main') { throw 'Expected the main branch; no branch was changed.' }
Invoke-ProjectGit add -- .gitignore .env.example .python-version README.md constraints.txt requirements.txt requirements-production.txt render.yaml manage.py config ai_engine main records users templates scripts docs
$files = @(Invoke-ProjectGit diff --cached --name-only --diff-filter=ACMR)
foreach ($file in $files) {
    if (($file -like '.env*' -and $file -ne '.env.example') -or
        $file -match '(^|/)(\.google_tokens|media|meal_images|venv|\.venv)/|(^|/)(credentials[^/]*\.json|token[^/]*\.json|\.django-dev-secret)$|\.(sqlite3|pyc)$') {
        throw "Private file detected; upload stopped: $file"
    }
    $content = (Invoke-ProjectGit show ":$file") -join "`n"
    if ($content -match 'AIza[0-9A-Za-z_-]{35}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----') {
        throw "Possible secret detected; upload stopped: $file"
    }
}
if ($files.Count -gt 0) {
    Invoke-ProjectGit -c user.name=Emechani -c user.email=Emechani@users.noreply.github.com commit -m 'Prepare Django application for Render deployment'
}
$remoteNames = @(Invoke-ProjectGit remote)
if ($remoteNames -contains 'origin') {
    $currentUrl = Invoke-ProjectGit remote get-url origin
    if ($currentUrl -ne $remoteUrl) { throw 'origin points to a different repository; it was not changed.' }
} else {
    Invoke-ProjectGit remote add origin $remoteUrl
}
Invoke-ProjectGit push -u origin main
Write-Output 'Source uploaded. Private DB, uploads and credentials were excluded.'
