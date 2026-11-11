#!/usr/bin/env python3
"""Export AI session records into the repo (text only, no binaries).

  python3 minivm-takehome/tools/export_session.py [--no-git] [SESSION_ID ...]      default: cf78df4d-6085-4d1f-90b5-dfd32d2a4e14

--no-git skips regenerating git-history/ (the Stop hook uses it, so every commit doesn't
show up as a fresh diff; run without it before your final commit).

Each SESSION_ID is a main Cortex Code session; its subagent sessions are found and
exported with it. Exports accumulate: running it for one session never overwrites
another session's files.

Writes, per session (<id8> = first 8 characters of the id):
  ai-sessions/raw/<id>.json, <id>.history.jsonl   raw session files (main + subagents), copied
                                                  verbatim EXCEPT embedded base64 file payloads
                                                  (e.g. a PDF an agent read), which are replaced
                                                  by a placeholder so no binary content lands in git.
  prompts/<id8>_user_prompts.md                   every prompt the user typed, in order, with time
  prompts/<id8>_subagent_prompts.md               every prompt the main agent sent to a subagent
Shared (rebuilt on every run):
  prompts/INDEX.md                                one row per exported main session
  git-history/git_log.txt                         git log --stat (fuller)
  git-history/git_log_patch.txt                   full patch history (binary diffs shown as text stubs)
  git-history/git_reflog.txt                      reflog
Find a session id: it is printed as CX_SESSION_ID at session start, or run
  ls -t ~/.snowflake/cortex/conversations/*/ | head
Re-run at the end of a session so its last turns are included. This also happens
automatically: tools/hooks/export_session_hook.sh (a Cortex Code Stop + SessionEnd hook)
runs this script for every session whose working directory is this repo.
"""
import datetime, glob, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
# the git repo root, wherever tools/ now lives inside it
REPO = subprocess.run(["git", "-C", HERE, "rev-parse", "--show-toplevel"], capture_output=True,
                      text=True).stdout.strip() or os.path.normpath(os.path.join(HERE, ".."))
CONV = os.path.expanduser("~/.snowflake/cortex/conversations")
DEFAULT = "cf78df4d-6085-4d1f-90b5-dfd32d2a4e14"
NOISE = ("<system-reminder>", "<system_context_from_session_hook>")
RAW = os.path.join(REPO, "ai-sessions", "raw")
PROMPTS = os.path.join(REPO, "ai-sessions", "prompts")


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
    """Epoch-ms or ISO-8601 -> 'YYYY-MM-DD HH:MM:SS UTC'."""
    if not ts:
        return ""
    utc = datetime.timezone.utc
    if isinstance(ts, (int, float)) or str(ts).isdigit():
        d = datetime.datetime.fromtimestamp(int(ts) / 1000, utc)
    else:
        try:
            d = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(utc)
        except ValueError:
            return str(ts)
    return d.strftime("%Y-%m-%d %H:%M:%S UTC")


def locate(sid):
    hits = glob.glob(os.path.join(CONV, "*", sid + ".json"))
    if hits:
        return os.path.dirname(hits[0])
    if os.path.exists(os.path.join(CONV, sid + ".json")):
        return CONV
    sys.exit(f"session {sid} not found under {CONV}")


def subagent_ids(meta):
    refs = meta.get("subagentRefs") or []
    if isinstance(refs, str):
        refs = json.loads(refs.replace("'", '"'))
    return [r["subagentSessionId"] for r in refs]


def extract_prompts(history_path):
    hist = [json.loads(l) for l in open(history_path) if l.strip()]
    users, subs = [], []
    for msg in hist:
        parts = msg.get("content") if isinstance(msg.get("content"), list) else []
        if msg.get("role") == "user":
            texts = [p.get("text", "") for p in parts if p.get("type") == "text" and not p.get("text", "").startswith(NOISE)]
            texts = [re.sub(r"<system-reminder>.*?</system-reminder>", "", t, flags=re.S).strip() for t in texts]
            texts = [t for t in texts if t]
            if texts:
                users.append((when(msg.get("user_sent_time")), "\n\n".join(texts)))
        for p in parts:
            tu = p.get("tool_use") if isinstance(p.get("tool_use"), dict) else p   # stored as {"type":"tool_use","tool_use":{...}}
            if p.get("type") == "tool_use" and tu.get("name") == "task":
                inp = tu.get("input", {})
                subs.append((inp.get("description", ""), inp.get("subagent_type", "generalPurpose"), inp.get("prompt", "")))
    return users, subs


