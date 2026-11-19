---
name: nemotron-bolt-demo-setup
description: Set up, verify and run the Chief of Staff demo on a local NVIDIA Nemotron 3.5 Bolt model served by llama.cpp, exactly as on the reference RTX Spark machine.
license: MIT
metadata:
  version: 0.1.0
  author: NVIDIA, Hermes Agent
  platforms: [windows]
  created_by: agent
  hermes:
    tags: [Setup, Nemotron, llama.cpp, Chief-of-Staff, Demo]
---

# Nemotron 3.5 Bolt demo setup

## Purpose

Use this skill when asked to install, reproduce, verify or repair the Chief of Staff demo on a
machine with an NVIDIA GPU, running **Nemotron 3.5 Bolt 74B-A9B (24GB build) + LiLiCorr draft
model** under **llama.cpp b12445**, driven by **Hermes Desktop**. It turns the repository's
`NEMOTRON_BOLT_SETUP.md` into a checklist with a verifier, so you can prove each step rather
than assume it.

Reference result (RTX Spark laptop, Hermes Desktop, three demo prompts, mains power is better):
142–172 s total, 9–11 model turns, 6–9 tool calls, 0 failed commands, tracker update correct.

## Operating rules

- Work in the order below. Run `scripts/check_setup.py` after every phase; do not go on while
  it reports a `FAIL` for that phase.
- Never copy, print or commit `google_token.json`, `google_client_secret.json` or `auth.json`.
- Downloads are large (22 GB + 1 GB). Verify SHA-256 before using a file; never "fix" a checksum
  mismatch by skipping it.
- Keep one model server only (port 8080, one slot). Stop any other `llama-server` first.
- Measure the demo in **Hermes Desktop**, not through the CLI `-z` path, and on mains power.
- Report what you verified, what you skipped, and every step where your machine differs from
  the reference layout. Do not report a step as done without its check passing.

## Layout (reference machine; change with `--hermes-root/--runtime/--llama/--repo`)

