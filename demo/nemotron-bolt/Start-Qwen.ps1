# Starts the local Qwen 3.6 model server that the Hermes chief-of-staff profile talks to.
# Leave this window open while using the demo. Ctrl+C stops it.
# Flags follow the chief-of-staff repo's demo\LATENCY.md (context 65536, one slot,
# reasoning budget 768, cache reuse), minus the optional vision and MTP draft files.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$root\bin\llama-server.exe" `
  -m "$root\models\Qwen3.6-35B-A3B-Q4_K_M.gguf" `
  --alias qwen3.6-35b-a3b `
  --host 127.0.0.1 --port 8080 `
  --ctx-size 65536 -np 1 -ngl 99 --jinja `
  --cache-reuse 256 --reasoning-budget 768 2>&1 | Tee-Object -FilePath "$root\qwen-server-last.log"
