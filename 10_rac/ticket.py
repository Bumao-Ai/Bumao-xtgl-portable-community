# -*- coding: utf-8 -*-
# Copyright 2026 Bumao
#
# Licensed under the Apache License, Version 2.0.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

"""ticket.py —— 绿票账本（采集侧，community 端）

一张票＝一次真实 check 运行，不是一句「已通过」：
  at 写入时刻／rc 实跑返回码／conclusion 输出末行（[结论] 行）／out 输出文件及其 sha256／argv／pid。

票面四外键与执行中监管（runtime_guard）动作账同名字段对齐：
  run_id＝本次运行；op_id＝一次入口调用（环境变量 BUMO_OP_ID 下传，子进程继承）；
  rule_id＝本次判据范围（整包 "*"，单闸/单规则写具体编号）；
  error_code＝仅当退出码能唯一坐实时写（rc=3→KERNEL_INTERNAL_ERROR），否则留空。

与其他端的差别（有意为之）：
  本端只有采集侧：check 跑完由 wrapper 调 issue() 开票；没有 require()／消费账本，
  因为本端没有「治理件写前领票」的写入闸（那道闸在 personal 端）。
  票本 schema 与 personal 相同（lvpiao/2）：同名字段、同一条哈希链口径，
  三端可用同一套 verify 口径核链。

身份与链：
  schema＝lvpiao/2；首行是固定种子的 genesis 锚点行；每票 prev＝上一条原始行 sha256，
  整链 `ticket.py verify` 一条命令验完。票只能由一次真实运行产生，无手工补票入口。
"""
import hashlib
import io
import json
import os
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
PARAM = os.path.join(HERE, "lvpiao_canshu.json")
SCHEMA = "lvpiao/2"

OP_ENV = "BUMO_OP_ID"
RUN_ENV = "BUMO_RUN_ID"


def new_run_id():
    """单轮唯一标识；只做关联，不承载语义。"""
    return str(uuid.uuid4())


def current_run_id():
    """同一进程链共用同一个 run_id；外部没给就现开一个并写入环境供子进程继承。"""
    rid = os.environ.get(RUN_ENV) or ""
    if not rid:
        rid = new_run_id()
        os.environ[RUN_ENV] = rid
    return rid


def current_op_id():
    """一次入口调用＝一个 op_id；父进程经环境变量下传，子进程继承同一值。"""
    op = os.environ.get(OP_ENV) or ""
    if not op:
        op = "op-%s-%d-%s" % (time.strftime("%Y%m%dT%H%M%S"), os.getpid(),
                              uuid.uuid4().hex[:6])
        os.environ[OP_ENV] = op
    return op


def error_code_for_rc(rc):
    """票面错误码只记退出码能唯一坐实的一类：3＝内核自身异常；其余留空。"""
    return "KERNEL_INTERNAL_ERROR" if int(rc) == 3 else ""


def _param(name):
    if not os.path.isfile(PARAM):
        raise SystemExit("[绿票] 参数件缺失：%s" % PARAM)
    with io.open(PARAM, encoding="utf-8") as f:
        c = json.load(f)
    if name not in c:
        raise SystemExit("[绿票] 参数件无该键：%s（不写死进代码）" % name)
    return c[name]


def _at(name):
    return os.path.join(HERE, _param(name))


def _ledger_real():
    return _at("ledger")


def _ledger_rtest():
    return _at("rtest_ledger")


def _legacy():
    return _at("legacy_archive")


def _route(ledger=None, source=None):
    """记账层选账本：反向测试须显式声明 AOS_CHECK_LEDGER=rtest，真账只收未声明或 real。"""
    mode = (os.environ.get("AOS_CHECK_LEDGER") or "").strip().lower()
    if "AOS_CHECK_NO_LOG" in os.environ and mode != "rtest":
        raise SystemExit(
            "[记账拒写] AOS_CHECK_NO_LOG 已废（内核不认它，开着也只是静默丢票）。"
            "反向测试须显式声明 AOS_CHECK_LEDGER=rtest 才跑。")
    if ledger:
        p, src = ledger, (source or "manual")
    elif mode == "rtest":
        p, src = _ledger_rtest(), "rtest"
    elif mode in ("", "real"):
        p, src = _ledger_real(), (source or os.environ.get("AOS_CHECK_SOURCE") or "manual")
    else:
        raise SystemExit("[记账拒写] AOS_CHECK_LEDGER 只认 real／rtest，收到 %r" % mode)
    if src not in ("manual", "auto", "rtest"):
        raise SystemExit("[记账拒写] source 只认 manual／auto／rtest，收到 %r" % src)
    return p, src


