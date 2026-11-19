# Starts the local NVIDIA Nemotron 3.5 Bolt (74B-A9B, NVIDIA 24GB build) model server for the
# Hermes chief-of-staff profile. Uses about 25 GB of GPU memory.
# Uses the same address as the other Start-*.ps1 scripts, so run only one at a time.
# Leave this window open while using the demo. Ctrl+C stops it.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$root\bin\llama-server.exe" `
  -m "$root\models\NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB.gguf" `
  --alias nemotron-3.5-bolt `
  --host 127.0.0.1 --port 8080 `
  --ctx-size 65536 -np 1 -ngl 99 --jinja `
  --cache-reuse 256 --reasoning-budget 768 `
  --spec-type draft-lilicorr `
  --spec-draft-model "$root\models\NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-LiLiCorr.gguf" `
  --spec-draft-ngl 99 --spec-draft-n-max 7 2>&1 | Tee-Object -FilePath "$root\bolt-server-last.log"
