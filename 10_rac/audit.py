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

"""audit.py —— 执行后审计：给定 op_id，一条命令导出完整链路。

取数只读两处既有凭证，不按规则推演、不给旧记录补字段：
  ① 票本 check_lvpiao.jsonl（lvpiao/2，四键同名字段）；
  ② 执行中监管动作账 runtime_guard/jiancha_run/**/actions.jsonl（act/1，只读）。

四键口径：op_id／run_id／rule_id／error_code；缺值标「缺失」，不留空。

用法：
    python audit.py <op_id>   # 导出该操作的完整链路
    python audit.py --keys    # 核对票面四键在本端票上的出现情况
    python audit.py --last    # 用最近一张票的 op_id 导出
退出码：0＝动作行与票证都命中；1＝有缺环（缺环已逐条列出）。
"""
import hashlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HX = os.path.dirname(HERE)
ROOT = os.path.dirname(HX)
MISSING = "缺失"
KEYS = ("run_id", "op_id", "rule_id", "error_code")

PARAM = os.path.join(HERE, "lvpiao_canshu.json")
JRUN = os.path.join(HERE, "runtime_guard", "jiancha_run")


def _param(name):
    with io.open(PARAM, encoding="utf-8") as f:
        return json.load(f)[name]


def _ledger():
    return os.path.join(HERE, _param("ledger"))


def _legacy():
    return os.path.join(HERE, _param("legacy_archive"))


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


def _tickets():
    """[(票, tid)]：tid＝账本原始行 sha256 前 16 位，现算不落库。"""
    out = []
    for p in (_ledger(), _legacy()):
        for ln in _raw_lines(p):
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            if rec.get("kind") == "genesis":
                continue
            out.append((rec, hashlib.sha256(ln.encode("utf-8")).hexdigest()[:16]))
    return out


def _tickets_for(op_id):
    return [t for t, _tid in _tickets() if str(t.get("op_id") or "") == op_id]


def _ticket_by_tid(tid):
    for t, i in _tickets():
        if i == tid:
            return t
    return None


def _jiancha_rows(op_id):
    """[(运行目录, 动作行)]；运行目录本身或其下一层子目录里有 actions.jsonl 都认。"""
    found = []
    if not os.path.isdir(JRUN):
        return found
    cands = [JRUN]
    try:
        cands += [os.path.join(JRUN, n) for n in sorted(os.listdir(JRUN))]
    except OSError:
        pass
    for d in cands:
        p = os.path.join(d, "actions.jsonl")
        if not os.path.isfile(p):
            continue
        for ln in _raw_lines(p):
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            if rec.get("kind") == "genesis":
                continue
            if str(rec.get("op_id") or "") == op_id:
                found.append((d, rec))
    found.sort(key=lambda x: (str(x[1].get("at") or ""), x[1].get("seq") or 0))
    return found


def _bundle(run_dir):
    try:
        with io.open(os.path.join(run_dir, "state.json"), encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, IOError, ValueError):
        return ""
    return str((st.get("halt") or {}).get("bundle") or "").strip()


def _rel(p):
    try:
        return os.path.relpath(p, ROOT).replace(os.sep, "/")
    except ValueError:
        return p


def _rid(v):
    if not v or v == MISSING:
        return MISSING
    segs = []
    for s in str(v).split("，"):
        if "→" in s:
            a, b = s.split("→", 1)
            segs.append("%s（条款 %s）" % (b, a))
        elif s == "*":
            segs.append("*（票面整包判据范围）")
        else:
            segs.append(s)
    return "／".join(segs)


def _ec(t):
    v = str(t.get("error_code") or "").strip()
    if v:
        return "%s（rc=%s 坐实）" % (v, t.get("rc"))
    return "缺失（票面为空：rc=%s≠3，按票面口径不记错误码）" % t.get("rc")


def audit_keys():
    """验收一：票面四键在实际票上出现没有——只数现存票面字段，不推断。"""
    ts = [t for t, _i in _tickets()]
    if not ts:
        print("[票面四键] 缺失（真账 %s 无票）" % os.path.basename(_ledger()))
        return 1
    n = len(ts)
    print("[票面四键] 真账票数 %d 张（%s → %s）"
          % (n, ts[0].get("at", "")[:10], ts[-1].get("at", "")[:10]))
    for k in KEYS:
        has = [t for t in ts if k in t]
        non = [t for t in has if str(t.get(k) or "").strip()]
        note = "（error_code 仅 rc=3 有值，其余按口径为空）" if k == "error_code" else ""
        print("  %-10s 字段在场 %d/%d，非空 %d%s" % (k, len(has), n, len(non), note))
    full = [t for t in ts if all(k in t for k in KEYS)]
    print("  四键字段齐全：%d/%d 张" % (len(full), n))
    print("  最近一张原始票面（真账原样）：")
    print(json.dumps(ts[-1], ensure_ascii=False))
    return 0


