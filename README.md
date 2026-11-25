# Bumao XTGL Portable · Community 0.01

A USB-first, self-contained edition of Bumao XTGL. Rules, runtime guard and web console ship inside the package. Drop it on a stick, run it on any machine, leave nothing behind on the host.

## What is inside

| Path | Content |
|---|---|
| `00_meta/` | Metadata, feature packs, templates, rules library |
| `10_rac/` | Rules and execution layer: rule set, tool-call guard, runtime guard (supervisor / scope / gate check / ledger), output guard, ledger |
| `20_view/` | Viewer layer: web console and icon set |
| `MANIFEST.sha256` | Per-file checksum manifest |
| `core_manifest.json` | Front-end core file hashes |

Repository-level files: `LICENSE` (Apache-2.0), `NOTICE`, `TRADEMARK.md`, `CONTRIBUTING.md`, `DCO`, `README-HX.txt`, `.gitattributes`, `.gitignore`.

## How to run

The portable edition is composed of a launcher layer plus a body. Put the two together at the stick root:

```
<stick root>/
├── launcher/          start.bat, start.ps1, portable_menu.py, portable_env.py,
│                      portable_paths.py, check_disk.py, resume.py, archive.py, finish.py
├── body/community/    contents of this repository
└── archive/community/ on-stick archive
```

1. Health check: `python launcher/check_disk.py` — expect `FAIL=0`
2. Launch: `launcher/start.bat`, choose community in the menu
3. Resume body into the host temp area: `python launcher/resume.py`
4. Work in the temp area (`%LOCALAPPDATA%\BumaoPortable\work`)
5. Archive back to the stick: `python launcher/archive.py --prune`
6. Finish: `python launcher/finish.py` — wipes the host temp area, the on-stick archive stays

## Verify

```bash
sha256sum -c MANIFEST.sha256
```

## License

Apache-2.0, see `LICENSE`. Trademark and attribution terms are in `TRADEMARK.md`.
