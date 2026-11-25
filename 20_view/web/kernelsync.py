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

"""内核同步工具：让「一份内核、两个仓库」可以被机器验证，而不是靠自觉复制。

核心文件（core）：xtgl_core.py / serve.py / index.html / setup.html / favicon.png / xtgl_clean.py
一致性判据（2026-11-07 用户裁定）：
    1. 基线：community↔minimal 12 件逐字节一致，`xtgl_core.py` 仅允许「端口兜底行」
       按端不同（personal 8801／community 8802／minimal 8804）；
    2. personal 相对该基线的既有差异，逐条列入 WHITELIST：每条写明「哪些行允许不同、为什么、
       依据」，记忆层／措辞／历史数据键三类注明「用户裁定保留」；
    3. personal 专属前端 5 件已于 Q015 收口、Q007 收尾时冻结：design_tokens.json 归 W4、
       modules.json 归 W2；index.html／tutorial.html／i18n.js 的双语包装与个人端专属块按实测
       差异上限登记（DIFF_CAP，段数／删行／增行超限即判不一致）；setup.html 首启向导页
       保留登记（PEND），待 0.10 基线重建时并入上限；
    4. 除第 1–3 条列明的差异，任何字节差异都判不一致。

用法：
    python kernelsync.py --manifest            生成/更新 core_manifest.json
    python kernelsync.py --check               校验本地文件与清单一致
    python kernelsync.py --compare <另一web目录> 比对两端核心文件
    python kernelsync.py --sync-from <目录>     从另一端复制核心文件（带 .bak）
"""
import argparse
import difflib
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "core_manifest.json"
CORE_FILES = ("xtgl_core.py", "serve.py", "index.html", "setup.html",
              "tutorial.html", "kernelsync.py", "module_check.py", "modules.json",
              "snapshot.py", "i18n.js", "favicon.png", "xtgl_clean.py",
              "design_tokens.json")

# 白名单：只登记「哪些行允许不同、为什么、依据」，不按文件名整体放行。
# 比对时逐段（difflib opcode）判定：全部段落都能归到某条规则才算 WHITE，否则 DIFF。
WHITELIST = {
    "xtgl_core.py": (
        ("W1 端口兜底行", "仅 3 行：`or 8801`／`or 8802`／`or 8804` 的默认端口数字",
         "各端默认端口不同；只允许端口数字不同，同行其余部分必须逐字节一致",
         "用户 2026-11-07 裁定"),
        ("W2 记忆层", "personal 4 块共 76 行：783-842／3970-3974／4114-4118／4157-4162",
         "personal 独有 50_naoji 能力（_naoji_mod／naoji*／/api/naoji 路由／启动清扫）；"
         "community、minimal 无此能力，多出来的只能整块删除才判一致",
         "用户裁定保留"),
        ("W3 历史数据键", "6 行：`\"工程\": \"projects\"`、`关联工程`、`本次工程`、`(\"projects\",\"工程\")` 等",
         "personal 既有台账／目标数据用「工程」键，改键会读不到历史数据；"
         "community／minimal 用「项目」键",
         "用户裁定保留"),
        ("W4 措辞", "约 45 行：注释、docstring、提示语与页面文案里的「工程」↔「项目」",
         "personal 沿用「工程」，community／minimal 统一「项目」；纯文案，无逻辑差异",
         "用户裁定保留"),
        ("W5 入口文件名", "2 行：`<端名>XTGL_<Edition>_v01.py` 的前缀拼写",
         "personal 与 community／minimal 的入口前缀写法不同，引用以实物为准",
         "实物约束"),
        ("W6 客户名单", "3 行：`NON_CLIENT_NAMES=(\"架构师\",\"haness\")` ↔ `NON_CLIENT_PREFIXES=(\"执行\",)` 及 2 处判定",
         "personal 的历史执行者按人名排除；community／minimal 按「执行」前缀排除",
         "端专属口径"),
    ),
    "snapshot.py": (
        ("W2 记忆层", "personal 29 行：379-406（_naoji_mod／sec_naoji_ceng）＋424（build 注册）",
         "同 xtgl_core 的 50_naoji 能力；其余端无此段", "用户裁定保留"),
        ("W4 措辞", "3 行 docstring 中的「工程」↔「项目」",
         "纯文案，无逻辑差异", "用户裁定保留"),
    ),
    "design_tokens.json": (
        ("W4 措辞", "1 行：`_基准工程` ↔ `_基准项目` 的键名",
         "personal 沿用「工程」，community／minimal 统一「项目」；纯 token 键名，无样式差异",
         "用户裁定保留"),
    ),
    "modules.json": (
        ("W2 记忆层", "18 行：personal 独有的 naoji 模块登记（含「大脑记忆层」条目）",
         "personal 独有 50_naoji 能力对应的模块条目；community／minimal 无此能力，"
         "整块删除才判一致",
         "用户裁定保留"),
    ),
    "kernelsync.py": (
        ("W7 登记文案", "2 行（W5 条目说明）：本地 72-73 / 对端 72-73",
         "仅「W5 入口文件名」条目的说明写法与理由句不同"
         "（`BumaoXTGL_<Edition>_v01.py` 的前缀写法与理由句），"
         "比对逻辑、常量与命令行行为均无差异",
         "登记口径：WHITELIST 逐段登记（非功能性，纯文案差异）"),
    ),
}

