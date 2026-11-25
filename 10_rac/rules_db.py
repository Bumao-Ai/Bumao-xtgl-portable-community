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

"""rules_db.py —— 真身装载与结构校验（Bumao XTGL Community）
定位（1.2）：zhunze\\z*.json 是唯一真身。本模块只读真身、只做校验与派生索引，
不定义规则、不持有第二份正文。
去私人化要求：所有路径由 __file__ 运行时溯源，不写字面绝对路径，产品可整体拷贝。
输出：rules.json（派生索引，可随时重建；真身一变它就该重建）
"""
import os, io, re, sys, json, hashlib, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
HX = os.path.dirname(HERE)
ZH = os.path.join(HERE, "zhunze")
META = os.path.join(HX, "00_meta", "meta.json")
VIEW = os.path.join(HX, "20_view")
LEDGER_DIR = os.path.join(HX, "30_taizhang")
DB = os.path.join(HERE, "rules.json")

REF = re.compile(r"(?:按|见|依|据|照|走|见第)\s*(\d{1,2}\.\d{1,2}(?:\.\d{1,2}){0,2})")
REF2 = re.compile(r"(?<![0-9.])（(\d{1,2}\.\d{1,2}(?:\.\d{1,2}){0,2})）")


def rd(p):
    return io.open(p, encoding="utf-8").read()


def wr(p, s):
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)


def sha_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def zhang_files():
    if not os.path.isdir(ZH):
        return []
    return sorted([f for f in os.listdir(ZH) if re.match(r"^z\d{2}\.json$", f)])


def load():
    meta = json.loads(rd(META)) if os.path.exists(META) else {}
    chapters, clauses = [], []
    for f in zhang_files():
        z = json.loads(rd(os.path.join(ZH, f)))
        chapters.append({"ch": z["ch"], "file": z["file"],
                         "chapter_title": z["chapter_title"],
                         "n": len(z["clauses"]), "json": f})
        for c in z["clauses"]:
            c2 = dict(c)
            c2["ch"] = z["ch"]
            clauses.append(c2)
    return {"meta": meta, "chapters": chapters, "clauses": clauses}


def index(db):
    """补 refs / broken_refs / nbody"""
    ids = set(c["id"] for c in db["clauses"])
    roots = set(c["root"] for c in db["clauses"])
    for c in db["clauses"]:
        text = c["title"] + "\n" + "\n".join(c["body"])
        refs = set(REF.findall(text)) | set(REF2.findall(text))
        c["refs"] = sorted(r for r in refs if r in ids or r in roots)
        c["broken_refs"] = sorted(r for r in refs if r not in ids and r not in roots)
        c["nbody"] = len([x for x in c["body"] if x.strip()])
    return db


def dup_ids(db):
    seen, dup = set(), []
    for c in db["clauses"]:
        if c["id"] in seen:
            dup.append(c["id"])
        seen.add(c["id"])
    return dup


def block_broken(clauses):
    """同一 root 的条款必须连续出现且主条在最前"""
    pos, bad = {}, []
    for i, c in enumerate(clauses):
        pos.setdefault(c["root"], []).append(i)
    for r, ps in pos.items():
        if ps != list(range(ps[0], ps[0] + len(ps))) or clauses[ps[0]]["id"] != r:
            bad.append(r)
    return sorted(bad)


def shell_clauses(db):
    """标题以「：」结尾、自身无正文、且没有任何子条款承接的条款。"""
    kids = [c["id"] for c in db["clauses"]]
    out = []
    for c in db["clauses"]:
        if c["nbody"] > 0 or not c["title"].rstrip().endswith("："):
            continue
        if any(k.startswith(c["id"] + "(") or k.startswith(c["id"] + ".") for k in kids):
            continue
        out.append(c["id"])
    return out


def build_index(db):
    qw = sorted([f for f in os.listdir(VIEW)
                 if f.startswith("quanwen_") and f.endswith(".txt")]) \
        if os.path.isdir(VIEW) else []
    return {
        "schema": 1,
        "product": "Bumao XTGL Community",
        "name": db["meta"].get("name", ""),
        "version": db["meta"].get("version", ""),
        "ssot_files": zhang_files(),
        "n_clauses": len(db["clauses"]),
        "n_chapters": len(db["chapters"]),
        "chapters": [{"ch": c["ch"], "file": c["file"], "n": c["n"]} for c in db["chapters"]],
        "ids": [c["id"] for c in db["clauses"]],
        "quanwen_files": qw,
    }


def save(db):
    idx = build_index(db)
    wr(DB, json.dumps(idx, ensure_ascii=False, indent=1))
    return "%s %s / 条款 %d / 分章 %d" % (idx["name"], idx["version"], idx["n_clauses"], idx["n_chapters"])


