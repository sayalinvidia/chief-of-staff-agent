"""Collect Bolt facts for the deployment guide: Desktop turn durations and server-log stats."""
import os
import re

prof = os.path.expandvars(r"%LOCALAPPDATA%\hermes-channel-build-nvidia-local-offer\profiles\chief-of-staff")
log = open(prof + r"\logs\agent.log", encoding="utf-8", errors="replace").read().splitlines()
model_of = {}
for l in log:
    m = re.search(r"conversation turn: session=(\S+) model=(\S+) .*platform=(\S+) history=(\d+) msg='(.{0,30})", l)
    if m:
        model_of.setdefault(m[1], (m[2], m[3]))
        print(l[:19], m[1][-6:], m[2], m[3], "hist", m[4], repr(m[5])) if "bolt" in m[2] and m[3] == "desktop" else None
    m = re.search(r"tui turn finished: .*agent_session_id=(\S+) status=(\S+) .*duration=([\d.]+)s", l)
    if m and model_of.get(m[1], ("", ""))[0].endswith("bolt"):
        print("   ", l[:19], m[1][-6:], m[2], m[3] + "s")
    m = re.search(r"\[(\S+)\] agent.conversation_loop: Turn ended: .*api_calls=(\d+)/\d+ .*tool_turns=(\d+)", l)
    if m and model_of.get(m[1], ("", ""))[0].endswith("bolt") and model_of[m[1]][1] == "desktop":
        print("       api_calls", m[2], "tool_turns(cum)", m[3])
    if "Tool terminal returned error" in l and any(k in l for k in model_of if model_of[k][0].endswith("bolt")):
        print("       TOOL ERROR", l[60:170])

print("\n==== server log")
s = open(r"C:\Users\NVIDIA\llama.cpp\bolt-server-last.log", encoding="utf-16", errors="replace").read()
s = re.sub(r"\r?\n(?=[^\d\n])", "", s)  # re-join wrapped lines
for pat in [r"build:.*", r"system_info.*", r".*general\.name.*", r".*file type.*", r".*model params.*", r".*file size.*", r".*n_ctx .*",
            r".*offloaded \d+/\d+ layers.*", r".*CUDA0.*(model buffer|compute buffer|KV|context).*", r".*chat template.*", r".*thinking.*",
            r".*reasoning.*", r".*draft.*(n_max|loaded|model).*", r".*sampler.*", r".*temp.*top_p.*", r".*main: model loaded.*", r".*server is listening.*", r".*load time.*"]:
    hits = re.findall(pat, s)
    for h in hits[:4]:
        print(h[:230])
gen = [(int(a), float(b)) for a, b in re.findall(r"\|\s+eval time =\s*[\d.]+ ms /\s*(\d+) tokens \(.*?([\d.]+) tokens per second", s)]
pr = [(int(a), float(b)) for a, b in re.findall(r"prompt eval time =\s*[\d.]+ ms /\s*(\d+) tokens \(.*?([\d.]+) tokens per second", s)]
big = [g for g in gen if g[0] >= 200]
print("gen requests", len(gen), "tokens", sum(g[0] for g in gen), "speed range (>=200 tok)", min(g[1] for g in big), max(g[1] for g in big),
      "weighted", round(sum(g[0] for g in big) / sum(g[0] / g[1] for g in big), 1))
bp = [p for p in pr if p[0] >= 2000]
print("prompt speed (>=2000 tok)", [p[1] for p in bp])
acc = [(int(a), int(b)) for a, b in re.findall(r"draft acceptance = [\d.]+ \(\s*(\d+) accepted /\s*(\d+) generated", s)]
print("draft acceptance overall", round(sum(a for a, _ in acc) / sum(b for _, b in acc), 3), "requests", len(acc))
