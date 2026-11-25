# Bumao XTGL 便携版 · 行路版 0.01

一套 U 盘优先、自包含的 Bumao XTGL 发行版。规则库、运行时守卫与 Web 控制台全部随包发布。插盘即用，任何机器可跑，宿主不留痕。

A USB-first, self-contained edition of Bumao XTGL. Rules, runtime guard and web console ship inside the package. Drop it on a stick, run it on any machine, leave nothing behind on the host.

## 包含内容 / What is inside

| 目录 Path | 内容 Content |
|---|---|
| `00_meta/` | 元数据、功能包、模板、规则库 / Metadata, feature packs, templates, rules library |
| `10_rac/` | 规则与执行层：规则集、工具调用守卫、运行时守卫（supervisor / scope / gate check / ledger）、输出守卫、台账 / Rules and execution layer |
| `20_view/` | 查看层：Web 控制台与图标集 / Viewer layer: web console and icon set |
| `MANIFEST.sha256` | 逐文件校验清单 / Per-file checksum manifest |
| `core_manifest.json` | 前端核心件哈希 / Front-end core file hashes |

仓级文件 / Repository-level files：`LICENSE`(Apache-2.0)、`NOTICE`、`TRADEMARK.md`、`CONTRIBUTING.md`、`DCO`、`README-HX.txt`、`.gitattributes`、`.gitignore`。

## 运行方式 / How to run

便携版由启动器层与本体两部分组成，在盘根把两者合到位 / The portable edition is a launcher layer plus a body; put both at the stick root:

```
<盘根 stick root>/
├── launcher/          start.bat, start.ps1, portable_menu.py, portable_env.py,
│                      portable_paths.py, check_disk.py, resume.py, archive.py, finish.py
├── body/community/    本仓内容 / contents of this repository
└── archive/community/ 盘内归档 / on-stick archive
```

1. 体检 / Health check：`python launcher/check_disk.py`，应为 `FAIL=0`
2. 启动 / Launch：`launcher/start.bat`，菜单里选 community
3. 把本体接到宿主机临时区 / Resume body into the host temp area：`python launcher/resume.py`
4. 在临时区干活 / Work in the temp area（`%LOCALAPPDATA%\BumaoPortable\work`）
5. 归档回盘 / Archive back to the stick：`python launcher/archive.py --prune`
6. 收工 / Finish：`python launcher/finish.py`，清宿主机临时区，盘内归档保留

## 校验 / Verify

```bash
sha256sum -c MANIFEST.sha256
```

## 许可 / License

Apache-2.0，见 / see `LICENSE`。商标与署名条款见 / Trademark and attribution terms: `TRADEMARK.md`。
