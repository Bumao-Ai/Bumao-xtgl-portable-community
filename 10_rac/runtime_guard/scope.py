# -*- coding: utf-8 -*-
"""scope.py —— Intent-order parsing and target-set judgment (the S0 checkpoint criterion source).

An intent order (intent/1) is an "approved target set", not a free-text note:
  approved_roots  directories that may be written (relative to workspace)
  approved_files  concrete files that may be written (relative to workspace)
  denied_zones    path segments rejected regardless of approved roots
  allowed_actions allowed action types
  expires_at      expiry time (empty = this order does not expire, but a human still holds it)
  approved_by     approver; empty = unapproved order, rejected outright
  ticket_tid      bound green-ticket tid (may be empty; forbidden when force_ticket=true)

Judgment has exactly three outcomes: in_scope / out_of_scope / malformed. There is no
"roughly in scope".
"""
import io
import json
import ntpath
import os
import posixpath
import re
import time

from . import reasons


class ScopeError(ValueError):
    """The intent order is invalid or the target path shape is illegal. code comes from
    schema/reason_codes.json and can go straight onto the ticket."""

    def __init__(self, message, code="TARGET_FORM_INVALID"):
        self.code = code
        super().__init__(message)


RE_DRIVE = re.compile(r"^[A-Za-z]:")
RE_TID = re.compile(r"^[0-9a-f]{16}$")
RE_QUOTE = re.compile(r"「[^」]{2,}」|“[^”]{2,}”|\"[^\"]{2,}\"|'[^']{2,}'")
ACTION_TYPES = ("file_read", "file_write", "cmd_exec", "batch_exec")
PROXY_MARK = "PROXY-SIGNED"
MAX_INTENT_SPAN = 24 * 3600          # live-order validity cap: 24h; never auto-renew past it


def is_live(order=None, live=None):
    """Live judgment (fail-closed): explicit parameter wins; env unset/empty/unknown = live.

    Only an explicit BUMO_JIANCHA_ENV=sandbox relaxes this; forgetting the env var must not
    disable "live required + 24h cap". A demo_only=true single intent may carry an empty
    expires_at even under live.
    """
    if live is not None:
        return bool(live)
    return (os.environ.get("BUMO_JIANCHA_ENV") or "").strip().lower() != "sandbox"


def is_proxy_sign(order):
    return PROXY_MARK in str((order or {}).get("note") or "")


def weak_authorization(order):
    """Weak-authorization detection: a proxy-signed note counts as weak authorization
    and must not be tallied as an independent approval."""
    proxy = is_proxy_sign(order)
    return {
        "mode": "proxy_weak" if proxy else "independent",
        "weak_authorization": proxy,
        "counts_as_independent_approval": not proxy,
        "approved_by": str((order or {}).get("approved_by") or ""),
        "note": str((order or {}).get("note") or ""),
    }


def export_intent(order):
    """Export summary: weak authorization must be visible at a glance so it cannot be
    tallied as an independent approval."""
    return {
        "schema": "intent_export/1",
        "order_id": str((order or {}).get("order_id") or ""),
        "approved_by": str((order or {}).get("approved_by") or ""),
        "approved_at": str((order or {}).get("approved_at") or ""),
        "expires_at": str((order or {}).get("expires_at") or ""),
        "authorization": weak_authorization(order),
    }


def load_order(path, live=None):
    if not os.path.isfile(path):
        raise ScopeError("意图单不存在：%s" % path, "NO_ORDER")
    try:
        with io.open(path, encoding="utf-8") as f:
            order = json.load(f)
    except (ValueError, OSError) as e:
        raise ScopeError("意图单无法解析：%s" % e, "ORDER_UNPARSABLE")
    validate_order(order, live=live)
    return order