# 已冻结的个人端专属前端：按实测差异上限登记（Q015 收口、Q007 收尾后转白名单）。
# 只比对「差异段数／删行／增行」三项，任一项超出上限即判不一致；人改前端后须重测再登记。
DIFF_CAP = {
    "index.html": (121, 422, 340),
    "tutorial.html": (15, 26, 52),
    "i18n.js": (15, 980, 603),
}

# 已冻结、尚未并入差异上限的件：比对记 PEND（不计一致也不计不一致），0.10 基线重建时并入上限。
PENDING_FREEZE = {
    "setup.html": "首启四步向导页：personal 单语、community／minimal 双语包装"
                   "（personal 206 行／对端 249 行；删 56／增 99、35 段；"
                   "personal 0 个 class=\"zh\"、对端各 28 个 zh+en span；"
                   "四步流程与校验逻辑一致，无功能性差异）",
}
RULE_FILES = ("xtgl_core.py", "snapshot.py", "kernelsync.py", "modules.json", "design_tokens.json")
PORT_RE = re.compile(r"or\s+880[124]\b")
NAOJI_MARKERS = ("naoji", "记忆层", "50_naoji")
KEY_MAP = (('"工程": "projects"', '"项目": "projects"'),
           ("关联工程", "关联项目"),
           ("本次工程", "本次项目"),
           ('("projects", "工程")', '("projects", "项目")'))
FILTER_CONST_RE = re.compile(r'NON_CLIENT_NAMES\s*=\s*\(\s*"架构师"\s*,\s*"haness"\s*\)')
FILTER_TEST_RE = re.compile(r"(\w+) in NON_CLIENT_NAMES")


def _end_name(path: Path) -> str:
    """web 目录的端名：<端>\\20_view\\web → <端>。"""
    try:
        return Path(path).resolve().parent.parent.name
    except Exception:
        return ""


def _read_lines(path: Path):
    return path.read_text(encoding="utf-8").splitlines()


def _norm_keys(s: str) -> str:
    for old, new in KEY_MAP:
        s = s.replace(old, new)
    return s


def _norm_filter(s: str) -> str:
    s = FILTER_CONST_RE.sub('NON_CLIENT_PREFIXES = ("执行",)', s)
    return FILTER_TEST_RE.sub(r"\1.startswith(NON_CLIENT_PREFIXES)", s)


def _looks_naoji(lines) -> bool:
    return bool(lines) and any(any(m in l for m in NAOJI_MARKERS) for l in lines)


