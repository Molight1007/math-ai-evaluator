# -*- coding: utf-8 -*-
"""三体架构图生成器测试（2026-10-27）。

图是给人看的状态快照，最容易出现的错不是"算错"，而是：
  · 节点漏画 / 多画（图上看不出，但会让人以为某块没做或做了）
  · 框跑出画布或互相压住（排版崩了，但文件照样"生成成功"）
  · 头部统计与实际节点数不一致（最坑：图上说 13 已落地，其实只有 12）
所以这三条都要机器验一遍。
"""
from __future__ import annotations

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import tools.gen_three_body_diagram as gen  # noqa: E402


def _html():
    return gen.render(gen._counts())[0]


def test_01_all_nodes_rendered():
    html = _html()
    assert html.count('<g class="node"') == 23, "节点数必须与架构图一致（4+6+4+3+4+2）"


def test_02_header_stats_match_nodes():
    html = _html()
    n_all = html.count('<g class="node"')
    n_ok = html.count('data-st="ok"')
    n_warn = html.count('data-st="warn"')
    n_bad = html.count('data-st="bad"')
    m = re.search(r"(\d+) 节点：.*?(\d+) 已落地.*?(\d+) 部分.*?(\d+) 未做", html, re.S)
    assert m, "头部统计行缺失"
    assert tuple(int(x) for x in m.groups()) == (n_all, n_ok, n_warn, n_bad)
    assert n_ok + n_warn + n_bad == n_all


def test_03_boxes_stay_inside_canvas():
    html = _html()
    rects = [(float(x), float(y), float(w))
             for x, y, w in re.findall(
                 r'<rect class="nb" x="([\d.]+)" y="(\d+)" width="([\d.]+)"', html)]
    assert len(rects) == 23
    out = [r for r in rects if r[0] < 40 or r[0] + r[2] > 1580]
    assert not out, "有框跑出画布：%s" % out


def test_04_no_overlap_within_lane():
    html = _html()
    rects = [(float(x), float(y), float(w))
             for x, y, w in re.findall(
                 r'<rect class="nb" x="([\d.]+)" y="(\d+)" width="([\d.]+)"', html)]
    by_y = {}
    for r in rects:
        by_y.setdefault(r[1], []).append(r)
    for y, rs in by_y.items():
        rs.sort()
        for a, b in zip(rs, rs[1:]):
            assert a[0] + a[2] <= b[0], "y=%s 处两个框重叠" % y


def test_05_counts_come_from_artifacts():
    """数字必须现读产物：params.json 存在时 A 段不该是 0。"""
    c = gen._counts()
    if os.path.isfile(os.path.join(REPO, "params.json")):
        assert c["A"] > 0 and c["B"] > 0
    assert set(c) >= {"A", "B", "C", "ctx", "ledger", "cands", "cal", "delta"}


def test_06_detail_text_is_pipe_separated_and_escaped():
    html = _html()
    for d in re.findall(r'data-d="([^"]*)"', html):
        assert d.count("|") >= 1, "详情应按 | 分段，右侧面板才会分条显示"
        assert '"' not in d, "详情里的引号必须转义成 &quot;，否则属性会被截断"