| Piece | Path |
|---|---|
| Repo, branch `nemotron-bolt-3.5` | `%USERPROFILE%\chief-of-staff-agent` |
| Hermes channel-build home | `%LOCALAPPDATA%\hermes-channel-build-nvidia-local-offer` |
| Profile | `<hermes home>\profiles\chief-of-staff` |
| Isolated Python + reset helpers | `%USERPROFILE%\chief-of-staff-runtime` (Python in `...\python`) |
| llama.cpp | `%USERPROFILE%\llama.cpp` (`bin\`, `models\`) |

## Phase 1: Hermes and the repository

1. Confirm Hermes Desktop (NVIDIA local-offer channel build) is installed: the folder
   `%LOCALAPPDATA%\hermes-channel-build-nvidia-local-offer` exists and
   `hermes-nvidia-local-offer.exe` is on PATH. If not, stop and ask for the installer; this skill
   cannot download it.
2. Clone the repo and check out `nemotron-bolt-3.5`.
3. Set `HERMES_HOME` to the **profile** folder under the channel-build home for every CLI call
   in this skill. The plain `hermes` command and `%LOCALAPPDATA%\hermes` are a different
   install that the Desktop app ignores.
4. `python install.py --hermes-home "<profile>"` creates the profile and installs the skills.
5. Connect the demo Google account and seed the workspace as `QUICKSTART.md` steps 3 and 4
   describe (`demo\seed_workspace.py`). This needs a browser sign-in by a person; ask for it.

Check: `python skills\setup\nemotron-bolt-demo-setup\scripts\check_setup.py --phase hermes`

## Phase 2: isolated Python

Hermes Desktop exports its own `PYTHONPATH` into terminal and cron child processes, which breaks
any ordinary Python (its bundled `cryptography` DLL cannot be loaded from outside the app). The
skill scripts therefore run on an isolated CPython 3.14:

1. Copy a CPython 3.14 (python.exe, python3*.dll, `DLLs\`, `Lib\`) to `<runtime>\python`.
2. Copy `demo\nemotron-bolt\python314._pth` next to `python.exe` (it makes the interpreter ignore
   `PYTHONPATH`/`PYTHONHOME`).
3. `<runtime>\python\python.exe -m pip install --only-binary=:all: -r requirements.txt`
4. Junction it where the skill looks for it:
   `New-Item -ItemType Junction -Path "<profile>\hermes-agent\venv\Scripts" -Target "<runtime>\python"`
   (create `<profile>\hermes-agent\venv` first).
5. Copy `demo\nemotron-bolt\shell-init.sh` to `<profile>\shell-init.sh` after Phase 4 has
   rewritten its paths.

Check: `check_setup.py --phase python` (imports `googleapiclient` and `cryptography` through the
junction).

## Phase 3: llama.cpp and the model files

1. From `https://github.com/ggml-org/llama.cpp/releases/tag/b12445` unzip
   `llama-b12445-bin-win-cuda-13.5-<arch>.zip` and `cudart-llama-bin-win-cuda-13.5-<arch>.zip`
   into `<llama>\bin` (`arm64` on RTX Spark / Windows on ARM, `x64` otherwise).
2. Download into `<llama>\models` (public, OpenMDW-1.1 licence):
   - `https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-GGUF/resolve/main/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB.gguf`
     (22,018,326,528 bytes, SHA-256 `91d63363e782c8a3d5f4be42816eba8e0d42dd2530bd07a7d0d2dc440599af75`)
   - `https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-LiLiCorr-GGUF/resolve/main/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-LiLiCorr.gguf`
     (998,242,560 bytes, SHA-256 `080e1ea41c9562a7804dbf30c6fbd4d17e216c6b8ff666f88e6edb1816010194`)
3. Copy `demo\nemotron-bolt\Start-Bolt.ps1`, `Switch-Model.ps1` and `Start-Qwen.ps1` to `<llama>\`.
4. Start the server: `powershell -ExecutionPolicy Bypass -File <llama>\Start-Bolt.ps1`
   (12–16 s to ready). Flags and their reasons are in `NEMOTRON_BOLT_SETUP.md` section 3c; do not
   change them when reproducing the reference numbers.

Check: `check_setup.py --phase model` (files, sizes, checksums with `--verify-sha`, server health,
alias `nemotron-3.5-bolt`, `n_ctx` 65536, a one-token generation with tokens/s).

## Phase 4: paths and skill text

The skill text and helper scripts on this branch carry the reference machine's literal paths
on purpose (it stopped Bolt searching for its scripts). Rewrite them for this machine:

```
python demo\nemotron-bolt\configure_paths.py --check
python demo\nemotron-bolt\configure_paths.py [--hermes-root ... --profile ... --runtime ... --llama ...]
```

Then install the rewritten skill into the profile (`python install.py --hermes-home "<profile>"`
again, or copy `skills\productivity\chief-of-staff` over `<profile>\skills\productivity\chief-of-staff`).
The profile holds a **copy**, not a link. Copy `demo\nemotron-bolt\shell-init.sh` and the reset
helpers (`Reset-Demo.cmd`, `Reset-Demo-KeepEmails.cmd`, `Next-Run.cmd`, `reset_keep_emails.py`,
`snapshot_tracker.py`) to their places (`<profile>` and `<runtime>`).

Check: `check_setup.py --phase paths` (no `SKILL_ROOT` or `Users\NVIDIA` left; every path named in
the profile's SKILL.md exists).

## Phase 5: profile configuration

Apply `demo\nemotron-bolt\config.chief-of-staff.yaml` (rewritten in Phase 4) as
`<profile>\config.yaml`, or set its keys: `model.default: nemotron-3.5-bolt`, `provider: custom`,
`base_url: http://127.0.0.1:8080/v1`, `context_length: 65536`;
`providers.local-qwen.extra_body.temperature: 0.6`; `terminal.shell_init_files` →
`<profile>\shell-init.sh`; toolsets `skills, terminal, cronjob`; memory, auxiliary and curator off;
`skills.auto_load: [chief-of-staff]` with the other bundled skills disabled. Restart Hermes Desktop.

Check: `check_setup.py --phase config`.

## Phase 6: run and score

1. Optional but recommended: create the morning-brief cron job (`README.md`, "Scheduled daily
   brief"). Without it the first prompt collects evidence live, as in the reference runs.
2. `Next-Run.cmd` (snapshot + reset), then a **new chat** in Hermes Desktop, type `hi`, then:
   - `hey chief of staff, tell me what should I work on today`
   - `Help me prepare for the exec review`
   - `Hey chief of staff, update the status of the NeoAgent V2 tracker`
3. Score from Hermes's records, not a stopwatch:
   `python demo\nemotron-bolt\eval\desktop_sessions.py "<YYYY-MM-DD HH:MM>"` and
   `python demo\nemotron-bolt\snapshot_tracker.py` (with `HERMES_HOME` = the profile).

Expected: about 30–36 s / 30–58 s / 76–83 s on battery (less on mains); 9–11 model turns; 6–9 tool
calls; no `Tool terminal returned error` lines in `<profile>\logs\agent.log`; tracker ends with
Performance results = Complete, Exec Review deck = In progress, Agent Messaging = In progress,
Legal intake LGL-2026-0847 = Complete, and the other four lanes unchanged. If Bolt leaves Agent
Messaging at "Awaiting update", note it: that lane is the one ambiguous call in the demo data.

Check: `check_setup.py --phase all` for the final report.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Profile not visible in Hermes Desktop | Installed under `%LOCALAPPDATA%\hermes` | Reinstall with `HERMES_HOME` under the channel-build folder |
| "Access is denied" importing `cryptography` from a skill command | Hermes's `PYTHONPATH` reached a normal venv | Use the isolated Python (`python314._pth`) and `shell-init.sh` |
| Model lists folders or probes for Python before the brief | Skill paths not rewritten, or old skill copy in the profile | Phase 4, then re-copy the skill into the profile |
| First prompt is slow and returns a 500-token planning text | Running through the CLI `-z` path | Use Hermes Desktop |
| ~35 tokens/s instead of ~80 | Laptop on battery | Plug in the charger |
| Desktop shows a model name that is not answering | Picker is only a label | Check `curl http://127.0.0.1:8080/v1/models` |
| Keep-emails reset refuses | No full reset yet today | Run `Reset-Demo.cmd` once |
