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

    def to_dict(self) -> dict:
        """将结果转为字典，用于 JSON 序列化"""
        return asdict(self)
