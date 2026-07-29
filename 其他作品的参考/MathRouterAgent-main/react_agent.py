"""ReAct 数学推理智能体模块（从 DeepMath 子项目迁移而来）。

本模块是一个自包含的 ReAct agent，使用 smolagents 的 LocalPythonExecutor
作为 Python 沙箱（支持 sympy / mpmath / numpy / scipy 等科学计算库），
配合 OpenAI 兼容的 InternChatClient 完成"代码即推理"的数学问题求解。

该模块会被 user_agent.py 导入使用，不依赖任何 deep_math.* 或 DeepMath.* 模块。
"""

import ast
import concurrent.futures
import re
import time
from pathlib import Path

from smolagents import (
    ChatMessage,
    LocalPythonExecutor,
    MessageRole,
    Model,
    fix_final_answer_code,
    parse_code_blobs,
)

# ==================== 常量定义（迁移自 run_intern_agent.py）====================

# 停止序列：模型在生成到 </tool_call> 或 <end_code> 时截断
# （与源文件 run_intern_agent.py 保持一致，使用 </tool_call> 而非 </code>）
STOP_SEQUENCES = ["</tool_call>", "<end_code>"]

# 沙箱额外允许导入的第三方库
ADDITIONAL_IMPORTS = [
    "cmath",
    "numpy",
    "scipy",
    "sympy",
    "mpmath",
    "math",
    "random",
    "statistics",
]

# 用于从模型输出中提取 \boxed{...} 答案的正则
BOXED_RE = re.compile(r"\\boxed\{((?:[^{}]|\{[^{}]*\})*)\}")

# 上下文裁剪阈值：消息数超过此值时，保留 system + 首条 user + 最近若干条消息
MAX_MESSAGES = 22


# ==================== InternChatModel（迁移自 deep_math/intern_model.py）====================


class InternChatModel(Model):
    """Wraps an InternChatClient so smolagents-style agents can call it.

    The client is injected by the runner; this module only depends on
    smolagents, not on llm_client, so it can be imported as
    ``from react_agent import InternChatModel``.
    """

    def __init__(self, client, temperature: float = 0, max_tokens: int = 3000, enable_thinking: bool = False):
        self.client = client
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.enable_thinking = enable_thinking
        self.last_input_token_count = 0
        self.last_output_token_count = 0

    @staticmethod
    def _role_to_openai(role) -> str:
        # MessageRole is an enum; accept either it or a raw string.
        role_str = role.value if hasattr(role, "value") else str(role)
        role_lower = role_str.lower()
        # InternLM endpoint may reject the "tool" role; fall back to "user".
        if role_lower == "tool":
            return "user"
        return role_lower

    def generate(
        self,
        messages,
        stop_sequences=None,
        response_format=None,
        tools_to_call_from=None,
        prefill: str = None,
        **kwargs,
    ) -> ChatMessage:
        try:
            openai_msgs = [
                {"role": self._role_to_openai(m.role), "content": m.content}
                for m in messages
            ]
            if prefill:
                openai_msgs.append({"role": "assistant", "content": prefill})
            text = self.client.chat(
                openai_msgs,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                enable_thinking=self.enable_thinking,
            )

            # Truncate at the first occurrence of any stop sequence (stop
            # string itself excluded, matching the agent's expectation that
            # the assistant message ends right before the observation block).
            if stop_sequences and text:
                cut = -1
                for s in stop_sequences:
                    if not s:
                        continue
                    idx = text.find(s)
                    if idx >= 0 and (cut < 0 or idx < cut):
                        cut = idx
                if cut >= 0:
                    text = text[:cut]

            if prefill:
                text = prefill + text

            self.last_input_token_count = sum(len(m.content) for m in messages) // 4
            self.last_output_token_count = len(text or "") // 4
            return ChatMessage(
                role=MessageRole.ASSISTANT, content=text, raw={"out": text}
            )
        except Exception as exc:  # noqa: BLE001 - keep the agent loop alive.
            print(f"########################## Error in InternChatModel.generate: {exc}")
            return ChatMessage(
                role=MessageRole.ASSISTANT, content="I don't know.", raw={}
            )

    def __call__(self, *args, **kwargs):
        return self.generate(*args, **kwargs)


