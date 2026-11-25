# -*- coding: utf-8 -*-
"""community_adapter.py —— community 端 Web 写接口接入层（挂 do_POST 两处）。

契约：
  begin_post(console, path, payload, mode) -> ctx|None
  end_post(ctx, exc_info) -> None

  ctx["blocked"]=True 时调用方直接回 403 + ctx["body"]，不进入路由分支。
  off 路径由调用方（do_POST 内联 env 判断）短路，本模块根本不会被 import。

覆盖口径（v0.2）：
  gated    目标能在动作前唯一确定、且落在工作区内的 5 个写路由：task/add、task/delete、
           project/status、task/status、task/stub
  observed 其余写路由（配置/向导/AI/健康/导出/OSS 等）：目标在工作区外或 handler 内派生，
           动作前无法判定，只记账并标 covered=false —— 不假装已覆盖

已知缺口（与 0.2 内核评估一致，未在本轮修）：
  S1 的窗口扫描只认主目标，写方法照旧生成的 .bak/.archive.txt 会被判「额外汇出」。
  因此 enforce 下 S1 恒红，只能做事后中断留证，拦不住已落盘那一下。一期建议只跑 shadow。
"""
import json
import os
import threading
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_DIR = os.path.join(HERE, "jiancha_run")
ORDER_PATH = os.path.join(RUN_DIR, "order.json")
CFG_PATH = os.path.join(HERE, "jiancha_canshu.json")

MODE_ENV = "BUMO_JIANCHA_MODE"
MODES = ("off", "shadow", "enforce")

LOCK = threading.RLock()
_SINGLETONS = {}


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _release(ctx):
    if ctx.get("_locked"):
        ctx["_locked"] = False
        LOCK.release()


def _rel_inside(root, abs_path):
    try:
        rel = os.path.relpath(str(abs_path), str(root))
    except ValueError:
        return ""
    if os.path.isabs(rel) or rel.startswith(".."):
        return ""
    return rel.replace(os.sep, "/")


def _board_target(console, payload):
    _board, p = console._board_path(payload.get("board"))
    return p, ""


def _overlay_target(console, payload):
    cfg = console._proj_cfg()
    sp = console._proj_path(cfg, "state_file",
                            "未配置状态覆盖层（web_config.json 的 projects.state_file）")
    return sp, ""


def _stub_target(console, payload):
    raw = str(payload.get("dir") or "").strip()
    if not raw:
        return None
    d = Path(raw)
    if not d.is_absolute() or not d.is_dir():
        return None
    return d / "renwu_liudang.txt", ""


# 路由 → (动作类型, 目标派生函数)；目标必须在工作区内才能做 S0/S1
GATED_ROUTES = {
    "/api/task/add": ("file_write", _board_target),
    "/api/task/delete": ("file_write", _board_target),
    "/api/project/status": ("file_write", _overlay_target),
    "/api/task/status": ("file_write", _overlay_target),
    "/api/task/stub": ("file_write", _stub_target),
}

OBSERVED_ROUTES = {
    "/api/setup/save": "写 web_config.json，工作区外",
    "/api/setup/scaffold": "新建项目骨架，目标在工作区外",
    "/api/setup/task": "新项目首个任务，目标在工作区外",
    "/api/setup/pick": "本机目录选择框，不落盘",
    "/api/manual": "写 ~/.xtgl/manual.json，工作区外",
    "/api/ai/config": "写 AI 配置件，工作区外",
    "/api/ai/test": "只读探活",
    "/api/health/rules": "写 ~/.xtgl/health_rules.json，工作区外",
    "/api/health/computer": "只读采集",
    "/api/export/save": "目标在 handler 内派生，多目标",
    "/api/oss/check": "跨端只读核对",
    "/api/ai/enable": "写 AI 配置件，工作区外",
    "/api/anomaly/scan": "只读扫描",
    "/api/ai/diagnose": "只读诊断",
    "/api/detail": "目标由看板文件派生，动作前未落地",
}


def _map_action(console, path, payload):
    spec = GATED_ROUTES.get(path)
    if not spec:
        return None
    action_type, derive = spec
    try:
        got = derive(console, payload or {})
    except Exception:  # noqa: BLE001 —— 目标派生不出，交回 handler 自己报错
        return None
    if not got:
        return None
    target, content = got
    rel = _rel_inside(console.root, target)
    if not rel:
        return None      # 工作区外：不做放行判断，只记账
    return {"action_type": action_type, "target": rel, "content": content,
            "abs": str(target), "gated": True}


