$ErrorActionPreference = "Stop"

$path = Join-Path (Get-Location) "web\js\main.js"

if (-not (Test-Path $path)) {
    throw "web\js\main.js 파일을 찾을 수 없습니다. CloudeDX 프로젝트 루트에서 실행하세요."
}

$content = Get-Content -Path $path -Raw -Encoding UTF8

$initPattern = '(?ms)^\s*if \(state\.mode === "home"\) \{\r?\n\s*state\.status = "idle";\r?\n\s*renderList\(state\);\r?\n\s*armScrollLoader\(\);\r?\n\s*\} else \{\r?\n\s*load\(\);\r?\n\s*\}'
$initReplacement = @'
  // Reverdi 홈에서도 추천 매물을 즉시 불러온다.
  // 기존 코드는 pager가 화면 근처에 올 때까지 첫 API 요청을 미뤘다.
  load();
'@

$updated = [regex]::Replace($content, $initPattern, $initReplacement, 1)
if ($updated -eq $content) {
    throw "초기 로딩 블록을 찾지 못했습니다. main.js가 예상 버전과 다릅니다."
}
$content = $updated

$homePattern = '(?ms)(renderList\(state\);\r?\n\s*renderMetaLine\(state\);\r?\n\s*globalThis\.scrollTo\?\.\(\{ top: 0, behavior: "smooth" \}\);\r?\n\s*)armScrollLoader\(\);(\r?\n\})'
$homeReplacement = '$1// 로고로 홈에 돌아왔을 때도 즉시 추천 매물을 다시 불러온다.' + "`r`n  load();`$2"

$updated = [regex]::Replace($content, $homePattern, $homeReplacement, 1)
if ($updated -eq $content) {
    throw "홈 복귀 블록을 찾지 못했습니다. main.js가 예상 버전과 다릅니다."
}
$content = $updated

Set-Content -Path $path -Value $content -Encoding UTF8 -NoNewline

Write-Host "수정 완료: web\js\main.js"
Write-Host ""
Write-Host "이제 다음 명령을 실행하세요:"
Write-Host "  docker compose build backend"
Write-Host "  docker compose up -d --force-recreate backend"