def rules_sha():
    """z 系真身合并哈希。B19 与 engine 的检查凭据共用这一算法，避免两套口径。"""
    h = hashlib.sha256()
    for f in zhang_files():
        with open(os.path.join(ZH, f), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def enforce_decl():
    """第 11／12 章逐条的「条款 id → 闸位」声明，供 engine 的 A12 接线核对。"""
    out = []
    for f in zhang_files():
        z = json.loads(rd(os.path.join(ZH, f)))
        for c in z.get("clauses") or []:
            g = c.get("gate")
            if g:
                out.append({"clause": c.get("id", ""), "gate": g,
                            "judge": c.get("judge", ""), "file": f})
    return out


CHAIN = os.path.join(LEDGER_DIR, "check_run_chain.jsonl")


class _CheckLock:
    """check_last.json 独占锁：O_EXCL 建锁，超时即失败，不静默降级。"""

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
                    raise RuntimeError("检查凭据锁被占用：%s" % self.path)
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


def _chain_append(run_id, doc):
    """运行链：每轮绿检查落一行，prev 指上一行 sha256，只追加。

    check_last.json 是单个可手写的 JSON；B19／B22 要判「凭据来自同一次真实运行」，
    就得有一个只能由检查本身追加的旁证。手写 check_last 对不上链，判红。
    """
    prev = ""
    if os.path.isfile(CHAIN):
        rows = [l.rstrip("\n") for l in io.open(CHAIN, encoding="utf-8") if l.strip()]
        if rows:
            prev = hashlib.sha256(rows[-1].encode("utf-8")).hexdigest()
    row = {"at": doc["finished_at"], "ts": time.time(), "run_id": run_id,
           "rules_sha": doc["rules_sha"], "nfail": 0,
           "a_items": doc["a_items"], "b_items": doc["b_items"],
           "total": doc["total"], "prev": prev}
    line = json.dumps(row, ensure_ascii=False)
    with io.open(CHAIN, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")
    return row


def chain_ok(run_id):
    """run_id 能否在运行链里找到一条绿记录（链断即红、找不到即红）。"""
    rid = str(run_id or "").strip()
    if not rid:
        return False, "检查凭据缺 run_id"
    if not os.path.isfile(CHAIN):
        return False, "缺运行链 %s（凭据无法自证来自真实运行）" % os.path.basename(CHAIN)
    prev, hit, n = "", None, 0
    for ln in io.open(CHAIN, encoding="utf-8"):
        ln = ln.rstrip("\n")
        if not ln.strip():
            continue
        n += 1
        try:
            rec = json.loads(ln)
        except ValueError:
            return False, "运行链第 %d 行不是合法 JSON（被截断或手写）" % n
        if rec.get("prev") != prev:
            return False, "运行链第 %d 行 prev 不符（上一行被改／插入／删除）" % n
        if str(rec.get("run_id") or "") == rid:
            hit = rec
        prev = hashlib.sha256(ln.encode("utf-8")).hexdigest()
    if hit is None:
        return False, "run_id=%s 在运行链里没有绿记录（手写 check_last 不算凭据）" % rid
    return True, "run_id=%s 对上运行链绿记录（%s，A=%d／B=%d）" % (
        rid[:8], hit.get("at"), int(hit.get("a_items") or 0), int(hit.get("b_items") or 0))


def record_check_result(nfail, a_items, b_items, total, run_id=""):
    """每轮 check 结束写凭据；B19 下一轮据此判「跑完检查才准落盘」。

    2026-11-08（第二批第 2 条）：
      - 独占锁串行化写入，临时件＋fsync＋原子替换，避免两轮并发各写半截；
      - nfail≠0 一律不落凭据（不升级旧凭据，也不写半成品）；
      - 绿轮的 run_id 追加进 check_run_chain.jsonl（哈希链），B19／B22 不再只比 sha。
    """
    path = os.path.join(LEDGER_DIR, "check_last.json")
    rid = (run_id or os.environ.get("BUMO_RUN_ID") or "").strip() or str(uuid.uuid4())
    if int(nfail) != 0:
        return {"written": False, "nfail": int(nfail), "run_id": rid}
    # 第二批 R6：把受管件内容哈希清单写进凭据，B22 下一轮按内容划界，不再看 mtime。
    try:
        import enforce as _qz
        _msha = _qz.managed_sha()
    except Exception:
        _msha = {}
    doc = {
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "run_id": rid,
        "rules_sha": rules_sha(),
        "a_items": int(a_items),
        "b_items": int(b_items),
        "total": int(total),
        "nfail": 0,
        "version": json.loads(rd(META)).get("version", "") if os.path.exists(META) else "",
    }
    if _msha:
        doc["managed_sha"] = _msha
    with _CheckLock(path):
        _chain_append(rid, doc)
        tmp = "%s.%d.%s.tmp" % (path, os.getpid(), uuid.uuid4().hex)
        try:
            with io.open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(doc, ensure_ascii=False, indent=1))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    return doc


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    db = index(load())
    print("装载：" + save(db))
    print("  重复 id %d %s" % (len(dup_ids(db)), dup_ids(db)[:5]))
    bb = block_broken(db["clauses"])
    print("  块断裂 %d %s" % (len(bb), bb[:5]))
    bad = [(c["id"], c["broken_refs"]) for c in db["clauses"] if c["broken_refs"]]
    print("  断链 %d %s" % (len(bad), bad[:5]))
    print("  空壳 %d %s" % (len(shell_clauses(db)), shell_clauses(db)[:5]))
