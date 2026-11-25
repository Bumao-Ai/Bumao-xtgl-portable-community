# -*- coding: utf-8 -*-
"""Cleanup of supervision-round artifacts: only deletes what this package generated under
run_dir.

User constraints (2026-11-08):
1. Only clean round-generated artifacts under jiancha_run; ticket book, ledger, _frozen and
   the live tree never enter deletion scope.
2. Rounds in use / unfinished must be skipped.
3. Emit a retention policy first, then a dry-run; nothing is deleted by default, only
   explicit --apply deletes.

Retention policy (parameters under the qingli section of jiancha_canshu.json):
- baseline: workspace snapshot copy. **When the round carries halt_*/quarantine evidence
  bundles, the baseline shares their lifetime** (while evidence bundles stay inside the
  retention window, the baseline is not cleaned) — it is the only copy of what the live
  tree looked like at interception; rounds that intercepted nothing keep only the current
  copy (a new begin re-snapshots).
- evidence: halt_* and quarantine/* bundles, keep the most recent keep_evidence (default 10)
  of each; older ones are cleaned.
- Ledger actions.jsonl and state.json are kept forever: never deleted, audit/forensics only.
- Total cap max_total_mb (default 400): if still over after cleaning, report only; never
  cross the line to delete the ledger.
- Trigger: at startup (before Supervisor.begin). Rationale: failed rounds never reach the
  teardown hook; begin is the old/new round switch point, at which the old round is
  necessarily no longer in use by the process; teardown cleanup covers only the few
  normally-finished cases.

Skip rules:
- run_dir missing -> nothing to clean.
- state.status == "running" -> this round is in use, skip (never clean under any condition).
- state.status other unfinished states (e.g. halted):
  * auto hook (new-round begin) may clean: begin overwrites state, the old round was
    abandoned;
  * manual CLI skips by default (strict "unfinished must skip"); pass --allow-halted to
    clean deliberately.
- Latest round started less than min_age_hours (default 1h) ago -> skip, guards against
  concurrent mis-cleanup.
"""

import io
import json
import os
import shutil
import time

DEFAULTS = {
    "enabled": True,
    "min_age_hours": 1,
    "keep_evidence": 10,
    "max_total_mb": 400,
}

# Files never deleted at the run_dir root (ticket book lives elsewhere; this lists only
# ledger/state/fingerprint files inside this directory)
PROTECTED = ("actions.jsonl", "state.json", "state.json.tmp",
             "gate_ref.json", "jiancha_canshu.json", "qingli.log")


def settings(cfg):
    s = dict(DEFAULTS)
    s.update((cfg or {}).get("qingli") or {})
    return s


def _state(run_dir):
    p = os.path.join(run_dir, "state.json")
    if not os.path.isfile(p):
        return None
    try:
        with io.open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _started_at(st):
    s = str((st or {}).get("started_at") or "")
    try:
        return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None


def _dir_bytes(path):
    total = 0
    for base, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            p = os.path.join(base, name)
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
    return total


def _inside(base, path):
    try:
        return os.path.commonpath([os.path.abspath(base), os.path.abspath(path)]) == os.path.abspath(base)
    except ValueError:
        return False


def _evidence_all(run_dir):
    """Return all evidence bundle paths (halt, quarantine), sorted by name."""
    root = os.path.join(run_dir, "evidence")
    halt, quar = [], []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name)
            if not os.path.isdir(p):
                continue
            if name.startswith("halt_"):
                halt.append(p)
            elif name == "quarantine":
                for sub in sorted(os.listdir(p)):
                    sp = os.path.join(p, sub)
                    if os.path.isdir(sp):
                        quar.append(sp)
    return halt, quar


def _evidence_bundles(run_dir, keep):
    """Cleanable bundles under evidence: halt_* and quarantine/*, keep the most recent
    keep of each (sorted by name)."""
    halt, quar = _evidence_all(run_dir)
    drop = halt[:-keep] if keep > 0 else list(halt)
    drop += quar[:-keep] if keep > 0 else list(quar)
    return drop


