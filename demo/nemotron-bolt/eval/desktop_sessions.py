"""List Hermes Desktop sessions since a given local time with per-prompt timings and tool calls."""
import sqlite3, sys, json, time, os
db = os.path.expandvars(r"%LOCALAPPDATA%\hermes-channel-build-nvidia-local-offer\profiles\chief-of-staff\state.db")
since = time.mktime(time.strptime(sys.argv[1], "%Y-%m-%d %H:%M"))
full = len(sys.argv) > 2
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
for s in c.execute("select * from sessions where started_at>=? order by started_at", (since,)):
    msgs = c.execute("select * from messages where session_id=? order by timestamp, id", (s["id"],)).fetchall()
    print(f"\n=== {s['id']} src={s['source']} model={s['model']} start={time.strftime('%H:%M:%S', time.localtime(s['started_at']))} msgs={len(msgs)}")
    i = 0
    while i < len(msgs):
        m = msgs[i]
        if m["role"] == "user":
            j = i + 1
            turns = tools = fails = 0
            cmds = []
            last = m
            while j < len(msgs) and msgs[j]["role"] != "user":
                x = msgs[j]
                if x["role"] == "assistant":
                    turns += 1
                    if x["tool_calls"]:
                        tc = json.loads(x["tool_calls"])
                        tools += len(tc)
                        for t in tc:
                            f = t.get("function", t)
                            cmds.append((f.get("name"), str(f.get("arguments"))[:300 if full else 110]))
                    last = x
                elif x["role"] == "tool":
                    body = x["content"] or ""
                    if '"exit_code": 0' not in body and "exit_code" in body or "Traceback" in body or '"error"' in body[:200]:
                        fails += 1
                        cmds.append(("  FAIL", body[:300].replace("\n", " ")))
                    last = x if x["timestamp"] > last["timestamp"] else last
                j += 1
            final = next((x for x in reversed(msgs[i+1:j]) if x["role"] == "assistant" and not x["tool_calls"]), None)
            end = final["timestamp"] if final else last["timestamp"]
            print(f"\n[{time.strftime('%H:%M:%S', time.localtime(m['timestamp']))}] USER: {(m['content'] or '')[:70]!r}  -> {end - m['timestamp']:.0f}s turns={turns} tools={tools} fails={fails}")
            for n, a in cmds:
                print("   ", n, a)
            if final:
                txt = final["content"] or ""
                print("    REPLY opens:", repr(txt[:160]), "| len", len(txt))
                if full: print(txt)
            i = j
        else:
            i += 1
