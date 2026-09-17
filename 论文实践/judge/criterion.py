# -*- coding: utf-8 -*-
"""文本判据自检：验证「条件清单正则」是否真的判得准。

**为什么单独立一个文件**（2026-09-05 的血泪教训）：

判据正则写错时**不会报错、不会崩溃**——它只是安静地把所有模型判成
"漏条件"，然后你拿着一份看起来很合理、实则完全错误的报告去写论文。
这是本项目里**唯一一类不会自己暴露的错误**，必须有一个廉价的手段主动抓它。

自检用三条语料卡住判据的两端与鲁棒性：

| 语料 | 期望 | 抓的是什么错 |
|---|---|---|
| `perfect` | **全命中** | 正则太窄 → 漏判（如只认 `‖u‖` 不认 `||u||`） |
| `vague` | **漏命中** | 正则太松 → 无法区分"真懂"与"会说" |
| `variants` | **全命中** | 记号/语言变体没覆盖（Unicode/LaTeX/中英） |

不联网、不花钱、3 秒跑完。**加新题后必跑。**
"""
from __future__ import annotations

from bank.problems import E_ITEMS, E_SELFTEST
from probes.statement import _score


def run(verbose: bool = True) -> tuple[int, int]:
    """返回 (失败数, 检查总数)。退出码由调用方决定。"""
    n_fail = 0
    n_check = 0

    def _line(s: str = "") -> None:
        if verbose:
            print(s)

    _line("=" * 74)
    _line("文本判据自检（不联网 / 不花钱 / 加题后必跑）")
    _line("=" * 74)

    for item in E_ITEMS:
        corpus = E_SELFTEST.get(item.eid)
        if not corpus:
            _line(f"\n⚠️  {item.eid} 没有自检语料 —— 加题时请同步补 E_SELFTEST")
            continue

        n = len(item.key_conditions) or 1
        _line(f"\n{item.eid}  {item.theorem}（{len(item.key_conditions)} 个关键条件）")

        # ① perfect：必须全命中
        for text in corpus.get("perfect", []):
            n_check += 1
            hits = _score(text, item)
            if all(hits):
                _line(f"  ✓ [perfect]  {sum(hits)}/{n}")
            else:
                n_fail += 1
                missing = [c for c, h in zip(item.key_conditions, hits) if not h]
                _line(f"  ❌ [perfect]  {sum(hits)}/{n} —— 判据太窄，漏判：")
                for m in missing:
                    _line(f"       - {m}")

        # ② vague：必须漏命中（否则判据过松，分不出真懂与含糊）
        for text in corpus.get("vague", []):
            n_check += 1
            hits = _score(text, item)
            if not all(hits):
                _line(f"  ✓ [vague]    {sum(hits)}/{n}（正确：识别出含糊）")
            else:
                n_fail += 1
                _line(f"  ❌ [vague]    {n}/{n} —— 判据太松，含糊回答也被判全对")

        # ③ variants：换写法仍须全命中
        for i, text in enumerate(corpus.get("variants", []), 1):
            n_check += 1
            hits = _score(text, item)
            if all(hits):
                _line(f"  ✓ [variant{i}] {sum(hits)}/{n}")
            else:
                n_fail += 1
                missing = [c for c, h in zip(item.key_conditions, hits) if not h]
                _line(f"  ❌ [variant{i}] {sum(hits)}/{n} —— 写法变体没覆盖：")
                _line(f"       原文：{text.strip()[:76]}")
                for m in missing:
                    _line(f"       - {m}")

    _line("\n" + "=" * 74)
    if n_fail:
        _line(f"❌ {n_fail}/{n_check} 项未通过 —— **判据不可信，先修再跑实验**")
    else:
        _line(f"✅ {n_check}/{n_check} 项全部通过 —— 判据可区分，且不受写法变体影响")
    _line("=" * 74)
    return n_fail, n_check
