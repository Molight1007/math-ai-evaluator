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
    """推理结果 - Intern-S1 模型对单题的推理输出

    支持两种模式：
    1. 单候选模式（旧）：answer / reasoning / steps / verification
    2. 多候选模式（新）：模型内部生成 3 个候选答案，自评估后选出最优
    """
    problem_id: str                               # 对应的题目ID
    question: str                                 # 原题内容
    answer: str = ""                              # 模型给出的最终答案（多候选模式 = 选出的最优答案）
    reasoning: str = ""                           # 推理过程文本（多候选模式 = 选择理由）
    steps: list[str] = field(default_factory=list)# 分步骤推理列表
    verification: str = ""                        # 自验证过程
    raw_response: str = ""                        # API 返回的原始响应
    tokens_used: int = 0                          # 推理消耗的 token 数
    latency_seconds: float = 0.0                  # 推理耗时（秒）
    error: Optional[str] = None                   # 推理过程中的错误信息
    sample_index: int = 0                         # 多样本编号（0-based，单样本模式下为0）
    # 多候选模式专用字段
    candidates: Optional[list[dict]] = None       # 候选答案列表 [{"index":0,"answer":"...","reasoning":"...","confidence":0.9}, ...]
    selected_candidate_index: Optional[int] = None  # 最终选中的候选编号
    selection_reasoning: str = ""                 # 选择最优候选的理由
    # 自审核相关字段
    review_passed: Optional[bool] = None          # 自审核是否通过（None=未执行审核）
    review_feedback: Optional[dict] = None        # 审核反馈详情 {"verdict","scores","issues","suggestions","summary"}
    review_attempts: int = 0                      # 审核/重试总次数
    review_tokens_used: int = 0                   # 审核消耗 token 数
    review_latency_seconds: float = 0.0           # 审核耗时（秒）
    total_tokens_used: int = 0                    # 总 token（推理+审核+重试）
    total_latency_seconds: float = 0.0            # 总耗时（推理+审核+重试，秒）
    skipped: bool = False                         # 是否因超时等原因被跳过
    skip_reason: str = ""                         # 跳过原因（如 "timeout: 600s"）


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
    lean_verification: Optional[dict] = None      # Lean 验证结果（LeanVerificationResult.to_dict()）
    sample_index: int = 0                         # 多样本编号（0-based，单样本模式下为0）
    # 自审核相关字段（从 InferenceResult 透传）
    review_passed: Optional[bool] = None          # 自审核是否通过
    review_attempts: int = 0                      # 审核/重试次数
    total_tokens_used: int = 0                    # 总 token（推理+审核）
    skipped: bool = False                         # 是否因超时等原因被跳过
    skip_reason: str = ""                         # 跳过原因（如 "timeout: 600s"）

    def to_dict(self) -> dict:
        """将结果转为字典，用于 JSON 序列化"""
        return asdict(self)


@dataclass
class ANDORDAG:
    """AND-OR DAG 表示的数学证明结构"""
    problem_id: str = ""
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)


@dataclass
class LeanVerificationResult:
    """Lean 4 验证结果"""
    problem_id: str = ""
    passed: bool = False
    lean_code: str = ""
    error_message: str = ""
    latency_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)
