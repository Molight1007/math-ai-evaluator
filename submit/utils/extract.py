"""答案提取与格式化工具""" 

import re


def extract_final_answer(text: str) -> str:
    """
    从模型输出中提取最终答案。

    三级提取策略：
    1. 查找【最终答案】标记后的内容
    2. 查找 \\boxed{...} 格式（LaTeX 常见）
    3. 取最后一行非空内容
    """
    if not text:
        return ""

    # 策略 1：【最终答案】标记
    patterns = [
        r"【最终答案】\s*\n?\s*(.+?)(?:\n|$)",
        r"最终答案[:：]\s*(.+?)(?:\n|$)",
        r"答案[:：]\s*(.+?)(?:\n|$)",
        r"[Ff]inal\s*[Aa]nswer[:：]\s*(.+?)(?:\n|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            answer = match.group(1).strip()
            if answer:
                return clean_answer(answer)

    # 策略 2：\\boxed{...} 格式
    boxed_match = re.search(r"\\boxed\{([^}]+)\}", text)
    if boxed_match:
        return boxed_match.group(1).strip()

    # 策略 3：最后一行
    lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
    if lines:
        last_line = lines[-1]
        # 排除明显的非答案行
        if not re.match(r"^(因此|所以|故|综上|综上所|因此最后|终上)", last_line):
            return clean_answer(last_line)
        # 如果最后一行是总结语句，取倒数第二行
        if len(lines) > 1:
            return clean_answer(lines[-2])

    return ""


def clean_answer(text: str) -> str:
    """清理答案文本，去除多余符号"""
    text = text.strip()
    # 去除编号前缀
    text = re.sub(r"^[\d]+[\.\、\)）]\s*", "", text)
    # 去除 markdown 格式
    text = text.replace("**", "").replace("__", "")
    return text


def format_response(answer: str) -> str:
    """确保 final_response 非空且可序列化"""
    if answer is None:
        return ""
    answer = str(answer).strip()
    return answer


def safe_json_serialize(obj: dict) -> dict:
    """
    安全地将字典转为 JSON 可序列化格式。
    递归处理所有值，将不可序列化的对象转为字符串。
    """
    result = {}
    for key, value in obj.items():
        if isinstance(value, dict):
            result[key] = safe_json_serialize(value)
        elif isinstance(value, (list, tuple)):
            result[key] = [
                safe_json_serialize(v) if isinstance(v, dict)
                else str(v) if not isinstance(v, (str, int, float, bool, type(None)))
                else v
                for v in value
            ]
        elif isinstance(value, (str, int, float, bool, type(None))):
            result[key] = value
        else:
            result[key] = str(value)
    return result
