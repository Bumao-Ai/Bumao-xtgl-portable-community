# -*- coding: utf-8 -*-
"""community 端监管适配器反向用例：三反一正。

正：合规单＋工作区内写 → 放行。
反1：单已过期 → 拒。
反2：目标落拒绝区 → 拒（enforce 下动作不执行）。
反3：无意图单 → 拒（fail-closed，不裸奔）。
另测：未登记路由 → 只记账、covered=false（明确记为未覆盖）。

跑法（本包上级 10_rac 必须在 sys.path 上）：
    python test_community_adapter.py
产物落在临时目录；退出码 0＝全过。
"""

import io
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from runtime_guard import community_adapter as A  # noqa: E402

CASES = []


def check(label, ok, detail=""):
    CASES.append((label, bool(ok), detail))
    print("%s %s%s" % ("PASS" if ok else "FAIL", label,
                       ("  :: " + str(detail)) if detail else ""))


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def make_project(tmp, name="proj"):
    root = os.path.join(tmp, name)
    _write(os.path.join(root, "40_renwu", "tasks.json"), "[]\n")
    _write(os.path.join(root, "00_meta", "meta.json"), "{}\n")
    _write(os.path.join(root, "90_lishi", "old.json"), "{}\n")
    return root


def order_for(root, order_id="ORD-T-MINIMAL", expires=None, approved=None):
    return {
        "schema": "intent/1",
        "order_id": order_id,
        "workspace": os.path.basename(root),
        "approved_at": approved or time.strftime("%Y-%m-%d %H:%M:%S"),
        "expires_at": expires or time.strftime("%Y-%m-%d %H:%M:%S",
                                               time.localtime(time.time() + 3600)),
        "approved_by": "测试",
        "note": "适配器自测",
        "allowed_actions": ["file_read", "file_write"],
        "approved_roots": ["40_renwu"],
        "approved_files": [],
        "denied_zones": ["90_lishi", ".git", "secret"],
    }


class FakeConsole(object):
    def __init__(self, root, board_rel="40_renwu/tasks.json"):
        self.root = root
        self.board_rel = board_rel

    def _board_path(self, board):
        return board, os.path.join(self.root, *self.board_rel.split("/"))

    def _proj_cfg(self):
        return {"state_file": "40_renwu/state.json"}

    def _proj_path(self, cfg, key, required_msg):
        f = cfg.get(key) or ""
        if not f:
            raise RuntimeError(required_msg)
        return os.path.join(self.root, *f.split("/"))


def point_at(cfg_path, order_path, run_dir):
    A.CFG_PATH = cfg_path
    A.ORDER_PATH = order_path
    A.RUN_DIR = run_dir
    A._SINGLETONS.clear()


def run_case(tmp, name, board_rel, expired=False, no_order=False):
    root = make_project(tmp, name)
    pkg = os.path.join(tmp, name + "_pkg")
    run_dir = os.path.join(tmp, name + "_run")
    os.makedirs(pkg, exist_ok=True)
    _write(os.path.join(pkg, "jiancha_canshu.json"),
           json.dumps(json.load(open(os.path.join(HERE, "jiancha_canshu.json"),
                                     encoding="utf-8")), ensure_ascii=False))
    order_path = os.path.join(pkg, "order.json")
    if not no_order:
        now = time.time()
        if expired:
            ap = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 7200))
            exp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 3600))
        else:
            ap = time.strftime("%Y-%m-%d %H:%M:%S")
            exp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now + 3600))
        with io.open(order_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(order_for(root, name, exp, ap), f, ensure_ascii=False, indent=1)
    point_at(os.path.join(pkg, "jiancha_canshu.json"), order_path, run_dir)

    c = FakeConsole(root, board_rel)
    ctx = A.begin_post(c, "/api/task/add", {"board": "goals"}, "enforce")
    executed = False
    if not (ctx and ctx.get("blocked")):
        _write(os.path.join(root, *board_rel.split("/")), "[]\n")
        executed = True
    A.end_post(ctx, None)
    return ctx or {}, executed, run_dir


def main():
    tmp = tempfile.mkdtemp(prefix="t_min_adapter_")
    try:
        ctx, ran, rd = run_case(tmp, "ok", "40_renwu/tasks.json")
        check("正例：合规单放行并执行", ran and not ctx.get("blocked"),
              ctx.get("body", ""))

        ctx, ran, rd = run_case(tmp, "expired", "40_renwu/tasks.json", expired=True)
        check("反1：过期单被拒", bool(ctx.get("blocked")) and not ran,
              (ctx.get("body") or {}).get("error", ""))

        ctx, ran, rd = run_case(tmp, "outzone", "90_lishi/tasks.json")
        check("反2：目标落拒绝区被拒且未执行", bool(ctx.get("blocked")) and not ran,
              (ctx.get("body") or {}).get("error", ""))

        ctx, ran, rd = run_case(tmp, "noorder", "40_renwu/tasks.json", no_order=True)
        check("反3：无意图单被拒（fail-closed）", bool(ctx.get("blocked")) and not ran,
              (ctx.get("body") or {}).get("error", ""))

        root = make_project(tmp, "observed")
        pkg = os.path.join(tmp, "observed_pkg")
        os.makedirs(pkg, exist_ok=True)
        shutil.copyfile(os.path.join(HERE, "jiancha_canshu.json"),
                        os.path.join(pkg, "jiancha_canshu.json"))
        op = os.path.join(pkg, "order.json")
        with io.open(op, "w", encoding="utf-8", newline="\n") as f:
            json.dump(order_for(root, "observed"), f, ensure_ascii=False)
        point_at(os.path.join(pkg, "jiancha_canshu.json"), op,
                 os.path.join(tmp, "observed_run"))
        ctx = A.begin_post(FakeConsole(root), "/api/ai/test", {}, "enforce")
        A.end_post(ctx, None)
        rows = [json.loads(x) for x in io.open(
            os.path.join(tmp, "observed_run", "actions.jsonl"), encoding="utf-8")
            if x.strip()]
        last = rows[-1]
        check("未登记路由只记账、covered=false",
              last.get("result") == "ok" and (last.get("covered") is False
                                              or (last.get("extra") or {}).get("covered") is False),
              json.dumps({k: last.get(k) for k in ("seq", "target", "result", "covered")},
                         ensure_ascii=False))

        bad = [c for c in CASES if not c[1]]
        print("ALL PASS" if not bad else "FAIL %d" % len(bad))
        return 0 if not bad else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    print("== community 适配器三反一正 ==")
    raise SystemExit(main())
