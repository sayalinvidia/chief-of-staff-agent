# Switches the chief-of-staff demo to another local model.
#   powershell -ExecutionPolicy Bypass -File C:\Users\NVIDIA\llama.cpp\Switch-Model.ps1 bolt
#   ... Switch-Model.ps1 super
#   ... Switch-Model.ps1 qwen
# It stops the running model server, points the Hermes profile at the chosen model,
# and starts that model in its own minimised window. Then start a NEW chat in Hermes Desktop
# (restart the app if the old model name still shows).
param([Parameter(Mandatory = $true)][ValidateSet('qwen', 'super', 'bolt')][string]$Model)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$map = @{
    qwen  = @{ alias = 'qwen3.6-35b-a3b';       script = 'Start-Qwen.ps1' }
    super = @{ alias = 'nemotron-3.5-super-vl'; script = 'Start-Nemotron.ps1' }
    bolt  = @{ alias = 'nemotron-3.5-bolt';     script = 'Start-Bolt.ps1' }
}
$choice = $map[$Model]
$config = Join-Path $env:LOCALAPPDATA 'hermes-channel-build-nvidia-local-offer\profiles\chief-of-staff\config.yaml'

Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:$false
Start-Sleep -Seconds 3

# Change only the model name line under "model:"; everything else in the profile stays as it is.
$lines = [IO.File]::ReadAllLines($config)
$inModel = $false; $changed = $false
for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match '^model:\s*$') { $inModel = $true; continue }
    if ($inModel -and $lines[$i] -match '^\S') { $inModel = $false }
    if ($inModel -and $lines[$i] -match '^  default:') { $lines[$i] = "  default: $($choice.alias)"; $changed = $true }
}
if (-not $changed) { throw "Could not find the model name line in $config" }
[IO.File]::WriteAllLines($config, $lines, (New-Object Text.UTF8Encoding $false))

Start-Process powershell.exe -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $root $choice.script) -WindowStyle Minimized
Write-Host "Loading $($choice.alias) ..."
$ready = $false
foreach ($n in 1..120) {
    try { if ((Invoke-WebRequest http://127.0.0.1:8080/health -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { $ready = $true; break } } catch {}
    Start-Sleep -Seconds 3
}
if ($ready) { Write-Host "Ready: $($choice.alias) is running. Start a new chat in Hermes Desktop." }
else { Write-Host "The model server did not come up. Check the log in $root ($Model-server-last.log or nemotron-server-last.log)." }
