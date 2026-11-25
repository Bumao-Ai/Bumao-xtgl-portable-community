# SPDX-License-Identifier: Apache-2.0
"""审批前置轻量化（S10）：一条命令补当日审批行，替代手工拼审批册。

用法：
    python 10_rac/approval.py qianzhi <文件>... [--why 事由] [--time 改动时间]
例：
    python 10_rac/approval.py qianzhi 20_view/web/index.html --why "前端收口"
"""

import io
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_root(p):
    # 向上找本端包根（以 00_meta 目录为标记）；找不到返回空串
    q = p
    while q:
        if os.path.isdir(os.path.join(q, "00_meta")):
            return q
        n = os.path.dirname(q)
        if n == q:
            break
        q = n
    return ""


ROOT = _find_root(HERE)
LEDGER = os.path.join(ROOT, "30_taizhang", "qiangzhi_shenpi.txt")
_ENTRY = re.compile(r"【第\s*(\d+)\s*号】")


def _next_no(text):
    ns = [int(x) for x in _ENTRY.findall(text)]
    return (max(ns) + 1) if ns else 1


def _resolve(p):
    for c in (p, os.path.join(ROOT, p)):
        if os.path.isfile(c):
            return os.path.normpath(c)
    return ""


def main(argv):
    if len(argv) < 3 or argv[1] != "qianzhi":
        print("用法：approval.py qianzhi <文件>... [--why 事由] [--time 改动时间]")
        return 2
    files, why, when = [], "核心件改动", time.strftime("%Y-%m-%d %H:%M:%S")
    i = 2
    while i < len(argv):
        a = argv[i]
        if a == "--why" and i + 1 < len(argv):
            why = argv[i + 1]
            i += 2
            continue
        if a == "--time" and i + 1 < len(argv):
            when = argv[i + 1]
            i += 2
            continue
        files.append(a)
        i += 1
    if not files:
        print("缺件：未给任何文件")
        return 1
    miss = [f for f in files if not _resolve(f)]
    if miss:
        print("缺件：%s（未找到实物，拒绝登记）" % "、".join(miss))
        return 1
    names = [os.path.basename(_resolve(f)) for f in files]
    txt = io.open(LEDGER, encoding="utf-8-sig").read()
    n = _next_no(txt)
    now = time.strftime("%Y-%m-%d")
    entry = (
        "【第 %d 号】%s｜%s（一条命令登记）\n"
        "范围：%s\n"
        "改动时间：%s\n"
        "授权来源：用户授权（见审批册登记）\n"
        "签署：<待签>（本命令不代签，谁签写谁）\n"
        "说明：模板见 10_rac/shenpi_moban.txt；本行为事前审批。\n\n"
    ) % (n, now, why, "、".join(names), when)
    t0 = time.time()
    with io.open(LEDGER, "a", encoding="utf-8") as f:
        f.write(entry)
    dt = time.time() - t0
    print("已写入第 %d 号｜文件 %d 件｜审批行写入耗时 %.3f 秒" % (n, len(names), dt))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
