"""
数学智能体评测器 - 数据模型定义
定义整个评测流程中使用的核心数据结构。
"""
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Problem:
    """题目数据模型 - 从题库/文件中加载的原始数学题"""
    id: str                                       # 题目唯一标识
    question: str                                 # 题目内容
    domain: Optional[str] = None                  # 所属知识域（如：代数、几何）
    reference_answer: Optional[str] = None        # 参考答案（用于评判）


@dataclass
class InferenceResult:
    """推理结果 - Intern-S1 模型对单题的推理输出"""
    problem_id: str                               # 对应的题目ID
    question: str                                 # 原题内容
    answer: str = ""                              # 模型给出的最终答案
    reasoning: str = ""                           # 推理过程文本
    steps: list[str] = field(default_factory=list)# 分步骤推理列表
    verification: str = ""                        # 自验证过程
    raw_response: str = ""                        # API 返回的原始响应
    tokens_used: int = 0                          # 推理消耗的 token 数
    latency_seconds: float = 0.0                  # 推理耗时（秒）
    error: Optional[str] = None                   # 推理过程中的错误信息


@dataclass
class JudgeResult:
    """评判结果 - DeepSeek 模型对推理结果的正确性判定"""
    problem_id: str                               # 对应的题目ID
    is_correct: bool = False                      # 答案是否正确
    confidence: float = 0.0                       # 评判置信度（0~1）
    explanation: str = ""                         # 评判解释
    error_type: Optional[str] = None              # 错误类型分类
    correct_answer: Optional[str] = None          # 评判模型给出的正确答案
    raw_response: str = ""                        # API 返回的原始响应
    tokens_used: int = 0                          # 评判消耗的 token 数
    latency_seconds: float = 0.0                  # 评判耗时（秒）
    error: Optional[str] = None                   # 评判过程中的错误信息


@dataclass
class LeanVerificationResult:
    """Lean 形式化验证结果 - 将推理转化为 Lean 代码并编译验证的完整信息"""
    problem_id: str = ""                          # 对应的题目ID
    verified: bool = False                        # 是否执行了 Lean 验证
    lean_available: bool = False                  # Lean 环境是否可用
    # 转化阶段
    lean_code: str = ""                           # 转化后的 Lean 4 代码
    formalized_claim: str = ""                    # 形式化后的命题描述（中文）
    conversion_tokens: int = 0                    # 转化阶段消耗 token
    conversion_latency: float = 0.0               # 转化耗时（秒）
    conversion_error: Optional[str] = None        # 转化过程中的错误
    # 编译阶段
    compile_passed: Optional[bool] = None         # Lean 编译是否通过（None=未编译）
    compile_output: str = ""                      # 编译输出（stdout + stderr）
    compile_latency: float = 0.0                  # 编译耗时（秒）
    compile_timeout: bool = False                 # 编译是否超时
    # 分析阶段
    analysis_performed: bool = False              # 是否执行了错误分析
    error_category: Optional[str] = None          # 错误类别：translation_error / logic_error / both / uncertain
    analysis_confidence: float = 0.0              # 分析置信度
    human_readable_error: str = ""                # 人类可读的错误解释
    root_cause: str = ""                          # 根因分析（中文）
    logic_flaw_location: str = ""                 # 逻辑错误定位（推理中哪一步有问题）
    logic_flaw_why: str = ""                      # 逻辑错误原因
    correct_approach: str = ""                    # 正确的做法
    translation_issue: str = ""                   # 转化问题描述
    fix_prompt_for_ai: str = ""                   # 修正提示词（可反馈给书生AI）
    suggested_fix: str = ""                       # 推荐的修改方法（中文）
    analysis_tokens: int = 0                      # 分析阶段消耗 token
    analysis_latency: float = 0.0                 # 分析耗时（秒）
    analysis_error: Optional[str] = None          # 分析过程中的错误
    # sorry 检测
    sorry_count: int = 0                          # Lean 代码中 sorry 出现次数
    has_incomplete_proof: bool = False            # 是否证明不完整（有 sorry）

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvaluationResult:
    """评测最终结果 - 合并推理和评判的完整信息"""
    problem_id: str                               # 题目ID
    question: str                                 # 题目内容
    domain: Optional[str] = None                  # 知识域
    reference_answer: Optional[str] = None        # 参考答案
    intern_answer: str = ""                       # Intern-S1 的答案
    intern_reasoning: str = ""                    # Intern-S1 的推理过程
    intern_steps: list[str] = field(default_factory=list)  # Intern-S1 的分步推理
    intern_verification: str = ""                 # Intern-S1 的自验证
    is_correct: bool = False                      # 最终正确性判定
    confidence: float = 0.0                       # 评判置信度
    judge_explanation: str = ""                   # 评判解释
    error_type: Optional[str] = None              # 错误类型
    correct_answer_judge: Optional[str] = None    # 评判模型给出的正确答案
    inference_tokens: int = 0                     # 推理消耗 token
    judge_tokens: int = 0                         # 评判消耗 token
    inference_latency: float = 0.0                # 推理耗时
    judge_latency: float = 0.0                    # 评判耗时
    inference_error: Optional[str] = None         # 推理错误
    judge_error: Optional[str] = None             # 评判错误
    lean_verification: Optional[dict] = None      # Lean 验证结果（LeanVerificationResult.to_dict()）

    def to_dict(self) -> dict:
        """将结果转为字典，用于 JSON 序列化"""
        return asdict(self)