def plan(run_dir, cfg=None, now=None, allow_halted=False):
    """Plan only, delete nothing. Returns a dict: skip / items / freed_bytes /
    total_bytes / remaining_bytes."""
    s = settings(cfg)
    now = time.time() if now is None else now
    out = {"run_dir": run_dir or "", "skip": "", "items": [], "freed_bytes": 0,
           "total_bytes": 0, "remaining_bytes": 0, "warnings": [], "policy": s}
    if not run_dir or not os.path.isdir(run_dir):
        out["skip"] = "run_dir 不存在，无可清理"
        return out
    out["total_bytes"] = _dir_bytes(run_dir)

    st = _state(run_dir)
    status = str((st or {}).get("status") or "")
    if status == "running":
        out["skip"] = "本轮状态 running（正在用），跳过"
        return out
    if status == "halted" and not allow_halted:
        out["skip"] = "本轮状态 halted（未结束，需先 recover/done），跳过（确需清理加 --allow-halted）"
        return out
    started = _started_at(st)
    if started is not None:
        age_h = (now - started) / 3600.0
        if age_h < float(s["min_age_hours"]):
            out["skip"] = "本轮开始仅 %.1f 小时（< min_age_hours=%s），跳过" % (age_h, s["min_age_hours"])
            return out

    items = []
    base = os.path.join(run_dir, "baseline")
    halt_all, quar_all = _evidence_all(run_dir)
    if os.path.isdir(base):
        if halt_all or quar_all:
            # User review rule (2026-11-08): the baseline is the only copy of what the
            # live tree looked like at interception; when the round has halt/quarantine
            # bundles, the baseline shares their lifetime (stays inside the evidence
            # retention window).
            out["warnings"].append(
                "baseline 保留：本目录有 halt %d 束／quarantine %d 束，基线与其同寿命"
                % (len(halt_all), len(quar_all)))
        elif st is None and (now - _mtime(base)) / 3600.0 < float(s["min_age_hours"]):
            out["warnings"].append("baseline 无 state 且新鲜（< min_age_hours），本轮跳过它")
        else:
            items.append(base)
    items.extend(_evidence_bundles(run_dir, int(s["keep_evidence"])))

    for p in items:
        name = os.path.basename(p)
        if name in PROTECTED or "_frozen" in name.lower():
            out["warnings"].append("受保护件拒删：%s" % p)
            continue
        if not _inside(run_dir, p):
            out["warnings"].append("越界拒删：%s" % p)
            continue
        size = _dir_bytes(p)
        out["items"].append({
            "path": p,
            "rel": os.path.relpath(p, run_dir).replace("\\", "/"),
            "kind": "baseline" if p == base else "evidence",
            "bytes": size,
        })
        out["freed_bytes"] += size

    out["remaining_bytes"] = max(0, out["total_bytes"] - out["freed_bytes"])
    cap = int(float(s["max_total_mb"]) * 1024 * 1024)
    if out["remaining_bytes"] > cap:
        out["warnings"].append("清完仍剩 %.1f MB，超过上限 %.0f MB（账本/票本不动，需人工处理）"
                               % (out["remaining_bytes"] / 1048576.0, float(s["max_total_mb"])))
    return out


def apply(rep):
    """Execute the plan result. Re-verify ownership per item; a failed item does not
    block the rest."""
    done, failed = [], []
    base = rep.get("run_dir") or ""
    for it in rep.get("items") or []:
        p = it["path"]
        if os.path.basename(p) in PROTECTED or not _inside(base, p):
            failed.append({"path": p, "why": "受保护或越界"})
            continue
        try:
            shutil.rmtree(p)
            done.append(it)
        except OSError as e:
            failed.append({"path": p, "why": "%s: %s" % (type(e).__name__, e)})
    rep["deleted"] = done
    rep["failed"] = failed
    rep["freed_bytes"] = sum(x["bytes"] for x in done)
    rep["remaining_bytes"] = max(0, rep.get("remaining_bytes", 0) + (rep.get("freed_bytes", 0) - rep["freed_bytes"]))
    return rep


