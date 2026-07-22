"""
数学智能体评测器 - 数据模型定义
定义整个评测流程中使用的核心数据结构。
"""
from dataclasses import dataclass, field, asdict
from typing import Optional


# ==================== AND-OR DAG 数据模型 ====================

@dataclass
class ANDORDAGNode:
    """AND-OR DAG 树节点。

    表示证明蓝图分解中的一个节点。节点有三种类型：
    - OR：待证明的目标（需要选择一种分解方案）
    - AND：分解方案（所有子目标都需要证明）
    - LEAF：叶子节点（sorry 占位或已验证的子目标）

    属性:
        node_id: 节点唯一标识
        node_type: 节点类型，取值为 "OR" / "AND" / "LEAF"
        label: 节点显示标签（如"证明目标"、"子引理1"）
        statement: 节点对应的数学命题文本
        status: 节点状态，取值为 "open" / "decomposed" / "verified" / "sorry"
        children: 子节点 ID 列表
        detail: 节点补充说明（可选，如子引理的推理思路）
    """
    node_id: str
    node_type: str  # "OR" | "AND" | "LEAF"
    label: str = ""
    statement: str = ""
    status: str = "open"  # "open" | "decomposed" | "verified" | "sorry"
    children: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict:
        """将节点转为可 JSON 序列化的字典。"""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "label": self.label,
            "statement": self.statement,
            "status": self.status,
            "children": self.children,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ANDORDAGNode":
        """从字典还原节点对象。"""
        return cls(
            node_id=data.get("node_id", ""),
            node_type=data.get("node_type", "LEAF"),
            label=data.get("label", ""),
            statement=data.get("statement", ""),
            status=data.get("status", "open"),
            children=data.get("children", []),
            detail=data.get("detail", ""),
        )


@dataclass
class ANDORDAG:
    """AND-OR DAG 蓝图分解树。

    表示一个证明被分解为子引理的 AND-OR 树形结构。
    根节点为待证明的总目标（OR 类型），子节点为分解方案或叶子引理。

    属性:
        root_id: 根节点 ID
        nodes: 节点字典，key 为 node_id，value 为 ANDORDAGNode
    """
    root_id: str = ""
    nodes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """将 DAG 树转为可 JSON 序列化的字典。

        返回:
            {"root_id": str, "nodes": {node_id: node_dict, ...}}
        """
        return {
            "root_id": self.root_id,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ANDORDAG":
        """从字典还原 DAG 树对象。

        参数:
            data: to_dict() 输出的字典

        返回:
            ANDORDAG 实例。若 data 为空或缺失关键字段，返回空 DAG。
        """
        if not data or not isinstance(data, dict):
            return cls()
        root_id = data.get("root_id", "")
        raw_nodes = data.get("nodes", {})
        nodes = {}
        for nid, ndata in raw_nodes.items():
            if isinstance(ndata, dict):
                nodes[nid] = ANDORDAGNode.from_dict(ndata)
            elif isinstance(ndata, ANDORDAGNode):
                nodes[nid] = ndata
        return cls(root_id=root_id, nodes=nodes)

    def is_empty(self) -> bool:
        """检查 DAG 是否为空（无有效节点）。"""
        return not self.root_id or not self.nodes


# ==================== 核心数据模型 ====================

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
    # 反馈修正
    revision_attempts: int = 0                    # 反馈修正尝试次数
    revised_lean_code: str = ""                   # 修正后的 Lean 代码（最终版本）
    # 蓝图分解
    dag: Optional[dict] = None                    # AND-OR DAG 蓝图分解（ANDORDAG.to_dict()）

    def to_dict(self) -> dict:
        """将结果转为字典，用于 JSON 序列化。"""
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
