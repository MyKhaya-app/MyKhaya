$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '..\..\docs\security\asvs-5.0.0.csv'
$target = Join-Path $PSScriptRoot '..\..\docs\security\asvs-control-matrix.md'
$implemented = @{
  'V1.2.4' = @('SQLAlchemy parameterised expressions and no raw user-built SQL', 'apps/api/mykhaya/**/*.py', 'Implemented; verification pending')
  'V2.2.1' = @('Strict Pydantic request models with explicit lengths and enums', 'apps/api/mykhaya/schemas.py; test_journey.py', 'Implemented; automated evidence')
  'V2.2.2' = @('All security validation is repeated server-side', 'apps/api/mykhaya/schemas.py', 'Implemented; automated evidence')
  'V2.3.3' = @('Related writes and outbox events share database transactions', 'routers/*.py; audit.py', 'Implemented; automated evidence')
  'V2.4.1' = @('Redis-backed bounded authentication and registration rate limits', 'rate_limit.py', 'Implemented; operational evidence pending')
  'V3.3.2' = @('SameSite=Lax cookies and double-submit CSRF', 'security.py; test_journey.py', 'Implemented; automated evidence')
  'V3.3.4' = @('Opaque session token is HttpOnly', 'security.py; test_journey.py', 'Implemented; automated evidence')
  'V3.4.1' = @('One-year includeSubDomains HSTS at production Caddy origin', 'Caddyfile.production', 'Implemented; deployment evidence pending')
  'V3.4.2' = @('Fixed origin allow-list in FastAPI and unsafe-request middleware', 'main.py; test_journey.py', 'Implemented; automated evidence')
  'V4.2.1' = @('Central current-membership Home authorisation', 'dependencies.py; test_journey.py', 'Implemented; automated evidence')
  'V4.2.2' = @('Home identifiers are always paired with current membership checks', 'routers/groups.py; test_journey.py', 'Implemented; automated evidence')
  'V4.3.1' = @('Owner/administrator function checks are server-side', 'routers/groups.py; routers/invitations.py', 'Implemented; automated evidence')
  'V6.2.1' = @('Argon2 password hashing through pwdlib recommended profile', 'security.py', 'Implemented; verification pending')
  'V7.2.1' = @('Opaque high-entropy session identifiers stored as keyed hashes', 'security.py; models.py', 'Implemented; automated evidence')
  'V7.4.1' = @('Session revocation and password-reset global revocation', 'routers/auth.py; test_journey.py', 'Implemented; automated evidence')
  'V7.4.2' = @('Explicit session rotation endpoint revokes predecessor', 'routers/auth.py; test_journey.py', 'Implemented; automated evidence')
  'V8.2.1' = @('CSRF token and allowed Origin required on cookie-authenticated unsafe methods', 'security.py; test_journey.py', 'Implemented; automated evidence')
  'V9.1.1' = @('TLS termination and HSTS are production defaults', 'Caddyfile.production; compose.production.yml', 'Implemented; deployment evidence pending')
  'V10.2.1' = @('Reusable action and invitation tokens stored only as keyed hashes', 'security.py; models.py', 'Implemented; automated evidence')
  'V11.1.1' = @('Structured audit events for auth, membership and invitation changes', 'audit.py; routers/*.py', 'Implemented; verification pending')
  'V13.1.1' = @('Minimal API response models separate from persistence models', 'schemas.py; routers/*.py', 'Implemented; automated evidence')
  'V13.2.1' = @('Strict request schemas reject unknown properties', 'schemas.py; test_journey.py', 'Implemented; automated evidence')
}
$rows = Import-Csv -LiteralPath $source | Where-Object { [int]$_.L -le 2 }
$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add('# ASVS 5.0.0 Level 2 Control Matrix')
$lines.Add('')
$lines.Add('Target: **OWASP ASVS 5.0.0 Level 2**. Generated from the official stable English CSV pinned in this repository. The source is OWASP ASVS, licensed CC BY-SA 4.0. Requirement text remains in the attributed CSV; this matrix uses stable identifiers and section names.')
$lines.Add('')
$lines.Add('This is a coverage inventory, not a compliance claim. “Implemented” records current code evidence only. Controls marked “Not assessed” require design review, test evidence, an applicability decision, and where appropriate independent verification before hosted release.')
$lines.Add('')
$lines.Add('| Requirement | Level | Area | Implementation | Evidence | Status |')
$lines.Add('|---|---:|---|---|---|---|')
foreach ($row in $rows) {
  $id = $row.req_id
  $area = ($row.section_name -replace '\|','\\|')
  if ($implemented.ContainsKey($id)) {
    $entry = $implemented[$id]
    $lines.Add("| v5.0.0-$id | $($row.L) | $area | $($entry[0]) | $($entry[1]) | $($entry[2]) |")
  } else {
    $lines.Add("| v5.0.0-$id | $($row.L) | $area | Review required | TBD | Not assessed |")
  }
}
$lines.Add('')
$lines.Add("Inventory count: $($rows.Count) Level 1/2 requirements. Regenerate with ``powershell -File infrastructure/scripts/generate-asvs-matrix.ps1``.")
[System.IO.File]::WriteAllLines($target, $lines, [System.Text.UTF8Encoding]::new($false))
