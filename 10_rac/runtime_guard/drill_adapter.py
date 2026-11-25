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

"""drill_adapter.py —— 执行中监管演练（sandbox）：走 community 端真实适配器入口。

落点：本包 jiancha_run（真实运行目录，动作账供 audit 按 op_id 回查）。
工作区是临时目录，不碰活区；环境默认 sandbox。
op_id 从 BUMO_OP_ID 继承——与同轮 check 票共用同一个键，串链才成立。

用法：
    BUMO_OP_ID=op-... python drill_adapter.py
用例：
    ① 合规写 40_renwu/tasks.json → 放行并落盘；
    ② 目标落 90_lishi/tasks.json → enforce 拒绝，动作不执行。
退出码 0＝两条都符合预期。
"""
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from runtime_guard import community_adapter as A  # noqa: E402

ROWS = []


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def make_workspace(tmp):
    root = os.path.join(tmp, "drill_ws")
    _write(os.path.join(root, "40_renwu", "tasks.json"), "[]\n")
    _write(os.path.join(root, "90_lishi", "tasks.json"), "[]\n")
    return root


class FakeConsole(object):
    def __init__(self, root, board_rel):
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


def main():
    os.environ.setdefault("BUMO_JIANCHA_ENV", "sandbox")
    A._SINGLETONS.clear()
    op = os.environ.get("BUMO_OP_ID") or ""
    tmp = tempfile.mkdtemp(prefix="drill_comm_")
    ok = True
    try:
        for name, board_rel, want_blocked in (
                ("in_scope", "40_renwu/tasks.json", False),
                ("denied", "90_lishi/tasks.json", True)):
            root = make_workspace(os.path.join(tmp, name))
            c = FakeConsole(root, board_rel)
            ctx = A.begin_post(c, "/api/task/add", {"board": "goals"}, "enforce")
            blocked = bool(ctx and ctx.get("blocked"))
            ran = False
            if not blocked:
                _write(os.path.join(root, *board_rel.split("/")), "[]\n")
                ran = True
                # 与真实 caller 一致：blocked 直接回 403、不进路由分支，也不调 end_post
                # （end_post 会再跑一次 post_check，把被拒的写记成 ok）。
                A.end_post(ctx, None)
            good = blocked == want_blocked and ran != want_blocked
            ok = ok and good
            ROWS.append({"case": name, "blocked": blocked, "executed": ran,
                         "error": (ctx or {}).get("body", {}).get("error", "")})
            print("%s %s：blocked=%s executed=%s %s"
                  % ("PASS" if good else "FAIL", name, blocked, ran,
                     (ctx or {}).get("body", {}).get("error", "")))
        print("op_id=%s（与同轮 check 票同键）" % (op or "（未设）"))
        print("动作账：%s" % os.path.join(HERE, "jiancha_run", "actions.jsonl"))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