def _log(run_dir, line):
    try:
        with io.open(os.path.join(run_dir, "qingli.log"), "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    except OSError:
        pass


def before_begin(run_dir, cfg):
    """Pre-Supervisor.begin hook: clean old-round snapshots and over-age evidence bundles.
    Silent; nothing written to stdout."""
    s = settings(cfg)
    if not s.get("enabled") or not run_dir or not os.path.isdir(run_dir):
        return None
    rep = plan(run_dir, cfg, allow_halted=True)
    if rep["skip"]:
        _log(run_dir, "[qingli] skip: %s" % rep["skip"])
        return rep
    apply(rep)
    _log(run_dir, "[qingli] 删除 %d 项 / 释放 %.1f MB / 清后剩 %.1f MB%s"
         % (len(rep.get("deleted") or []), rep["freed_bytes"] / 1048576.0,
            rep["remaining_bytes"] / 1048576.0,
            (" ｜ " + "；".join(rep["warnings"])) if rep.get("warnings") else ""))
    return rep


def _fmt(rep):
    lines = []
    tag = "dry-run" if rep.get("_dry") else "APPLY"
    lines.append("[清理·%s] run_dir=%s" % (tag, rep.get("run_dir") or ""))
    if rep["skip"]:
        lines.append("  跳过：%s" % rep["skip"])
        return lines
    st = "未知"
    try:
        st = str((_state(rep["run_dir"]) or {}).get("status") or "无 state")
    except Exception:
        pass
    lines.append("  轮次状态=%s ｜ 总量 %.1f MB ｜ 策略：留 %s 份证据束、上限 %s MB、min_age %s h"
                 % (st, rep["total_bytes"] / 1048576.0, rep["policy"]["keep_evidence"],
                    rep["policy"]["max_total_mb"], rep["policy"]["min_age_hours"]))
    if not rep["items"]:
        lines.append("  无可清理项（账本/状态/票本一律不动）")
    else:
        lines.append("  将删 %d 项 / 共 %.1f MB：" % (len(rep["items"]), rep["freed_bytes"] / 1048576.0))
        for it in rep["items"]:
            lines.append("    - %s（%s，%.1f MB）" % (it["rel"], it["kind"], it["bytes"] / 1048576.0))
    lines.append("  清后剩余 %.1f MB / 上限 %s MB" % (rep["remaining_bytes"] / 1048576.0,
                                                     rep["policy"]["max_total_mb"]))
    for w in rep.get("warnings") or []:
        lines.append("  [提醒] %s" % w)
    return lines


def main(argv):
    run_dir = ""
    do_apply = "--apply" in argv
    allow_halted = "--allow-halted" in argv
    as_json = "--json" in argv
    if "--run-dir" in argv:
        i = argv.index("--run-dir")
        if i + 1 < len(argv):
            run_dir = argv[i + 1]
    if not run_dir:
        print("用法：python -m runtime_guard.qingli --run-dir <run_dir> [--apply] [--allow-halted] [--json]")
        return 2
    cfg = {}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jiancha_canshu.json")
    if os.path.isfile(p):
        with io.open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    rep = plan(run_dir, cfg, allow_halted=allow_halted)
    if do_apply and not rep["skip"]:
        apply(rep)
        _log(run_dir, "[qingli] 手工 APPLY 删除 %d 项 / 释放 %.1f MB"
             % (len(rep.get("deleted") or []), rep["freed_bytes"] / 1048576.0))
    else:
        rep["_dry"] = True
    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        for ln in _fmt(rep):
            print(ln)
    return 0 if (not rep["skip"] or not do_apply) else 1


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