def export(sid, stats):
    folder = locate(sid)
    meta = json.load(open(os.path.join(folder, sid + ".json")))
    if meta.get("sessionType") == "subagent":   # subagents are exported with their parent session
        return None, 0, 0
    exported = []
    for x in [sid] + subagent_ids(meta):
        m = json.load(open(os.path.join(folder, x + ".json")))
        json.dump(scrub(m, stats), open(os.path.join(RAW, x + ".json"), "w"), indent=1, ensure_ascii=False)
        hp, n = os.path.join(folder, x + ".history.jsonl"), 0
        if os.path.exists(hp):
            with open(hp) as fin, open(os.path.join(RAW, x + ".history.jsonl"), "w") as fout:
                for line in fin:
                    if line.strip():
                        fout.write(json.dumps(scrub(json.loads(line), stats), ensure_ascii=False) + "\n"); n += 1
        exported.append((x, m.get("sessionType", "main"), n, m.get("title", "")))

    users, subs = extract_prompts(os.path.join(folder, sid + ".history.jsonl"))
    title = meta.get("title", "")
    head = f"Session `{sid}` · {title}\n"
    with open(os.path.join(PROMPTS, f"{sid[:8]}_user_prompts.md"), "w") as f:
        f.write(f"# User prompts (in order)\n\n{head}\nprompts: {len(users)}\n")
        for i, (t, text) in enumerate(users, 1):
            f.write(f"\n## {i}. {t}\n\n{text}\n")
    with open(os.path.join(PROMPTS, f"{sid[:8]}_subagent_prompts.md"), "w") as f:
        f.write(f"# Prompts sent by the main agent to subagents\n\n{head}")
        for desc, typ, prompt in subs:
            f.write(f"\n## {desc} ({typ})\n\n```\n{prompt}\n```\n")
    return exported, len(users), len(subs)


def write_index():
    """One row per exported main session, built from what is on disk (so it survives across runs)."""
    rows = []
    for p in sorted(glob.glob(os.path.join(RAW, "*.json"))):
        m = json.load(open(p))
        if m.get("sessionType") == "subagent":
            continue
        sid = m.get("session_id") or os.path.basename(p)[:-5]
        up = os.path.join(PROMPTS, f"{sid[:8]}_user_prompts.md")
        hit = re.search(r"^prompts: (\d+)$", open(up).read(), re.M) if os.path.exists(up) else None
        n = int(hit.group(1)) if hit else 0
        started = when(m.get("creationDate"))
        hp = os.path.join(RAW, sid + ".history.jsonl")
        if not started and os.path.exists(hp):          # some sessions have no creationDate: use the first message
            first = next((json.loads(l) for l in open(hp) if l.strip()), {})
            started = when(first.get("user_sent_time"))
        rows.append((started, sid, m.get("title", ""), n, len(subagent_ids(m))))
    rows.sort()
    with open(os.path.join(PROMPTS, "INDEX.md"), "w") as f:
        f.write("# Exported sessions\n\nRegenerate: `python3 minivm-takehome/tools/export_session.py <session-id> ...`\n\n")
        f.write("| Started | Session | Title | User prompts | Subagents | Files |\n|---|---|---|---|---|---|\n")
        for started, sid, title, n, nsub in rows:
            f.write(f"| {started} | `{sid}` | {title} | {n} | {nsub} | "
                    f"[user]({sid[:8]}_user_prompts.md) · [subagent]({sid[:8]}_subagent_prompts.md) |\n")
    return len(rows)


def write_git_history():
    gh = os.path.join(REPO, "ai-sessions", "git-history")
    os.makedirs(gh, exist_ok=True)
    git = lambda *a: subprocess.run(["git", "-C", REPO, *a], capture_output=True, text=True).stdout
    open(os.path.join(gh, "git_log.txt"), "w").write(git("log", "--stat", "--format=fuller", "--all"))
    open(os.path.join(gh, "git_log_patch.txt"), "w").write(git("log", "-p", "--format=fuller", "--all"))
    open(os.path.join(gh, "git_reflog.txt"), "w").write(git("reflog", "--date=iso"))


def main():
    args = sys.argv[1:]
    no_git = "--no-git" in args
    ids = [a for a in args if a != "--no-git"] or [DEFAULT]
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(PROMPTS, exist_ok=True)
    stats = {"blobs": 0, "bytes": 0}
    for sid in ids:
        exported, nu, ns = export(sid, stats)
        if exported is None:
            print(f"{sid}: subagent session, skipped (exported with its parent)")
            continue
        print(f"{sid}: {len(exported)} session file pair(s), {nu} user prompts, {ns} subagent prompts")
        for x, typ, n, title in exported:
            print(f"  {x}  {typ:<8} {n:>4} msgs  {title}")
    total = write_index()
    if not no_git:
        write_git_history()
    print(f"index: {total} main session(s) in prompts/INDEX.md; git-history {'skipped' if no_git else 'refreshed'}; "
          f"base64 payloads omitted: {stats['blobs']} ({stats['bytes']} chars)")


if __name__ == "__main__":
    main()
