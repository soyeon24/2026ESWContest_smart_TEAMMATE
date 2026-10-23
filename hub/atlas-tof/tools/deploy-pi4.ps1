# PC(Windows)에서 Pi 4(ATLAS)로 ToF 자세 서비스 묶음을 올리고 자가 시험 뒤 서비스·중계기를 띄운다.
#   .\deploy-pi4.ps1 -Ip 172.16.34.199 -Jump 172.20.10.10   # 핫스팟: Pi 4 는 Pi 5 뒤 랜선 → Pi 5 를 거쳐 간다
#   .\deploy-pi4.ps1 -Ip 172.16.34.146                      # Pi 4 에 직접 닿을 때
#   .\deploy-pi4.ps1 -Ip ... -NoStart                       # 올리기 + selftest 만
# 묶음: GitHub Release 의 zip 을 hub/atlas-tof/dist/ 에 풀면 dist\pi4 를 쓴다(docs/run-on-hotspot.md). 다른 곳이면 -Bundle.
# 필요한 것: Windows 기본 OpenSSH(ssh, scp)·tar. 보드 root 는 빈 비밀번호(물으면 Enter).
param(
    [Parameter(Mandatory = $true)][string]$Ip,
    [string]$Jump = "",
    [string]$Bundle = "",
    [string]$User = "root",
    [string]$Dest = "/mnt/rawdata/deskmate_tof",
    [switch]$NoStart
)
$ErrorActionPreference = "Stop"
if (-not $Bundle) {   # 묶음 폴더 안에서 실행하면 .\pi4, 레포 hub/atlas-tof/tools 에서 실행하면 hub/atlas-tof/dist/pi4
    $Bundle = Join-Path $PSScriptRoot "pi4"
    if (-not (Test-Path $Bundle)) { $Bundle = Join-Path $PSScriptRoot "..\dist\pi4" }
}
if (-not (Test-Path $Bundle)) { throw "묶음이 없다: $Bundle — GitHub Release 의 zip 을 hub/atlas-tof/dist/ 에 풀거나 -Bundle 로 지정" }
$Bundle = (Resolve-Path $Bundle).Path
if (-not (Test-Path (Join-Path $Bundle "deskmate_tofposture"))) { throw "묶음이 아니다: $Bundle (deskmate_tofposture 없음)" }
$Target = "$User@$Ip"
$SshOpts = @("-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new")
$JumpArg = ""
if ($Jump) { $SshOpts += @("-J", "$User@$Jump"); $JumpArg = "-J $User@$Jump" }

Write-Host "== 1. 보드 확인 ($Target)"
& ssh @SshOpts $Target "tr -d '\0' < /proc/device-tree/model; echo; grep PRETTY /etc/os-release; for p in `$(pidof deskmate_tofposture) `$(pidof uart_relay_board); do kill `$p; done; mkdir -p $Dest"
if ($LASTEXITCODE -ne 0) { throw "SSH 실패. 보드 IP·전원·네트워크 확인 (README '내일 순서' 0번: DHCP 라 IP 가 바뀌면 노션 「ATLAS 보드 SSH 접속」 3번 포트 스캔)" }

Write-Host "== 2. 복사 → $Dest"
# tar 를 ssh 로 흘려 보낸다(바이너리 안전: PowerShell 파이프가 아니라 cmd 파이프 사용). 실패하면 scp -r.
cmd /c "tar -cf - -C `"$Bundle`" . | ssh -o ConnectTimeout=8 $JumpArg $Target `"tar -xf - -C $Dest`""
if ($LASTEXITCODE -ne 0) {
    Write-Host "   tar 경로 실패 → scp -r 로 재시도"
    & scp @SshOpts -r "$Bundle\*" "${Target}:$Dest/"
    if ($LASTEXITCODE -ne 0) { & scp -O @SshOpts -r "$Bundle\*" "${Target}:$Dest/" }
    if ($LASTEXITCODE -ne 0) { throw "복사 실패" }
}
& ssh @SshOpts $Target "chmod +x $Dest/deskmate_tofposture $Dest/tofposture_selftest $Dest/uart_relay_board $Dest/ch340cfg $Dest/usbpower $Dest/*.sh 2>/dev/null; ls -l $Dest $Dest/models"

Write-Host "== 3. 보드 자가 시험 (모델·파서·융합)"
& ssh @SshOpts $Target "sh $Dest/selftest.sh"
if ($LASTEXITCODE -ne 0) { throw "selftest 실패 — 출력 확인" }

if (-not $NoStart) {
    Write-Host "== 4. 서비스 시작 + 중계기(ESP32 USB/UART → :9100, :8772/raw)"
    & ssh @SshOpts $Target "sh $Dest/start.sh && sh $Dest/relay.sh"
    Write-Host ""
    Write-Host "보드 상태:     ssh $JumpArg $Target sh $Dest/status.sh"
    Write-Host "PC 에서 보기:  hub\atlas-tof\pc\view.ps1 (docs/run-on-hotspot.md)"
}
