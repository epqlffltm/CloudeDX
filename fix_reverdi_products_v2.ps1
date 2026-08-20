$ErrorActionPreference = "Stop"

$path = Join-Path (Get-Location) "web\js\main.js"
$backup = "$path.bak_reverdi"

if (-not (Test-Path $path)) {
    throw "web\js\main.js 파일을 찾을 수 없습니다. CloudeDX 프로젝트 루트에서 실행하세요."
}

$content = Get-Content -Path $path -Raw -Encoding UTF8

# 백업
Copy-Item -Path $path -Destination $backup -Force

# 1) init() 안의 '홈에서는 첫 로드를 지연'시키는 구간을,
#    새 Reverdi 홈에서는 즉시 load()하도록 교체한다.
$initStart = $content.IndexOf("async function init()")
if ($initStart -lt 0) {
    throw "async function init()을 찾지 못했습니다."
}

$tryPos = $content.IndexOf("  try {", $initStart)
if ($tryPos -lt 0) {
    throw "init() 안의 try 블록을 찾지 못했습니다."
}

# init() 안에서 load() 직전 제어 블록을 넓게 찾는다.
$segment = $content.Substring($initStart, $tryPos - $initStart)

$homeIfPos = $segment.IndexOf('if (state.mode === "home")')
if ($homeIfPos -ge 0) {
    $homeIfAbs = $initStart + $homeIfPos

    # if 블록의 중괄호를 직접 세서 끝 위치를 찾는다.
    $braceStart = $content.IndexOf("{", $homeIfAbs)
    if ($braceStart -lt 0) { throw "홈 모드 if 블록 시작을 찾지 못했습니다." }

    $depth = 0
    $i = $braceStart
    $ifEnd = -1

    while ($i -lt $tryPos) {
        $ch = $content[$i]
        if ($ch -eq "{") { $depth++ }
        elseif ($ch -eq "}") {
            $depth--
            if ($depth -eq 0) {
                $ifEnd = $i + 1

                # 바로 뒤에 else가 있으면 else 블록까지 포함
                $tail = $content.Substring($ifEnd, [Math]::Min(40, $content.Length - $ifEnd))
                if ($tail -match '^\s*else\s*\{') {
                    $elseOpen = $content.IndexOf("{", $ifEnd)
                    $depth2 = 0
                    $j = $elseOpen
                    while ($j -lt $tryPos) {
                        $ch2 = $content[$j]
                        if ($ch2 -eq "{") { $depth2++ }
                        elseif ($ch2 -eq "}") {
                            $depth2--
                            if ($depth2 -eq 0) {
                                $ifEnd = $j + 1
                                break
                            }
                        }
                        $j++
                    }
                }
                break
            }
        }
        $i++
    }

    if ($ifEnd -lt 0) {
        throw "홈 모드 초기 로딩 블록의 끝을 찾지 못했습니다."
    }

    $replacement = @'
  // Reverdi 홈에서도 추천 매물을 즉시 불러온다.
  load();
'@

    $content = $content.Substring(0, $homeIfAbs) + $replacement + $content.Substring($ifEnd)
}
else {
    # 이미 수정된 경우
    if ($segment -notmatch 'Reverdi 홈에서도 추천 매물을 즉시 불러온다') {
        throw "init() 구조가 예상과 달라 자동 수정할 수 없습니다."
    }
}

# 2) goHome()에서 홈 복귀 후에도 즉시 다시 로드하도록 한다.
$goStart = $content.IndexOf("function goHome()")
if ($goStart -lt 0) {
    throw "function goHome()을 찾지 못했습니다."
}

$nextSection = $content.IndexOf("/* ---------------------------------------------------------------------------", $goStart)
if ($nextSection -lt 0) { $nextSection = $content.Length }

$goSegment = $content.Substring($goStart, $nextSection - $goStart)

if ($goSegment -match 'armScrollLoader\(\);') {
    $goSegment = [regex]::Replace(
        $goSegment,
        'armScrollLoader\(\);',
        '// Reverdi 홈 복귀 시에도 추천 매물을 즉시 다시 불러온다.' + "`r`n  load();",
        1
    )
    $content = $content.Substring(0, $goStart) + $goSegment + $content.Substring($nextSection)
}

Set-Content -Path $path -Value $content -Encoding UTF8 -NoNewline

Write-Host ""
Write-Host "수정 완료: web\js\main.js"
Write-Host "백업 생성: web\js\main.js.bak_reverdi"
Write-Host ""
Write-Host "확인:"
Write-Host '  Select-String -Path .\web\js\main.js -Pattern "Reverdi 홈|load\(\)"'
Write-Host ""
Write-Host "재빌드:"
Write-Host "  docker compose build backend"
Write-Host "  docker compose up -d --force-recreate backend"