def _match_rule(pa, pb):
    """给一段差异定规则名；归不了返回 None。"""
    if not pa or not pb:
        side = pa or pb
        return "W2 记忆层" if _looks_naoji(side) else None
    ja, jb = "\n".join(pa), "\n".join(pb)
    if len(pa) == len(pb) and all(PORT_RE.search(x) for x in pa + pb):
        if PORT_RE.sub("or 880X", ja) == PORT_RE.sub("or 880X", jb):
            return "W1 端口兜底行"
    if "W5 入口文件名" in ja and "W5 入口文件名" in jb:
        return "W7 登记文案"
    if _norm_keys(ja) == _norm_keys(jb):
        return "W3 历史数据键"
    if _norm_filter(ja) == _norm_filter(jb):
        return "W6 客户名单"
    if ja.replace("Bumago", "Bumao") == jb.replace("Bumago", "Bumao"):
        return "W5 入口文件名"
    if ja.replace("工程", "项目") == jb.replace("工程", "项目"):
        return "W4 措辞"
    return None


def _classify_file(a_lines, b_lines):
    """逐段分类：返回 (命中规则列表, 未归因列表)。"""
    hits, unexplained = [], []
    sm = difflib.SequenceMatcher(None, a_lines, b_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        rule = _match_rule(a_lines[i1:i2], b_lines[j1:j2])
        if rule:
            hits.append((rule, i1 + 1, i2, j1 + 1, j2))
        else:
            unexplained.append((tag, i1 + 1, i2, j1 + 1, j2))
    return hits, unexplained


def _churn(a_lines, b_lines):
    """差异段数／删行／增行：DIFF_CAP 的三项实测值。"""
    sm = difflib.SequenceMatcher(None, a_lines, b_lines, autojunk=False)
    segs = dels = adds = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        segs += 1
        dels += i2 - i1
        adds += j2 - j1
    return segs, dels, adds


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def core_version() -> str:
    src = HERE / "xtgl_core.py"
    for line in src.read_text(encoding="utf-8").splitlines():
        if line.startswith("CORE_VERSION"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "unknown"


def make_manifest():
    files = {}
    for name in CORE_FILES:
        p = HERE / name
        if not p.is_file():
            raise SystemExit("缺核心文件：%s" % name)
        files[name] = sha256(p)
    data = {
        "core_version": core_version(),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "一致性判据（用户 2026-11-07 裁定）：community↔minimal 12 件逐字节一致"
                "＋xtgl_core.py 仅端口兜底行按端不同；personal 既有差异见 kernelsync.WHITELIST "
                "逐条登记；前端已冻结（Q015 收口／Q007 收尾），个人端专属前端按实测差异上限"
                "登记（DIFF_CAP），setup.html 向导页保留登记待 0.10 基线重建并入上限。"
                "改核心后必须重新生成本清单",
        "files": files,
    }
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("已生成：%s（%d 个文件）" % (MANIFEST, len(files)))
    return data


def check():
    if not MANIFEST.is_file():
        print("缺 core_manifest.json，先跑 --manifest")
        return 1
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bad = []
    for name, digest in data["files"].items():
        p = HERE / name
        if not p.is_file():
            bad.append("%s（缺失）" % name)
        elif sha256(p) != digest:
            bad.append("%s（哈希不一致）" % name)
    if data.get("core_version") != core_version():
        bad.append("core_version 不一致：清单 %s / 代码 %s" % (data.get("core_version"), core_version()))
    if bad:
        print("FAIL：" + "；".join(bad))
        return 1
    print("PASS：%d 个核心文件与清单一致（内核 %s）" % (len(data["files"]), data.get("core_version")))
    return 0


def compare(other: Path):
    other = Path(other).resolve()
    here_end, other_end = _end_name(HERE), _end_name(other)
    print("本地：%s（%s）" % (HERE, here_end))
    print("对端：%s（%s）" % (other, other_end))
    personal_pair = "personal" in (here_end, other_end)
    bad = white = pend = 0
    for name in CORE_FILES:
        a, b = HERE / name, other / name
        if not a.is_file() or not b.is_file():
            print("  MISS  %s" % name)
            bad += 1
            continue
        if sha256(a) == sha256(b):
            print("  SAME  %s" % name)
            continue
        if name in RULE_FILES:
            hits, unexplained = _classify_file(_read_lines(a), _read_lines(b))
            if unexplained:
                print("  DIFF  %s（白名单命中 %d 段，未归因 %d 段）" % (name, len(hits), len(unexplained)))
                for tag, i1, i2, j1, j2 in unexplained[:5]:
                    print("        未归因：本地 %d-%d 行 / 对端 %d-%d 行（%s）" % (i1, i2, j1, j2, tag))
                bad += 1
                continue
            rules = sorted({h[0] for h in hits})
            print("  WHITE %s（%d 段：%s）" % (name, len(hits), "；".join(rules)))
            for rule, i1, i2, j1, j2 in hits:
                print("        %s 本地 %d-%d / 对端 %d-%d" % (rule, i1, i2, j1, j2))
            white += 1
            continue
        if name in DIFF_CAP and personal_pair:
            segs, dels, adds = _churn(_read_lines(a), _read_lines(b))
            cap = DIFF_CAP[name]
            if segs <= cap[0] and dels <= cap[1] and adds <= cap[2]:
                print("  WHITE %s（W8 差异上限：%d 段／删 %d／增 %d，登记上限 %d／%d／%d）"
                      % (name, segs, dels, adds, cap[0], cap[1], cap[2]))
                white += 1
            else:
                print("  DIFF  %s（超出差异上限：%d 段／删 %d／增 %d，上限 %d／%d／%d）"
                      % (name, segs, dels, adds, cap[0], cap[1], cap[2]))
                bad += 1
            continue
        if name in PENDING_FREEZE and personal_pair:
            print("  PEND  %s（%s）" % (name, PENDING_FREEZE[name]))
            pend += 1
            continue
        print("  DIFF  %s" % name)
        bad += 1
    if bad:
        print("结论：%d 个文件不一致%s" % (bad, "；另有 %d 件保留登记待并入上限" % pend if pend else ""))
        return 1
    if pend:
        print("结论：核心一致（%d 件按白名单放行），%d 件保留登记待并入上限（不计一致也不计不一致）"
              % (white, pend))
        return 2
    print("结论：两端核心一致%s" % ("（%d 件按白名单放行）" % white if white else ""))
    return 0


def sync_from(other: Path):
    other = Path(other).resolve()
    if not other.is_dir():
        raise SystemExit("目录不存在：%s" % other)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for name in CORE_FILES:
        src, dst = other / name, HERE / name
        if not src.is_file():
            print("跳过（对端没有）：%s" % name)
            continue
        if dst.is_file() and sha256(src) == sha256(dst):
            print("已一致：%s" % name)
            continue
        if dst.is_file():
            shutil.copy2(dst, dst.with_name(dst.name + "." + stamp + ".bak"))
        shutil.copy2(src, dst)
        print("已覆盖：%s（旧文件留 .bak）" % name)
    make_manifest()
    return check()


def main(argv=None):
    ap = argparse.ArgumentParser(description="XTGL 内核一致性工具")
    ap.add_argument("--manifest", action="store_true", help="生成/更新清单")
    ap.add_argument("--check", action="store_true", help="校验清单")
    ap.add_argument("--compare", metavar="DIR", help="与另一 web 目录比对")
    ap.add_argument("--sync-from", metavar="DIR", help="从另一 web 目录同步")
    args = ap.parse_args(argv)
    if args.manifest:
        make_manifest()
        return 0
    if args.compare:
        return compare(Path(args.compare))
    if args.sync_from:
        return sync_from(Path(args.sync_from))
    if args.check:
        return check()
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