def _supervisor(console):
    root = Path(console.root) if console.root else None
    if root is None or not root.is_dir():
        raise RuntimeError("项目根不可用，监管无处落地")
    key = str(root)
    if key in _SINGLETONS:
        return _SINGLETONS[key]
    cfg = _read_json(CFG_PATH)
    order = _read_json(ORDER_PATH)
    from . import scope
    order["workspace"] = root.name
    scope.validate_order(order, live=scope.is_live(order))
    from .supervisor import Supervisor
    sup = Supervisor(str(root.parent), cfg, RUN_DIR, order,
                     source="community", entry="entry:web.do_POST")
    if sup.state.get("status") != "running":
        sup.begin()
    _SINGLETONS[key] = sup
    return sup


def begin_post(console, path, payload, mode):
    if mode not in ("shadow", "enforce"):
        return None
    ctx = {"mode": mode, "path": path, "payload": payload or {}, "sup": None,
           "gated": False, "blocked": False, "pre": None, "action": None,
           "before": None, "abs": "", "_locked": True}
    LOCK.acquire()
    try:
        ctx["sup"] = _supervisor(console)
    except Exception as e:  # noqa: BLE001
        ctx["init_error"] = "%s: %s" % (type(e).__name__, e)
        _release(ctx)
        if mode == "enforce":
            ctx["blocked"] = True
            ctx["body"] = {"error": "拒绝：执行中监管未就绪（%s）" % e}
        return ctx

    mapping = _map_action(console, path, payload)
    ctx["mapping"] = mapping
    if not mapping:
        ctx["why"] = OBSERVED_ROUTES.get(path, "未登记路由/目标在工作区外")
        return ctx

    try:
        action = {"action_type": mapping["action_type"],
                  "target": mapping["target"], "content": mapping.get("content", "")}
        ctx.update(gated=True, action=action, abs=mapping["abs"])
        ctx["before"] = ctx["sup"].refresh()
        pre = ctx["sup"].pre_check(action)
        ctx["pre"] = pre
        if pre["result"] == "fail" and mode == "enforce":
            rec = ctx["sup"].record(
                mapping["action_type"], "denied", pre["code"],
                {"pre": {"result": "fail", "items": pre["items"]}},
                target=mapping["target"],
                evidence={"reason": pre.get("reason", "")},
                extra={"route": path, "mode": mode, "covered": True,
                       "scope": pre.get("scope", {})})
            ctx["blocked"] = True
            ctx["body"] = {"error": "拒绝：执行中监管（%s）｜%s"
                                  % (pre["code"], pre.get("reason", "")),
                           "record": rec.get("seq")}
    except Exception as e:  # noqa: BLE001 —— 监管异常不把服务带崩
        ctx["hook_error"] = "%s: %s" % (type(e).__name__, e)
        if mode == "enforce":
            ctx["blocked"] = True
            ctx["body"] = {"error": "拒绝：执行中监管异常（%s）" % e}

    if ctx["blocked"]:
        _release(ctx)
    return ctx


def end_post(ctx, exc_info=None):
    if not ctx:
        return
    try:
        sup = ctx.get("sup")
        if sup is None:
            return
        mode = ctx["mode"]
        exc = exc_info[0] if exc_info else None
        result = "error" if exc is not None else "ok"
        code = "INTERNAL_ERROR" if exc is not None else ""
        if not ctx.get("gated"):
            sup.sync_snapshot()
            sup.record("file_write", result, code,
                       {"pre": {"result": "skip", "items": [
                           {"id": "S0.8", "name": "covered_scope", "result": "skip",
                            "detail": ctx.get("why", "")}]}},
                       target="-",
                       extra={"route": ctx["path"], "mode": mode, "covered": False})
            return

        from .ledger import sha_file
        action = ctx["action"]
        abs_p = ctx["abs"]
        expected = sha_file(abs_p) if os.path.isfile(abs_p) else ""
        post = sup.post_check(action, ctx["before"], expected)
        would = []
        if ctx["pre"]["result"] == "fail":
            would.append(ctx["pre"]["code"])
        if post["result"] == "fail":
            would.append("S1:" + post["code"])
        checks = {"pre": {"result": ctx["pre"]["result"], "items": ctx["pre"]["items"]},
                  "post": {"result": post["result"], "items": post["items"]}}
        evidence = {"would_deny": would, "diff": post["diff"],
                    "expected_sha256": expected}
        if mode == "shadow":
            sup.sync_snapshot()
            sup.record("file_write", result, code, checks,
                       target=action["target"], evidence=evidence,
                       extra={"route": ctx["path"], "mode": "shadow",
                              "covered": True, "would_deny": would})
            return

        rec = sup.record(
            "file_write",
            "interrupted" if post["result"] == "fail" else result,
            post["code"] if post["result"] == "fail" else code,
            checks, target=action["target"], evidence=evidence,
            extra={"route": ctx["path"], "mode": "enforce", "covered": True})
        sup.state["seq"] = rec["seq"]
        sup.state["last_snapshot"] = sup.current
        sup._save_state()
    finally:
        _release(ctx)
