param(
  [string]$Project = "mykhaya-e2e-$([guid]::NewGuid().ToString('N').Substring(0,8))",
  [string]$TestFile = "apps/web/e2e/social-registration-candidate.spec.ts",
  [string]$BrowserProject = "",
  [int]$WebPort = 18090,
  [int]$MailpitPort = 18082
)
$ErrorActionPreference = "Stop"
$webPort = $WebPort
$mailpitPort = $MailpitPort
$env:MYKHAYA_E2E_WEB_PORT = "$webPort"
$env:MYKHAYA_E2E_MAILPIT_PORT = "$mailpitPort"
if ($Project -notmatch '^[a-z0-9][a-z0-9_-]*$' -or $Project -eq 'mykhaya') { throw "Unsafe E2E Compose project name" }
if (docker ps -a --filter "label=com.docker.compose.project=$Project" --format '{{.ID}}' | Where-Object { $_ }) { throw "E2E Compose project already exists" }
foreach ($port in 18080, 18081, $mailpitPort, $webPort) {
  if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw "E2E port $port is already in use" }
}
$secretDir = Join-Path ([IO.Path]::GetTempPath()) "mykhaya-e2e-$Project"
New-Item -ItemType Directory -Force $secretDir | Out-Null
$env:MYKHAYA_E2E_SECRET_DIR = $secretDir
docker run --rm -v "${secretDir}:/out" alpine:3.22 sh -c 'apk add --no-cache openssl >/dev/null && openssl ecparam -name prime256v1 -genkey -noout -out /out/apple-sign-in.p8 && chmod 444 /out/apple-sign-in.p8'
try {
  docker compose -p $Project -f compose.e2e.yml config --quiet
  if ($LASTEXITCODE -ne 0) { throw "E2E Compose configuration validation failed" }
  docker compose -p $Project -f compose.e2e.yml build
  if ($LASTEXITCODE -ne 0) {
    docker compose -p $Project -f compose.e2e.yml logs --no-color migrate seed scheduler worker api web
    throw "E2E Compose image build failed"
  }
  docker compose -p $Project -f compose.e2e.yml up -d
  if ($LASTEXITCODE -ne 0) {
    docker compose -p $Project -f compose.e2e.yml logs --no-color migrate seed scheduler worker api web
    throw "E2E Compose startup failed"
  }
  $env:PLAYWRIGHT_BASE_URL = "http://127.0.0.1:$webPort"
  $playwright = Join-Path (Get-Location) "apps/web/node_modules/.bin/playwright.cmd"
  if (-not (Test-Path -LiteralPath $playwright)) { throw "Workspace Playwright executable is missing: $playwright" }
  & $playwright install chromium webkit
  if ($LASTEXITCODE -ne 0) { throw "Playwright browser installation failed" }
  $workspaceTestFile = $TestFile -replace '^apps/web/', ''
  $projectArgs = @()
  if ($BrowserProject) { $projectArgs = @("--project", $BrowserProject) }
  $playwrightConfig = Join-Path (Get-Location) "apps/web/playwright.config.ts"
  & $playwright test $workspaceTestFile --config $playwrightConfig @projectArgs
  if ($LASTEXITCODE -ne 0) {
    docker compose -p $Project -f compose.e2e.yml logs --no-color api web oauth-provider scheduler worker mailpit
    throw "Playwright E2E acceptance failed"
  }
  docker compose -p $Project -f compose.e2e.yml exec -T api python /opt/e2e/verify_google.py
  if ($LASTEXITCODE -ne 0) { throw "Authoritative Google E2E database verification failed" }
} finally {
  docker compose -p $Project -f compose.e2e.yml down -v --remove-orphans
  Remove-Item -LiteralPath $secretDir -Recurse -Force -ErrorAction SilentlyContinue
}