def audit(op_id):
    rows = _jiancha_rows(op_id)
    ticks = _tickets_for(op_id)
    print("=" * 72)
    print("[执行后审计] op_id = %s" % op_id)
    print("证据来源：监管动作账 %s；票本 %s（含归档）"
          % (_rel(JRUN), os.path.basename(_ledger())))
    print("四键口径：op_id／run_id／rule_id／error_code；缺值标「缺失」，不按规则补。")

    print("\n一、执行中监管动作（%d 条）" % len(rows))
    if not rows:
        print("  缺失（该 op_id 在监管动作账无行：这次操作没走监管入口，或监管未挂载）")
    for i, (rd, r) in enumerate(rows, 1):
        print("  %d) %s  seq=%s  %s／%s" % (i, r.get("at"), r.get("seq"),
                                           r.get("tool") or r.get("action_type"),
                                           r.get("action_type")))
        print("     目标：%s" % (r.get("target") or MISSING))
        print("     结果：%s%s" % (r.get("result") or MISSING,
                                 ("（%s：%s）" % (r.get("error_code"), r.get("error_text"))
                                  if r.get("error_code") else "")))
        print("     run_id：%s；intent_id：%s；入口：%s"
              % (r.get("run_id") or MISSING, r.get("intent_id") or MISSING,
                 r.get("entry") or MISSING))
        ck = r.get("checks") or {}
        if ck:
            print("     检查：%s" % "／".join(
                "%s=%s" % (k, (v or {}).get("result", MISSING)) for k, v in ck.items()))
        print("     运行目录：%s" % _rel(rd))
        b = _bundle(rd)
        if b:
            print("     证据束：%s" % b)
        att = r.get("ticket") or {}
        if att.get("tid"):
            face = _ticket_by_tid(str(att.get("tid")))
            print("     随附票面：tid=%s（state=%s）%s"
                  % (att.get("tid"), att.get("state") or MISSING,
                     "，已按 tid 回查票本" if face else "，票本里查不到该 tid"))
            if face:
                print("       四键：run_id=%s | op_id=%s | rule_id=%s | error_code=%s"
                      % (face.get("run_id") or MISSING, face.get("op_id") or MISSING,
                         _rid(face.get("rule_id")), _ec(face)))

    print("\n二、票证（%d 张）" % len(ticks))
    if not ticks:
        print("  缺失（该 op_id 无 check 票：这次操作没跑过判据，或票未落此 op_id）")
    for i, t in enumerate(ticks, 1):
        print("  %d) %s  rc=%s  %s" % (i, t.get("at"), t.get("rc"),
                                      t.get("conclusion") or MISSING))
        print("     四键：run_id=%s | op_id=%s | rule_id=%s | error_code=%s"
              % (t.get("run_id") or MISSING, t.get("op_id") or MISSING,
                 _rid(t.get("rule_id")), _ec(t)))
        print("     证据 sha256：%s；cmd=%s"
              % ((t.get("out_sha256") or "")[:16], t.get("cmd", "")))

    print("\n三、四键核对")
    print("  op_id      ：有（查询键；监管行 %d 条／票 %d 张命中）" % (len(rows), len(ticks)))
    runs = sorted({r.get("run_id") for _d, r in rows if r.get("run_id")}
                  | {t.get("run_id") for t in ticks if t.get("run_id")})
    print("  run_id     ：%s" % ("／".join(runs) if runs else MISSING))
    rids = sorted({t.get("rule_id") for t in ticks if t.get("rule_id")})
    print("  rule_id    ：%s" % ("／".join(_rid(i) for i in rids) if rids else MISSING))
    if ticks:
        print("  error_code ：%s" % "；".join(_ec(t) for t in ticks))
    else:
        print("  error_code ：%s（无票即无错误码来源）" % MISSING)

    print("\n四、缺失环")
    miss = []
    if not rows:
        miss.append("动作行：缺失（该 op_id 无任何监管动作行）")
    if not ticks:
        miss.append("票证：缺失（该 op_id 无 check 票）")
    if rows:
        miss.append("rule_id：监管动作行 %d 条本身不带该字段（act/1 口径；"
                    "判据依据随附票面或检查项 id 表达）" % len(rows))
    nec = [t for t in ticks if not str(t.get("error_code") or "").strip()]
    if nec:
        miss.append("error_code：缺失（%d 张票面为空：rc≠3，按口径不记，非漏记）" % len(nec))
    if miss:
        for m in miss:
            print("  - " + m)
    else:
        print("  无（四环齐全）")
    print("=" * 72)
    return 0 if (rows and ticks) else 1


def main(argv):
    a = argv[1:]
    if not a:
        print(__doc__)
        return 2
    if a[0] == "--keys":
        return audit_keys()
    if a[0] == "--last":
        ts = [t for t, _i in _tickets()]
        if not ts:
            print("缺失（真账无票，先跑一次 check）")
            return 1
        return audit(str(ts[-1].get("op_id") or ""))
    return audit(a[0])


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main(sys.argv))