def _sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _summarize(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    npass = sum(1 for l in lines if l.startswith("PASS ") or l.startswith("[PASS]"))
    nfail = sum(1 for l in lines if l.startswith("FAIL ") or l.startswith("[FAIL]"))
    tail = lines[-1][:120] if lines else ""
    return "%d 行｜PASS %d／FAIL %d｜末行 %s" % (len(lines), npass, nfail, tail)


def _raw_lines(p):
    if not os.path.isfile(p):
        return []
    out = []
    with io.open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if ln.strip():
                out.append(ln)
    return out


def _anchor(p):
    """账本为空时落固定种子起点行；返回最后一行原文（下一条票的 prev 就是它）。"""
    lines = _raw_lines(p)
    if lines:
        return lines[-1]
    gen = {"schema": SCHEMA, "kind": "genesis", "seed": _param("chain_seed"),
           "at": time.strftime("%Y-%m-%d %H:%M:%S"), "ts": time.time(),
           "legacy": os.path.basename(_legacy()),
           "boundary": _param("legacy_boundary"),
           "reason": _param("legacy_reason")}
    line = json.dumps(gen, ensure_ascii=False)
    with io.open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")
    return line


class _LedgerLock(object):
    """追加独占锁：O_EXCL 建锁，取 prev 与追加在同一把锁内，避免并发分叉。"""

    def __init__(self, target, wait=2.0):
        self.path = target + ".lock"
        self.wait = wait
        self.fh = None

    def __enter__(self):
        end = time.time() + self.wait
        while True:
            try:
                self.fh = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > 5:
                        os.remove(self.path)
                        continue
                except OSError:
                    pass
                if time.time() > end:
                    raise RuntimeError("绿票账本被占用：%s" % self.path)
                time.sleep(0.02)

    def __exit__(self, *exc):
        if self.fh is not None:
            os.close(self.fh)
            self.fh = None
        try:
            os.remove(self.path)
        except OSError:
            pass
        return False


def issue(rc, conclusion, out_path="", argv=None, console="", ledger=None, source=None,
          origin="", note="", run_id="", op_id="", rule_id="", error_code=""):
    """一次 check 跑完就开一张票。只追加，不改旧票（票面字段与 personal 同 schema）。"""
    p, src = _route(ledger, source)
    prev = _anchor(p)
    out_p = os.path.abspath(out_path) if out_path else ""
    console = console or ""
    rec = {"schema": SCHEMA, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "ts": time.time(),
           "rc": int(rc), "source": src, "cmd": " ".join(argv or []),
           "run_id": run_id or current_run_id(),
           "op_id": op_id or current_op_id(),
           "rule_id": rule_id or "*",
           "error_code": (error_code if error_code else error_code_for_rc(rc)),
           "conclusion": (conclusion or "").strip(),
           "out": out_p or "-",
           "out_sha256": (_sha_file(out_path) if (out_path and os.path.isfile(out_path))
                          else (_digest(console) if console else "")),
           "out_summary": _summarize(console),
           "argv": list(argv or []), "pid": os.getpid(),
           "prev": ""}
    if origin:
        rec["origin"] = origin
    if note:
        rec["note"] = note
    with _LedgerLock(p):
        rec["prev"] = _digest(_anchor(p))
        with io.open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _tickets_in(p):
    out = []
    for ln in _raw_lines(p):
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if rec.get("kind") == "genesis":
            continue
        out.append(rec)
    return out


def tickets():
    return _tickets_in(_ledger_real())


def raw_tickets():
    """[(票, tid)]；tid＝账本原始行 sha256 前 16 位，现算不落库。"""
    out = []
    for ln in _raw_lines(_ledger_real()):
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if rec.get("kind") == "genesis":
            continue
        out.append((rec, hashlib.sha256(ln.encode("utf-8")).hexdigest()[:16]))
    return out


def last():
    t = tickets()
    return t[-1] if t else None


def verify(ledger=None):
    """一条命令验完整条哈希链：链长／断点位置／真票数。"""
    p = os.path.abspath(ledger) if ledger else _ledger_real()
    lines = _raw_lines(p)
    seed = str(_param("chain_seed"))
    n_ticket, n_real, brk = 0, 0, ""
    prev = seed
    for i, ln in enumerate(lines, 1):
        try:
            rec = json.loads(ln)
        except ValueError:
            brk = "第 %d 行不是合法 JSON（被截断或手写）" % i
            break
        if rec.get("kind") == "genesis":
            if rec.get("seed") != seed:
                brk = "第 %d 行起点种子对不上参数件（seed=%s）" % (i, rec.get("seed"))
                break
        elif rec.get("prev") != prev:
            brk = "第 %d 行 prev 不符（上一行被改／插入／删除）" % i
            break
        else:
            n_ticket += 1
            if rec.get("rc") == 0 and rec.get("source") != "rtest":
                n_real += 1
        prev = _digest(ln)
    return {"path": p, "lines": len(lines), "chain": n_ticket, "real": n_real, "break": brk}


def status():
    ts = tickets()
    lines = ["账本：%s（%d 张票，其中绿票 %d 张）"
             % (_ledger_real(), len(ts), len([t for t in ts if t.get("rc") == 0])),
             "测试账本：%s（%d 张票，source=rtest）"
             % (_ledger_rtest(), len(_tickets_in(_ledger_rtest())))]
    t = last()
    lines.append("上一条：%s" % ("%s rc=%s ｜ %s"
                                 % (t.get("at"), t.get("rc"), t.get("conclusion", "")[:70])
                                 if t else "无"))
    lines.append("本端口径：只采集（check 实跑即开票）；写入闸不在此端。")
    return "\n".join(lines)


def main(argv):
    a = argv[1:]
    if not a:
        print(__doc__)
        return 2
    if a[0] == "--status":
        print(status())
        return 0
    if a[0] == "verify":
        target = None
        if "--ledger" in a and len(a) > a.index("--ledger") + 1:
            v = a[a.index("--ledger") + 1]
            target = _ledger_rtest() if v == "rtest" else (_ledger_real() if v == "real" else v)
        r = verify(target)
        print("[链验] 账本=%s｜链长=%d｜真票数=%d｜断点=%s"
              % (os.path.basename(r["path"]), r["chain"], r["real"],
                 r["break"] or "无（整链完整）"))
        return 0 if not r["break"] else 1
    print("用法：ticket.py --status | verify [--ledger real|rtest]")
    return 2


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main(sys.argv))