# ==================== 工具函数（迁移自 run_intern_agent.py）====================


def _recover_truncated_code(code: str) -> str:
    """Recover a valid Python prefix from truncated code.

    When max_tokens cuts off code mid-expression (e.g. `coeffs = [1, 1, 2, 3, `),
    ast.parse fails on the full code. This function tries progressively shorter
    prefixes (by removing lines from the end) until ast.parse succeeds.

    Returns the valid prefix (+ a truncation notice) so the sandbox can execute
    *something* and `code_executed` becomes True, or "" if no valid prefix exists.
    """
    code = code.strip()
    if not code:
        return ""
    # Full code already parses — no truncation, return as-is.
    try:
        ast.parse(code)
        return code
    except SyntaxError:
        pass
    # Truncated: try progressively shorter prefixes by dropping lines from the end.
    lines = code.split("\n")
    for i in range(len(lines) - 1, 0, -1):
        prefix = "\n".join(lines[:i]).strip()
        if not prefix:
            continue
        try:
            ast.parse(prefix)
            return (
                prefix
                + '\nprint("[code truncated by max_tokens — showing partial output]")'
            )
        except SyntaxError:
            continue
    return ""


# ==================== ReAct 主循环 ====================


def run_react(client, problem, config) -> tuple:
    """运行 ReAct 推理循环，返回 (final, trace, code_executed) 三元组。

    参数:
        client: OpenAI 兼容的 InternChatClient 实例（由调用方注入）。
        problem: 待求解的数学问题文本。
        config: AgentConfig 数据类实例，需包含以下字段：
            - react_max_steps (int)      : 最大 ReAct 步数
            - react_code_timeout (int)   : Python 沙箱执行超时（秒）
            - react_temperature (float)  : 采样温度
            - react_max_tokens (int)     : 单次生成的最大 token 数
            - react_enable_thinking (bool): 是否开启思维链
    """
    # 1. 构造模型（使用 config 中的参数）
    model = InternChatModel(
        client,
        temperature=config.react_temperature,
        max_tokens=config.react_max_tokens,
        enable_thinking=config.react_enable_thinking,
    )

    # 2. 加载系统提示词与 fewshot 示例（基于本文件所在目录定位 prompts 目录）
    prompts_dir = Path(__file__).parent / "prompts"
    system_prompt = (prompts_dir / "agent_math.txt").read_text(encoding="utf-8")
    fewshot = (prompts_dir / "fewshot.txt").read_text(encoding="utf-8")

    # 3. 用 fewshot 填充系统提示词中的 {examples} 占位符
    system_prompt = system_prompt.replace("{examples}", fewshot)

    # 4. 构造用户提示词（沿用 simple_template 格式 + 引导模型以代码块开头的后缀）
    user_prompt = f"Question: {problem}"
    user_prompt = user_prompt + "\n\nStart your response NOW with a <tool_call> block. Suggested shape:\n<tool_call>\nimport sympy as sp\n# your code here — explore the problem computationally\nprint(result)\n</tool_call>"

    # 5. 构造初始消息列表
    messages = [
        ChatMessage(MessageRole.SYSTEM, system_prompt),
        ChatMessage(MessageRole.USER, user_prompt),
    ]

    # 6. 创建 Python 沙箱并注入基础工具（print / range 等）
    executor = LocalPythonExecutor(
        additional_authorized_imports=ADDITIONAL_IMPORTS
    )
    # populate static_tools with BASE_PYTHON_TOOLS (print, range, etc.);
    # without this, the sandbox forbids calling print.
    executor.send_tools({})

    trace = []
    final = ""
    code_executed = False
    no_code_streak = 0

    max_steps = config.react_max_steps
    code_timeout = config.react_code_timeout

    wall_clock_timeout = config.react_wall_clock_timeout
    start_time = time.monotonic()

    # 7. ReAct 主循环
    for step in range(1, max_steps + 1):
        # 单题 wall-clock 超时兜底：超过阈值后强制输出最优 \boxed{} 答案
        elapsed = time.monotonic() - start_time
        if elapsed > wall_clock_timeout:
            # 优先从 trace 中检索最近一条含 \boxed{ 的 assistant 消息
            best_boxed_final = ""
            for tr in trace:
                if tr.get("role") == "assistant" and "\\boxed{" in (tr.get("content") or ""):
                    best_boxed_final = tr["content"]
            if best_boxed_final:
                final = best_boxed_final
                trace.append({
                    "step": step,
                    "role": "wall_clock_timeout",
                    "content": f"Timeout after {elapsed:.1f}s at step={step}; recovered boxed from trace.",
                })
            else:
                # 无任何 \boxed{，触发兜底 LLM 调用
                fallback_prompt = (
                    "Based on the reasoning so far, give your best \\boxed{} answer now. "
                    "Output ONLY the \\boxed{} answer with no explanation."
                )
                fallback_msgs = messages + [
                    ChatMessage(MessageRole.USER, fallback_prompt)
                ]
                try:
                    fb_resp = model.generate(fallback_msgs, stop_sequences=None, prefill="<plan>\n")
                    fallback_final = (fb_resp.content or "").lstrip()
                except Exception as exc:  # noqa: BLE001
                    fallback_final = f"\\boxed{{}}"  # 终极兜底：空 boxed
                final = fallback_final if "\\boxed{" in fallback_final else fallback_final + "\n\n\\boxed{}"
                trace.append({
                    "step": step,
                    "role": "wall_clock_timeout",
                    "content": f"Timeout after {elapsed:.1f}s at step={step}; no boxed in trace, fallback LLM call.",
                })
                trace.append({
                    "step": step,
                    "role": "wall_clock_fallback",
                    "content": final[:500],
                })
            break
        # 使用 <plan>\n 作为 prefill，强制模型以计划块开头
        resp = model.generate(messages, stop_sequences=STOP_SEQUENCES, prefill="<plan>" + chr(10))
        out = resp.content or ""
        trace.append({"step": step, "role": "assistant", "content": out})

        # 检测 API 层错误（如 INPUT_LENGTH_ERROR），提前退出避免错误响应膨胀上下文
        if "internal error" in out.lower() or "INPUT_LENGTH_ERROR" in out:
            trace.append({"step": step, "role": "error", "content": f"API error detected, stopping: {out[:200]}"})
            break

        # 剥离 <think>...</think> 推理块（intern-s2-preview 是推理模型，会输出这些；
        # 真正的响应在 </think> 之后）
        out = re.sub(r"<think>.*?</think>", "", out, flags=re.DOTALL)
        # 同时剥离孤立的 </think> 闭合标签
        out = out.replace("</think>", "")
        out = out.lstrip()

        # 检测到 \boxed{ 则视为最终答案，提前结束
        if "\\boxed{" in out:
            final = out
            break

        messages.append(ChatMessage(MessageRole.ASSISTANT, out))

        # 停止序列截断（按 InternChatModel 的约定，截断时不包含停止串本身），
        # 可能留下未闭合的 <tool_call> 标签或代码围栏。这里补齐以便
        # 正则 / parse_code_blobs 能够成功解析。
        md = out
        if "<tool_call>" in md and "</tool_call>" not in md:
            md = md + "\n</tool_call>"
        # 将 <tool_call>...</tool_call> 转换为 python markdown 代码块
        md = re.sub(
            r"<tool_call>(.*?)</tool_call>",
            r"```python\n\1\n```\n",
            md,
            flags=re.DOTALL,
        )
        if md.count("```") % 2 == 1:
            md = md + "\n```"

        # 提取代码
        try:
            code = fix_final_answer_code(parse_code_blobs(md))
        except Exception:
            code = None

        if not code:
            # 兜底1：尝试从原始 out 中提取（可能包含未包裹在 <tool_call> 中的
            # ```python 代码块，或模型以其他格式产出了代码）
            try:
                code = fix_final_answer_code(parse_code_blobs(out))
            except Exception:
                code = None

        if not code and "<tool_call>" in out:
            # 兜底2：截断代码恢复。当 max_tokens 在 </tool_call> 之前截断代码时，
            # <tool_call> 块中包含非法 Python（如 `coeffs = [1, 1, 2, 3, `）。
            # fix_final_answer_code 会在 ast.parse 失败时抛错。这里尝试恢复
            # 最长的合法前缀。
            tc_match = re.search(r"<tool_call>(.*)", out, flags=re.DOTALL)
            if tc_match:
                raw_code = tc_match.group(1).split("</tool_call>")[0]
                recovered = _recover_truncated_code(raw_code)
                if recovered:
                    code = recovered

        if not code:
            # 检测幻觉的 ```output 块（模型自行模拟执行结果）
            if "```output" in out and "<tool_call>" not in out:
                observation = (
                    "CRITICAL: You wrote a simulated ```output block. This is NOT real execution — you are hallucinating results. "
                    "You MUST emit a <tool_call>...</tool_call> Python block to get REAL execution results. "
                    "Do NOT simulate output. Do NOT write ```output yourself."
                )
                messages.append(ChatMessage(MessageRole.USER, observation))
                trace.append({"step": step, "role": "user_observation", "content": observation})
                continue

            # 连续未产出代码的警告（分三级递进）
            no_code_streak += 1
            if no_code_streak == 1:
                observation = "No <tool_call> block found. You MUST emit a <tool_call>...</tool_call> Python block now. Do NOT reason in plain text."
            elif no_code_streak == 2:
                observation = "WARNING: You have failed to produce code for 2 consecutive turns. This violates the FORMAT CONTRACT. Immediately output a <tool_call> Python block. Do NOT write any prose."
            else:
                observation = "CRITICAL: Stop writing text. Output ONLY a <tool_call>...</tool_call> Python block. No explanation, no reasoning, just code."
            messages.append(ChatMessage(MessageRole.USER, observation))
            trace.append({"step": step, "role": "user_observation", "content": observation})
            continue

        # 成功提取到代码，执行之
        code_executed = True
        no_code_streak = 0

        def _run(code_action=code):
            return executor(code_action)

        output = ""
        logs = ""
        try:
            # 使用线程池 + 超时机制执行代码，防止死循环卡死整个 agent
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_run)
                code_result = future.result(timeout=code_timeout)
            # CodeOutput 是数据类而非元组，使用属性访问
            output = code_result.output
            logs = code_result.logs
        except concurrent.futures.TimeoutError:
            output = ""
            logs = f"Execution timed out after {code_timeout}s"
        except Exception as exc:  # noqa: BLE001
            output = ""
            logs = f"Exception: {exc}"

        # 将执行结果作为观测反馈给模型
        observation = (
            "```output\n" + str(logs) + "\n\n" + str(output) + "\n```\n"
        )
        messages.append(ChatMessage(MessageRole.USER, observation))
        trace.append(
            {"step": step, "role": "user_observation", "content": observation}
        )

        # 上下文裁剪，防止 INPUT_LENGTH_ERROR。
        # 保留 system + 首条 user 消息 + 最近若干条消息（约 5 步对）。
        # 插入一条摘要标记，让模型知道早期上下文已被裁剪。
        if len(messages) > MAX_MESSAGES:
            trimmed_summary = ChatMessage(
                MessageRole.USER,
                "[Earlier steps trimmed to fit context. Your recent 5 steps are preserved below. Do NOT repeat earlier approaches — switch strategy if stuck.]",
            )
            messages = messages[:2] + [trimmed_summary] + messages[-(MAX_MESSAGES - 2):]
    else:
        # 循环耗尽且未得到 \boxed 答案：取最后一条 assistant 消息作为最终输出
        for m in reversed(messages):
            if m.role == MessageRole.ASSISTANT:
                final = m.content
                break

    # 返回三元组（注意：不再返回 len(trace)）
    return final, trace, code_executed