def order_problems(order, now=None, live=None):
    """List every problem of the intent order (does not raise). Each item carries
    code/field/detail; code can go straight onto the ticket."""
    live = is_live(order, live)
    probs = []

    def add(code, field, detail):
        reasons.assert_known(code)
        probs.append({"code": code, "field": field, "detail": detail})

    if not isinstance(order, dict):
        add("ORDER_NOT_OBJECT", "$", "意图单不是对象")
        return probs
    if order.get("schema") != "intent/1":
        add("INVALID_SCHEMA", "schema", "意图单 schema 须为 intent/1，收到 %r" % order.get("schema"))
    for k in ("order_id", "workspace", "approved_at"):
        if not str(order.get(k) or "").strip():
            add("ORDER_FIELD_MISSING", k, "意图单缺字段或为空：%s" % k)
    if not str(order.get("approved_by") or "").strip():
        add("NO_APPROVER", "approved_by", "未批准单：approved_by 为空，拒绝执行")
    note = str(order.get("note") or "")
    if is_proxy_sign(order) and not RE_QUOTE.search(note):
        add("PROXY_QUOTE_MISSING", "note",
            "代理代签必须在 note 含「%s」并附用户原话（引号内至少 2 字）" % PROXY_MARK)
    roots = order.get("approved_roots") or []
    files = order.get("approved_files") or []
    if not isinstance(roots, list) or not isinstance(files, list):
        add("INVALID_APPROVED_PATH", "approved_roots/approved_files", "批准集合须为列表")
    elif not roots and not files:
        add("EMPTY_APPROVAL_SET", "approved_roots+approved_files",
            "批准的目标集合为空：既不批目录也不批文件，等于没批")
    for rel in (roots if isinstance(roots, list) else []) + (files if isinstance(files, list) else []):
        try:
            normalize_rel(rel)                      # malformed shape raises at load time
        except ScopeError as e:
            add("INVALID_APPROVED_PATH", "approved_roots/approved_files", "%s（%r）" % (e, rel))
    ws = str(order.get("workspace") or "").strip()
    if ws:
        try:
            normalize_rel(ws)
        except ScopeError as e:
            add("INVALID_WORKSPACE", "workspace", str(e))
    acts = order.get("allowed_actions")
    if not isinstance(acts, list) or not acts:
        add("NO_ALLOWED_ACTIONS", "allowed_actions", "allowed_actions 为空：未声明可用动作类型")
    else:
        for a in acts:
            if a not in ACTION_TYPES:
                add("INVALID_ACTION_TYPE", "allowed_actions", "未知动作类型：%r" % a)
    e = str(order.get("expires_at") or "").strip()
    if not e:
        if live and not bool(order.get("demo_only")):
            add("LIVE_EXPIRES_REQUIRED", "expires_at",
                "live 单据必须写 expires_at（空值只允许沙盒/demo_only）")
    else:
        t1 = None
        try:
            t1 = time.mktime(time.strptime(e, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            add("INVALID_EXPIRES_AT", "expires_at",
                "expires_at 格式须为 YYYY-MM-DD HH:MM:SS：%s" % e)
        if t1 is not None:
            pa = str(order.get("approved_at") or "").strip()
            try:
                t0 = time.mktime(time.strptime(pa, "%Y-%m-%d %H:%M:%S"))
                span = t1 - t0
                if span > MAX_INTENT_SPAN:
                    add("INVALID_EXPIRES_AT", "expires_at",
                        "有效期 %.1f 小时，超过上限 24 小时；逾时须重新签发，不得自动续签" % (span / 3600.0))
                elif span <= 0:
                    add("INVALID_EXPIRES_AT", "expires_at", "expires_at 须晚于 approved_at")
            except ValueError:
                pass
    tid = str(order.get("ticket_tid") or "").strip()
    if tid and not RE_TID.match(tid):
        add("INVALID_TICKET_TID", "ticket_tid", "ticket_tid 须为 16 位小写十六进制：%s" % tid)
    return probs


def validate_order(order, now=None, live=None):
    probs = order_problems(order, now=now, live=live)
    if probs:
        p = probs[0]
        raise ScopeError(p["detail"], p["code"])
    return True



def normalize_rel(rel):
    """Normalize a relative path. Absolute paths, drive letters, .. segments and NUL are
    all rejected as malformed (no parsing ambiguity left)."""
    s = str(rel or "").strip().replace("\\", "/")
    if not s:
        raise ScopeError("目标路径为空")
    if "\0" in s:
        raise ScopeError("目标路径含 NUL")
    if RE_DRIVE.match(s) or s.startswith("/") or s.startswith("//"):
        raise ScopeError("目标路径不得为绝对路径或带盘符：%s" % rel)
    raw_parts = s.split("/")
    if any(p == ".." for p in raw_parts):
        raise ScopeError("目标路径不得含 .. 段：%s" % rel)
    s = posixpath.normpath(s)
    if s in ("", ".") or s.startswith("../"):
        raise ScopeError("目标路径归一化后越出根：%s" % rel)
    return s


def under(rel, root):
    """Whether rel sits under root (compared by path segment; prevents approved vs
    approved_evil prefix confusion)."""
    r = normalize_rel(rel)
    b = normalize_rel(root)
    return r == b or r.startswith(b + "/")


def denied(rel, zones):
    r = normalize_rel(rel)
    for z in zones or []:
        try:
            z = normalize_rel(z)
        except ScopeError:
            continue
        if under(r, z):
            return z
    return ""


def in_scope(rel, order):
    """Return (decision, reason, matched). decision: in_scope / out_of_scope."""
    try:
        r = normalize_rel(rel)
    except ScopeError as e:
        return "out_of_scope", str(e), ""
    z = denied(r, order.get("denied_zones") or [])
    if z:
        return "out_of_scope", "命中拒绝区 denied_zones=%s" % z, ""
    for root in order.get("approved_roots") or []:
        if under(r, root):
            return "in_scope", "落在批准目录 %s" % root, root
    for f in order.get("approved_files") or []:
        if r == normalize_rel(f):
            return "in_scope", "命中批准文件 %s" % f, f
    return "out_of_scope", "不在批准目录/文件集合内", ""


def expires_at(order):
    return str(order.get("expires_at") or "").strip()


def expired(order, now=None):
    e = expires_at(order)
    if not e:
        return False
    now = now or time.time()
    try:
        ts = time.mktime(time.strptime(e, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        raise ScopeError("expires_at 格式须为 YYYY-MM-DD HH:MM:SS：%s" % e, "INVALID_EXPIRES_AT")
    return now > ts


def workspace_abs(lab_root, order):
    """Resolve the order's workspace relative to this directory; after resolution it must
    still stay under this directory."""
    rel = normalize_rel(order["workspace"])
    base = os.path.abspath(lab_root)
    full = os.path.abspath(os.path.join(base, rel))
    try:
        inside = os.path.commonpath([base, full]) == base
    except ValueError:
        inside = False
    if not inside:
        raise ScopeError("workspace 越出沙盒根：%s" % order["workspace"], "WORKSPACE_OUTSIDE_ROOT")
    return full


def target_abs(workspace, rel):
    """Target absolute path. Even after shape validation, commonpath acts as a backstop
    (blocks symlink-style cross-root escapes)."""
    r = normalize_rel(rel)
    base = os.path.abspath(workspace)
    full = os.path.abspath(os.path.join(base, r.replace("/", os.sep)))
    try:
        if os.path.commonpath([base, full]) != base:
            raise ScopeError("目标路径实际解析越出 workspace：%s" % rel, "TARGET_OUTSIDE_WORKSPACE")
    except ValueError:
        raise ScopeError("目标路径盘符不同，越出 workspace：%s" % rel, "TARGET_OUTSIDE_WORKSPACE")
    return full


def rel_of(workspace, abs_path):
    return ntpath.normpath(os.path.relpath(abs_path, workspace)).replace("\\", "/")
