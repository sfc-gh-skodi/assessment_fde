#!/usr/bin/env python3
"""Export this project's AI session record into the repo (text only, no binaries).

  python3 tools/export_session.py [MAIN_SESSION_ID]

Writes:
  ai-sessions/raw/<id>.json, <id>.history.jsonl   raw Cortex Code session files (main + subagents),
                                                  copied verbatim EXCEPT embedded base64 file
                                                  payloads (e.g. the one-pager PDF an agent read),
                                                  which are replaced by a placeholder string so no
                                                  binary content lands in git.
  prompts/user_prompts.md                         every prompt the user typed, in order, with time
  prompts/subagent_prompts.md                     every prompt the main agent sent to a subagent
  git-history/git_log.txt                         git log --stat (fuller)
  git-history/git_log_patch.txt                   full patch history (binary diffs shown as text stubs)
  git-history/git_reflog.txt                      reflog (shows the amend + force-push that dropped binaries)
Re-run at the end of the session to refresh.
"""
import datetime, glob, json, os, re, subprocess, sys

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CONV = os.path.expanduser("~/.snowflake/cortex/conversations")
MAIN = sys.argv[1] if len(sys.argv) > 1 else "cf78df4d-6085-4d1f-90b5-dfd32d2a4e14"
NOISE = ("<system-reminder>", "<system_context_from_session_hook>")


def scrub(obj, stats):
    """Replace base64 payloads of embedded files; everything else untouched."""
    if isinstance(obj, dict):
        src = obj.get("source")
        if isinstance(src, dict) and src.get("type") == "base64" and isinstance(src.get("data"), str):
            stats["blobs"] += 1
            stats["bytes"] += len(src["data"])
            src = dict(src, data=f"<omitted: base64 {src.get('media_type', 'binary')}, {len(src['data'])} chars; binary files are not committed>")
            obj = dict(obj, source=src)
        return {k: scrub(v, stats) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, stats) for v in obj]
    return obj


def when(ts):
    if not ts:
        return ""
    if isinstance(ts, (int, float)) or str(ts).isdigit():
        return datetime.datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    return str(ts)


def main():
    hits = glob.glob(os.path.join(CONV, "*", MAIN + ".json"))
    if not hits:
        sys.exit(f"session {MAIN} not found under {CONV}")
    folder = os.path.dirname(hits[0])
    meta = json.load(open(hits[0]))
    refs = meta.get("subagentRefs") or []
    if isinstance(refs, str):
        refs = json.loads(refs.replace("'", '"'))
    ids = [MAIN] + [r["subagentSessionId"] for r in refs]

    raw = os.path.join(REPO, "ai-sessions", "raw")
    os.makedirs(raw, exist_ok=True)
    stats = {"blobs": 0, "bytes": 0}
    index = []
    for sid in ids:
        m = json.load(open(os.path.join(folder, sid + ".json")))
        json.dump(scrub(m, stats), open(os.path.join(raw, sid + ".json"), "w"), indent=1, ensure_ascii=False)
        hp = os.path.join(folder, sid + ".history.jsonl")
        n = 0
        if os.path.exists(hp):
            with open(hp) as fin, open(os.path.join(raw, sid + ".history.jsonl"), "w") as fout:
                for line in fin:
                    if line.strip():
                        fout.write(json.dumps(scrub(json.loads(line), stats), ensure_ascii=False) + "\n"); n += 1
        index.append((sid, m.get("title", ""), m.get("sessionType", "main"), n))

    # prompts
    os.makedirs(os.path.join(REPO, "prompts"), exist_ok=True)
    hist = [json.loads(l) for l in open(os.path.join(folder, MAIN + ".history.jsonl")) if l.strip()]
    up, sp = ["# User prompts (in order)\n"], ["# Prompts sent by the main agent to subagents\n"]
    k = 0
    for msg in hist:
        parts = msg.get("content") if isinstance(msg.get("content"), list) else []
        if msg.get("role") == "user":
            texts = [p.get("text", "") for p in parts if p.get("type") == "text" and not p.get("text", "").startswith(NOISE)]
            texts = [re.sub(r"<system-reminder>.*?</system-reminder>", "", t, flags=re.S).strip() for t in texts]
            texts = [t for t in texts if t]
            if texts:
                k += 1
                up.append(f"\n## {k}. {when(msg.get('user_sent_time'))}\n\n" + "\n\n".join(texts) + "\n")
        for p in parts:
            tu = p.get("tool_use") if isinstance(p.get("tool_use"), dict) else p   # stored as {"type":"tool_use","tool_use":{...}}
            if p.get("type") == "tool_use" and tu.get("name") == "task":
                inp = tu.get("input", {})
                sp.append(f"\n## {inp.get('description', '')} ({inp.get('subagent_type', 'generalPurpose')})\n\n```\n{inp.get('prompt', '')}\n```\n")
    open(os.path.join(REPO, "prompts", "user_prompts.md"), "w").write("".join(up))
    open(os.path.join(REPO, "prompts", "subagent_prompts.md"), "w").write("".join(sp))

    # git history
    gh = os.path.join(REPO, "git-history")
    os.makedirs(gh, exist_ok=True)
    git = lambda *a: subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True).stdout
    open(os.path.join(gh, "git_log.txt"), "w").write(git("log", "--stat", "--format=fuller", "--all"))
    open(os.path.join(gh, "git_log_patch.txt"), "w").write(git("log", "-p", "--format=fuller", "--all"))
    open(os.path.join(gh, "git_reflog.txt"), "w").write(git("reflog", "--date=iso"))

    print(f"sessions: {len(index)}")
    for sid, title, typ, n in index:
        print(f"  {sid}  {typ:<8} {n:>4} msgs  {title}")
    print(f"user prompts: {k}; base64 payloads omitted: {stats['blobs']} ({stats['bytes']} chars)")


if __name__ == "__main__":
    main()
