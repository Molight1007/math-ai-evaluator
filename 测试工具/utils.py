"""
公共工具模块 - 提供跨模块复用的通用函数。

集中存放多处重复的样板逻辑（HTML 转义、耗时统计、字段别名解析），
避免各模块各自实现导致逻辑不同步（代码要求 1.2 / 6.4）。
"""
import time
from contextlib import contextmanager
from typing import Iterator, Optional

import logging

logger = logging.getLogger(__name__)


def escape_html(text: str) -> str:
    """
    HTML 转义：防止 XSS 与标签破坏（代码要求 6.4）。

    统一处理 & < > " 四个特殊字符，供所有报告模块复用，
    避免各文件重复实现导致转义规则不一致。

    参数:
        text: 待转义的原始文本

    返回:
        转义后的安全 HTML 文本
    """
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@contextmanager
def timed() -> Iterator[float]:
    """
    耗时统计上下文管理器（代码要求 6.4 / 8.1）。

    用 `with timed() as t:` 包裹代码块，退出时自动计算耗时（秒）。
    替代散落在各处的 `start_time = time.time()` + `latency = round(...)` 样板。

    产出:
        上下文变量为开始时间戳（float），供调用方按需计算；
        实际耗时通过内部记录，调用方可用 `time.time() - t` 省略，
        此处直接 yield 起始时间，保持最小侵入。

    示例:
        with timed() as start:
            result = call_llm()
        latency = round(time.time() - start, 2)
    """
    start = time.time()
    try:
        yield start
    finally:
        # 上下文结束即记录一次总耗时日志，便于性能排查
        logger.debug("timed block elapsed=%.2fs", time.time() - start)


def get_first_by_aliases(
    data: dict, target: str, aliases: dict[str, list[str]]
) -> Optional[str]:
    """
    按别名映射从字典中取出第一个非空字段值（代码要求 6.4）。

    整合 loader._map_field / answer_extractor._find_value_by_keys /
    question_bank 内嵌 _g 三处重复逻辑，统一为单一实现。

    参数:
        data: 原始字段字典
        target: 目标字段名（作为 aliases 的键）
        aliases: 别名映射表，格式 {目标字段: [候选键名, ...]}

    返回:
        第一个非空字符串值；无匹配时返回 None
    """
    for alias in aliases.get(target, []):
        if alias in data:
            value = data[alias]
            if value is not None and str(value).strip():
                return str(value).strip()
    return None
