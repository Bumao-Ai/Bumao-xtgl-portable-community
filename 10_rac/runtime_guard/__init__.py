# -*- coding: utf-8 -*-
"""runtime_guard —— community end's "in-flight supervision" package (0.2 kernel three-gate
community adaptation).

Mount point (this end changes exactly one place): do_POST in 20_view/web/xtgl_core.py
    entry-prebegin begin_post() ＋ finally post-end end_post()
The 21 route branches, _body() and the 16 write methods are all untouched.

Four modes (env BUMO_JIANCHA_MODE; missing/invalid = off):
  off      do not load this package at all: no import, no run dir, no ledger; HTTP behavior
           is verbatim-equivalent to pre-integration
  shadow   S0/S1 computed and logged, but nothing blocked; records mark would_deny
  enforce  S0 failure rejects (write action does not execute); S1 can only act after the
           fact (already on disk, that instant cannot be blocked)

All imports inside the package are relative (from . import ...): community's 10_rac top
level has a same-name module; absolute import via sys.path would shadow it and break the
existing entry.
"""
