"""
题型检测模块（Problem Type Detector）
=====================================

基于正则表达式和关键词匹配的快速题型检测器，无需 LLM 调用。

设计目标：
- 支持 18 种数学题型检测（当前已实现 18 种）
- 纯规则检测，零 API 调用，毫秒级响应
- 可扩展架构：新增题型只需添加一个 TypeDetector 条目
- 返回结构化结果：主类型 + 所有匹配类型 + 置信度

使用示例::

    from problem_type_detector import detect, detect_all, ProblemType

    question = "求极限 lim_{x→0} (sin x) / x"
    result = detect(question)
    print(result.primary_type)   # ProblemType.LIMIT
    print(result.confidence)     # 0.95
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ============================================================================
# 题型枚举 — 18 种
# ============================================================================

class ProblemType(Enum):
    """18 种数学题型枚举。

    命名规则：英文标识符，中文标签用于展示。
    新增题型：在此枚举中添加成员，并在 _TYPE_DETECTORS 中配置检测规则即可。
    """
    # ── 按作答形式分类 ──
    PROOF = auto()              # 证明题：证明、求证、推导
    COMPUTATION = auto()        # 计算题：计算、求值、化简
    MULTIPLE_CHOICE = auto()    # 选择题：A/B/C/D 选项
    FILL_IN_BLANK = auto()      # 填空题：下划线/括号留空
    TRUE_FALSE = auto()         # 判断题：判断正误/对错

    # ── 按核心运算分类 ──
    EQUATION_SOLVING = auto()   # 方程求解：解方程、解方程组
    LIMIT = auto()              # 极限题：求极限、数列极限
    DERIVATIVE = auto()         # 求导/微分题：求导、微分、偏导数
    INTEGRAL = auto()           # 积分题：不定积分、定积分
    MATRIX = auto()             # 矩阵/行列式：矩阵运算、行列式

    # ── 按数学领域分类 ──
    PROBABILITY = auto()        # 概率题：概率、随机变量、期望
    STATISTICS = auto()         # 统计题：假设检验、参数估计、回归
    GEOMETRY = auto()           # 几何题：平面几何、解析几何、空间几何
    NUMBER_THEORY = auto()      # 数论题：整除、同余、素数
    INEQUALITY = auto()         # 不等式题：证明不等式、解不等式
    SERIES = auto()             # 级数题：无穷级数、收敛性、幂级数
    OPTIMIZATION = auto()       # 最优化题：极值、最值、线性规划
    APPLICATION = auto()        # 应用题：实际背景、物理/经济建模

    def label(self) -> str:
        """返回中文标签。"""
        return _TYPE_LABELS.get(self, self.name)

    def category(self) -> str:
        """返回所属大类。"""
        for cat, members in _TYPE_CATEGORIES.items():
            if self in members:
                return cat
        return "其他"


_TYPE_LABELS: dict[ProblemType, str] = {
    ProblemType.PROOF:            "证明题",
    ProblemType.COMPUTATION:      "计算题",
    ProblemType.MULTIPLE_CHOICE:  "选择题",
    ProblemType.FILL_IN_BLANK:    "填空题",
    ProblemType.TRUE_FALSE:       "判断题",
    ProblemType.EQUATION_SOLVING: "方程求解",
    ProblemType.LIMIT:            "极限题",
    ProblemType.DERIVATIVE:       "求导/微分题",
    ProblemType.INTEGRAL:         "积分题",
    ProblemType.MATRIX:           "矩阵/行列式题",
    ProblemType.PROBABILITY:      "概率题",
    ProblemType.STATISTICS:       "统计题",
    ProblemType.GEOMETRY:         "几何题",
    ProblemType.NUMBER_THEORY:    "数论题",
    ProblemType.INEQUALITY:       "不等式题",
    ProblemType.SERIES:           "级数题",
    ProblemType.OPTIMIZATION:     "最优化题",
    ProblemType.APPLICATION:      "应用题",
}

_TYPE_CATEGORIES: dict[str, list[ProblemType]] = {
    "作答形式": [
        ProblemType.PROOF, ProblemType.COMPUTATION,
        ProblemType.MULTIPLE_CHOICE, ProblemType.FILL_IN_BLANK,
        ProblemType.TRUE_FALSE,
    ],
    "核心运算": [
        ProblemType.EQUATION_SOLVING, ProblemType.LIMIT,
        ProblemType.DERIVATIVE, ProblemType.INTEGRAL,
        ProblemType.MATRIX,
    ],
    "数学领域": [
        ProblemType.PROBABILITY, ProblemType.STATISTICS,
        ProblemType.GEOMETRY, ProblemType.NUMBER_THEORY,
        ProblemType.INEQUALITY, ProblemType.SERIES,
        ProblemType.OPTIMIZATION, ProblemType.APPLICATION,
    ],
}


# ============================================================================
# 检测规则数据结构
# ============================================================================

@dataclass
class TypeDetector:
    """单个题型的检测规则。

    Attributes:
        ptype: 对应的题型枚举值。
        priority: 优先级（数值越大越优先，用于多类型冲突时的裁决）。
        patterns: 正则表达式列表，任一命中即视为匹配。
        keywords: 关键词列表（简化中文匹配，不区分大小写）。
        negative_patterns: 排除性正则，命中则取消该类型的匹配（防误判）。
        min_confidence: 仅通过关键词命中时的基础置信度。
        description: 该题型的简要说明。
    """
    ptype: ProblemType
    priority: int = 50
    patterns: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    negative_patterns: list[str] = field(default_factory=list)
    min_confidence: float = 0.60
    description: str = ""


# ============================================================================
# 18 种题型的检测规则配置
# ============================================================================

_TYPE_DETECTORS: list[TypeDetector] = [
    # ══════════════════════════════════════════════════════════════════
    # 作答形式类
    # ══════════════════════════════════════════════════════════════════
    TypeDetector(
        ptype=ProblemType.PROOF,
        priority=90,
        patterns=[
            # 中文证明指令
            r"证明[：:\s]",
            r"求证[：:\s]",
            r"试证[：:\s]",
            r"请证明",
            r"证明下列",
            # 英文证明指令
            r"\bprove\b[：:\s]",
            r"\bshow\s+that\b",
            r"\bdemonstrate\b[：:\s]",
            r"\bverify\b[：:\s]",
            r"\bjustify\b[：:\s]",
        ],
        keywords=[
            "证明", "求证", "试证",
        ],
        negative_patterns=[
            # "证明下列等式成立"中的"求解"不应触发证明题
        ],
        min_confidence=0.95,
        description="要求证明某个命题、定理或结论成立",
    ),
    TypeDetector(
        ptype=ProblemType.MULTIPLE_CHOICE,
        priority=85,
        patterns=[
            # 选项格式
            r"[（(]\s*[A-Da-d]\s*[）)]",
            r"[A-Da-d][\.\、\)]\s*\S",
            r"选择题",
            r"单选",
            r"多选",
            r"四个?选项",
            r"下列选项[中正]",
        ],
        keywords=[
            "选择题", "单选题", "多选题", "单项选择", "多项选择",
        ],
        min_confidence=0.95,
        description="给出多个选项，选择正确答案",
    ),
    TypeDetector(
        ptype=ProblemType.FILL_IN_BLANK,
        priority=82,
        patterns=[
            r"填空",
            r"_{3,}",                   # 长下划线
            r"（\s*）",                  # 空括号
            r"\(\s*\)",                  # 空英文括号
            r"\[空格\]",
            r"____+",
        ],
        keywords=[
            "填空题", "填空", "填入",
        ],
        min_confidence=0.90,
        description="题目中有空白处需要填写答案",
    ),
    TypeDetector(
        ptype=ProblemType.TRUE_FALSE,
        priority=80,
        patterns=[
            r"判断.*[正对错]误",
            r"[正对错]误.*判断",
            r"判断.*(?:正确|错误|对错)",
            r"说法.*(?:正确|错误)",
            r"\b(?:true|false)\b",
            r"是非题",
        ],
        keywords=[
            "判断题", "判断正误", "判断对错", "是非题",
        ],
        min_confidence=0.90,
        description="判断命题或说法的正误",
    ),
    TypeDetector(
        ptype=ProblemType.COMPUTATION,
        priority=75,
        patterns=[
            r"计算[：:\s]",
            r"[求计]算下列",
            r"求值[：:\s]",
            r"求\s*[：:\s]",
            r"\b(?:calculate|compute|evaluate|find)\b",
            r"化简[：:\s]",
            r"求(?:出|得)",
        ],
        keywords=[
            "计算", "求值", "求", "算出", "化简",
        ],
        min_confidence=0.60,
        description="需要通过数值计算得出结果",
    ),

    # ══════════════════════════════════════════════════════════════════
    # 核心运算类
    # ══════════════════════════════════════════════════════════════════
    TypeDetector(
        ptype=ProblemType.EQUATION_SOLVING,
        priority=78,
        patterns=[
            r"解方程",
            r"求解.*方程",
            r"求.*根",
            r"解(?:下列)?方程组",
            r"\bsolve\b.*equation",
            r"\broot[s]?\b.*\bequation\b",
            r"一元二次",
            r"一元三次",
            r"线性方程组",
            r"齐次方程",
        ],
        keywords=[
            "解方程", "方程", "方程组", "求根", "求解",
            "一元二次", "一元三次", "齐次方程",
        ],
        negative_patterns=[
            # 避免"微分方程"被误判为普通方程（微分方程另有处理）
        ],
        min_confidence=0.80,
        description="求解方程或方程组的根/解",
    ),
    TypeDetector(
        ptype=ProblemType.LIMIT,
        priority=80,
        patterns=[
            r"极限",
            r"\\lim\b",
            r"\\lim_",
            r"\blim\b",
            r"趋近?于",
            r"收敛",
            r"无穷小",
            r"无穷大",
            r"\bconverge",
            r"\bdivergent?\b",
        ],
        keywords=[
            "极限", "趋近", "收敛", "发散", "无穷小", "无穷大",
        ],
        negative_patterns=[
            r"级数",       # "判断级数收敛性" 应属于级数题而非极限题
            r"幂级数",
        ],
        min_confidence=0.90,
        description="求函数极限、数列极限或判断收敛性",
    ),
    TypeDetector(
        ptype=ProblemType.DERIVATIVE,
        priority=80,
        patterns=[
            r"求导",
            r"导数",
            r"微分[^方中]",
            r"偏导",
            r"\bf'",
            r"f''",
            r"\\frac\{d\}",
            r"d/dx",
            r"\bderivative\b",
            r"\bdifferentiate\b",
            r"梯度",
            r"方向导数",
            r"Hess[ei]an",
            r"Jacobi",
        ],
        keywords=[
            "求导", "导数", "微分", "偏导", "梯度",
        ],
        negative_patterns=[
            r"微分方程",       # 微分方程应属于方程类或独立类
            r"微分中值定理",    # 中值定理类
        ],
        min_confidence=0.85,
        description="求函数的导数、偏导数或微分",
    ),
    TypeDetector(
        ptype=ProblemType.INTEGRAL,
        priority=80,
        patterns=[
            r"积分",
            r"∫",
            r"\\int\b",
            r"\\iint\b",
            r"\\iiint\b",
            r"\\oint\b",
            r"\bintegral\b",
            r"\bintegrate\b",
            r"原函数",
            r"不定积分",
            r"定积分",
            r"重积分",
            r"曲线积分",
            r"曲面积分",
        ],
        keywords=[
            "积分", "不定积分", "定积分", "原函数",
            "二重积分", "三重积分", "曲线积分", "曲面积分",
        ],
        min_confidence=0.90,
        description="计算不定积分、定积分或多重积分",
    ),
    TypeDetector(
        ptype=ProblemType.MATRIX,
        priority=80,
        patterns=[
            r"矩阵",
            r"行列式",
            r"特征值",
            r"特征向量",
            r"对角化",
            r"逆矩阵",
            r"转置",
            r"\bmatrix\b",
            r"\bdeterminant\b",
            r"\beigenvalue\b",
            r"\beigenvector\b",
            r"秩",
            r"线性变换",
            r"二次型",
            r"正交",
        ],
        keywords=[
            "矩阵", "行列式", "特征值", "特征向量",
            "逆矩阵", "线性变换", "二次型",
        ],
        min_confidence=0.85,
        description="矩阵运算、行列式计算、特征值与特征向量",
    ),

    # ══════════════════════════════════════════════════════════════════
    # 数学领域类
    # ══════════════════════════════════════════════════════════════════
    TypeDetector(
        ptype=ProblemType.PROBABILITY,
        priority=78,
        patterns=[
            r"概率",
            r"随机变量",
            r"分布列",
            r"分布函数",
            r"密度函数",
            r"数学期望",
            r"方差",
            r"\bprobability\b",
            r"\brandom\b",
            r"\bdistribution\b",
            r"\bexpectation\b",
            r"\bvariance\b",
            r"古典概型",
            r"几何概型",
            r"条件概率",
            r"全概率",
            r"贝叶斯",
            r"二项分布",
            r"正态分布",
            r"泊松分布",
        ],
        keywords=[
            "概率", "随机变量", "期望", "方差", "分布",
            "古典概型", "条件概率", "贝叶斯",
        ],
        negative_patterns=[
            r"数理统计",         # 统计题
            r"假设检验",
            r"参数估计",
            r"置信区间",
        ],
        min_confidence=0.85,
        description="概率计算、随机变量分布、数字特征",
    ),
    TypeDetector(
        ptype=ProblemType.STATISTICS,
        priority=78,
        patterns=[
            r"统计",
            r"假设检验",
            r"参数估计",
            r"置信区间",
            r"回归",
            r"相关性?分析",
            r"方差分析",
            r"\bANOVA\b",
            r"\bhypothesis\b.*\btest\b",
            r"\bestimat",
            r"\bconfidence\b.*\binterval\b",
            r"\bregression\b",
            r"样本",
            r"总体",
            r"抽样",
            r"最小二乘",
            r"最大似然",
            r"矩估计",
        ],
        keywords=[
            "统计", "假设检验", "参数估计", "回归分析",
            "置信区间", "方差分析", "样本", "抽样",
        ],
        min_confidence=0.85,
        description="统计分析、假设检验、参数估计、回归分析",
    ),
    TypeDetector(
        ptype=ProblemType.GEOMETRY,
        priority=75,
        patterns=[
            r"几何",
            r"三角形",
            r"四边形",
            r"圆(?!周率)",
            r"椭圆",
            r"双曲线",
            r"抛物线",
            r"平面",
            r"空间.*坐标",
            r"向量.*坐标",
            r"\bgeometry\b",
            r"\btriangle\b",
            r"\bcircle\b",
            r"\bangle\b",
            r"\barea\b",
            r"\bvolume\b",
            r"\bperimeter\b",
            r"面积",
            r"体积",
            r"周长",
            r"坐标",
            r"切线",
            r"法线",
            r"曲面",
        ],
        keywords=[
            "几何", "三角形", "圆", "椭圆", "双曲线", "抛物线",
            "平面", "空间", "坐标", "面积", "体积",
        ],
        negative_patterns=[
            r"概率密度",     # 避免"面积"在概率题中误判
            r"分布曲线",
        ],
        min_confidence=0.70,
        description="平面几何、解析几何、空间几何问题",
    ),
    TypeDetector(
        ptype=ProblemType.NUMBER_THEORY,
        priority=76,  # 略高于计算题(75)，避免"求素数之和"被误判为纯计算题
        patterns=[
            r"数论",
            r"整除",
            r"同余",
            r"素数",
            r"质数",
            r"合数",
            r"最大公约数",
            r"最小公倍数",
            r"\bgcd\b",
            r"\blcm\b",
            r"模\s*\d+",
            r"mod\b",
            r"\bprime\b",
            r"\bdivisible\b",
            r"\bcongruen",
            r"费马",
            r"欧拉函数",
            r"丢番图",
            r"不定方程",
            r"无理数",
            r"有理数.*证明",
        ],
        keywords=[
            "数论", "整除", "同余", "素数", "质数",
            "最大公约数", "最小公倍数", "费马", "无理数",
        ],
        min_confidence=0.85,
        description="整除性、同余、素数性质等数论问题",
    ),
    TypeDetector(
        ptype=ProblemType.INEQUALITY,
        priority=78,
        patterns=[
            r"不等式",
            r"证明.*[≥≤><]",
            r"求证.*[≥≤><]",
            r"解不等式",
            r"\binequalit",
            r"[≥≤]",
            r"\\geq",
            r"\\leq",
            r"\\geqslant",
            r"\\leqslant",
            r"柯西",
            r"均值不等式",
            r"AM-GM",
            r"排序不等式",
            r"切比雪夫",
        ],
        keywords=[
            "不等式", "柯西", "均值不等式",
        ],
        min_confidence=0.80,
        description="证明或求解不等式",
    ),
    TypeDetector(
        ptype=ProblemType.SERIES,
        priority=83,  # 高于极限题(80)，避免"判断级数收敛性"被误判为极限题
        patterns=[
            r"级数",
            r"无穷级数",
            r"幂级数",
            r"收敛半径",
            r"收敛域",
            r"傅里[立叶]",
            r"Fourier",
            r"泰勒.*级数",
            r"\bseries\b",
            r"\bconvergence\b.*\bseries\b",
            r"∑",
            r"\\sum",
            r"交错级数",
            r"正项级数",
            r"函数项级数",
            r"一致收敛",
        ],
        keywords=[
            "级数", "无穷级数", "幂级数", "收敛半径",
            "傅里叶", "泰勒级数", "交错级数",
        ],
        min_confidence=0.85,
        description="无穷级数的收敛性、幂级数展开、傅里叶级数",
    ),
    TypeDetector(
        ptype=ProblemType.OPTIMIZATION,
        priority=78,
        patterns=[
            r"最[大小]值",
            r"极值",
            r"最优",
            r"线性规划",
            r"非线性规划",
            r"最优化",
            r"\boptimiz",
            r"\bmaximize\b",
            r"\bminimize\b",
            r"\bmaximum\b",
            r"\bminimum\b",
            r"\bextrem",
            r"约束条件",
            r"可行域",
            r"拉格朗日乘",
            r"KKT",
            r"目标函数",
        ],
        keywords=[
            "最值", "最大值", "最小值", "极值", "最优化",
            "线性规划", "拉格朗日",
        ],
        negative_patterns=[
            r"极值点.*导数",     # 这是求导题
            r"单调.*极值",       # 导数应用题
        ],
        min_confidence=0.75,
        description="求函数最值、线性/非线性规划等最优化问题",
    ),
    TypeDetector(
        ptype=ProblemType.APPLICATION,
        priority=70,
        patterns=[
            r"应用",
            r"应用题",
            r"实际.*问题",
            r"某.*公司",
            r"某.*工厂",
            r"某.*学校",
            r"某.*工程",
            r"经济学",
            r"物理.*问题",
            r"应用题",
            r"\bapplication\b",
            r"\breal.world\b",
            r"\bpractical\b",
        ],
        keywords=[
            "应用题", "实际问题", "应用题",
        ],
        negative_patterns=[
            r"定积分的应用",     # 这算积分题
        ],
        min_confidence=0.55,
        description="具有实际背景的应用建模问题",
    ),
]


# ============================================================================
# 检测结果数据结构
# ============================================================================

@dataclass
class DetectionResult:
    """题型检测结果。

    Attributes:
        primary_type: 最高置信度的题型。
        confidence: 主类型的置信度（0~1）。
        all_matches: 所有匹配到的题型及其置信度列表，按置信度降序排列。
        question_preview: 题干前 80 字符（便于调试）。
    """
    primary_type: Optional[ProblemType]
    confidence: float
    all_matches: list[tuple[ProblemType, float]]
    question_preview: str = ""

    @property
    def primary_label(self) -> str:
        """主类型的中文标签。"""
        if self.primary_type is None:
            return "未识别"
        return self.primary_type.label()

    @property
    def primary_category(self) -> str:
        """主类型的大类名。"""
        if self.primary_type is None:
            return "未知"
        return self.primary_type.category()

    def is_type(self, ptype: ProblemType) -> bool:
        """检查是否匹配指定题型。"""
        return self.primary_type is ptype

    def has_type(self, ptype: ProblemType) -> bool:
        """检查是否包含指定题型（主类型或次要匹配）。"""
        if self.primary_type is ptype:
            return True
        return any(t == ptype for t, _ in self.all_matches)

    def type_labels(self) -> list[str]:
        """返回所有匹配题型的中文标签列表。"""
        return [t.label() for t, _ in self.all_matches]


# ============================================================================
# 核心检测逻辑
# ============================================================================

class ProblemTypeDetector:
    """题型检测器。

    使用预配置的规则对题干进行快速检测，返回结构化的题型结果。

    >>> detector = ProblemTypeDetector()
    >>> result = detector.detect("求极限 lim_{x→0} (sin x)/x")
    >>> result.primary_label
    '极限题'
    """

    def __init__(self, detectors: Optional[list[TypeDetector]] = None):
        """初始化检测器。

        Args:
            detectors: 自定义检测规则列表。默认使用内置的 18 种题型规则。
        """
        self._detectors: list[TypeDetector] = detectors or list(_TYPE_DETECTORS)
        # 预编译所有正则
        self._compiled: list[tuple[TypeDetector, list[re.Pattern], list[re.Pattern]]] = []
        for d in self._detectors:
            pos = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in d.patterns]
            neg = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in d.negative_patterns]
            self._compiled.append((d, pos, neg))

    def detect(self, question: str) -> DetectionResult:
        """检测题目的主要题型。

        返回置信度最高的匹配结果。如果没有匹配到任何题型，返回 primary_type=None。

        Args:
            question: 题目文本。

        Returns:
            DetectionResult 包含主类型、置信度和所有匹配项。
        """
        if not question or not question.strip():
            return DetectionResult(
                primary_type=None,
                confidence=0.0,
                all_matches=[],
                question_preview="",
            )

        question_lower = question.lower()
        all_matches: list[tuple[ProblemType, float, int]] = []  # (type, conf, priority)

        for detector, pos_patterns, neg_patterns in self._compiled:
            # 1. 先检查排除规则
            neg_hit = False
            for neg_re in neg_patterns:
                if neg_re.search(question):
                    neg_hit = True
                    break
            if neg_hit:
                continue

            # 2. 检查正则匹配
            regex_hits = 0
            for pos_re in pos_patterns:
                if pos_re.search(question):
                    regex_hits += 1
                    break  # 有一个命中即可

            # 3. 检查关键词匹配
            keyword_hits = 0
            for kw in detector.keywords:
                if kw.lower() in question_lower:
                    keyword_hits += 1

            # 4. 计算置信度
            if regex_hits > 0:
                # 正则命中 → 高置信度
                confidence = max(detector.min_confidence, 0.85)
                # 多个正则命中 → 更高置信度
                if regex_hits >= 2:
                    confidence = min(confidence + 0.05, 0.99)
            elif keyword_hits >= 2:
                confidence = max(detector.min_confidence, 0.70)
            elif keyword_hits == 1:
                confidence = detector.min_confidence
            else:
                continue  # 未匹配

            all_matches.append((detector.ptype, confidence, detector.priority))

        # 5. 排序：优先级 > 置信度（优先使用高优先级的题型裁决）
        all_matches.sort(key=lambda x: (x[2], x[1]), reverse=True)

        # 6. 同类型合并（去重，保留最高置信度）
        seen: dict[ProblemType, float] = {}
        for pt, conf, pri in all_matches:
            if pt not in seen or conf > seen[pt]:
                seen[pt] = conf

        merged = sorted(seen.items(), key=lambda x: x[1], reverse=True)

        primary = merged[0][0] if merged else None
        primary_conf = merged[0][1] if merged else 0.0

        return DetectionResult(
            primary_type=primary,
            confidence=primary_conf,
            all_matches=merged,
            question_preview=question[:80],
        )

    def detect_all(self, question: str) -> DetectionResult:
        """检测题目涉及的所有题型（detect 的别名，语义更清晰）。"""
        return self.detect(question)

    def get_type_info(self, ptype: ProblemType) -> Optional[TypeDetector]:
        """获取指定题型的检测规则配置。"""
        for d in self._detectors:
            if d.ptype is ptype:
                return d
        return None

    def list_types(self) -> list[ProblemType]:
        """列出所有已注册的题型。"""
        return [d.ptype for d in self._detectors]

    def add_detector(self, detector: TypeDetector) -> None:
        """动态添加新的题型检测规则。

        示例::

            detector.add_detector(TypeDetector(
                ptype=ProblemType.NEW_TYPE,
                priority=70,
                patterns=[r"新模式"],
                keywords=["新模式"],
            ))
        """
        self._detectors.append(detector)
        pos = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in detector.patterns]
        neg = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in detector.negative_patterns]
        self._compiled.append((detector, pos, neg))


# ============================================================================
# 模块级便捷函数
# ============================================================================

_default_detector: Optional[ProblemTypeDetector] = None


def _get_detector() -> ProblemTypeDetector:
    """获取全局默认检测器（懒加载单例）。"""
    global _default_detector
    if _default_detector is None:
        _default_detector = ProblemTypeDetector()
    return _default_detector


def detect(question: str) -> DetectionResult:
    """检测题目的主要题型（便捷函数）。

    >>> detect("求极限 lim_{x→0} sin(x)/x").primary_label
    '极限题'
    """
    return _get_detector().detect(question)


def detect_all(question: str) -> DetectionResult:
    """检测题目涉及的所有题型（便捷函数）。"""
    return _get_detector().detect_all(question)


def is_type(question: str, ptype: ProblemType) -> bool:
    """快速判断题目是否属于指定题型。"""
    return _get_detector().detect(question).is_type(ptype)


def has_type(question: str, ptype: ProblemType) -> bool:
    """快速判断题目是否包含指定题型。"""
    return _get_detector().detect(question).has_type(ptype)


def list_all_types() -> list[ProblemType]:
    """列出所有支持的题型。"""
    return _get_detector().list_types()


# ============================================================================
# 兼容性导出：与 intern_s1.is_proof_problem 的桥接
# ============================================================================

def is_proof_problem(question: str) -> bool:
    """题干是否要求证明/推导（兼容 intern_s1 旧接口）。

    这是 intern_s1.is_proof_problem 的直接替代，返回 bool。
    """
    return is_type(question, ProblemType.PROOF)


# ============================================================================
# 自测入口
# ============================================================================

if __name__ == "__main__":
    test_cases = [
        ("求极限 lim_{x→0} (sin x) / x", ProblemType.LIMIT),
        ("证明：对于任意正整数 n，n^3 - n 能被 6 整除", ProblemType.PROOF),
        ("设 A 为 3 阶矩阵，|A| = 2，求 |2A|", ProblemType.MATRIX),
        ("计算 ∫₀¹ x² dx", ProblemType.INTEGRAL),
        ("求函数 f(x) = x³ - 3x 的极值", ProblemType.OPTIMIZATION),
        ("解方程 x² - 5x + 6 = 0", ProblemType.EQUATION_SOLVING),
        ("从 1-10 中随机取两个数，求其和为偶数的概率", ProblemType.PROBABILITY),
        ("判断级数 ∑(1/n²) 的收敛性", ProblemType.SERIES),
        ("设 f(x) = x²，求 f'(2)", ProblemType.DERIVATIVE),
        ("下列选项中，正确的是：A. ... B. ... C. ... D. ...", ProblemType.MULTIPLE_CHOICE),
        ("某工厂生产一种产品，固定成本 10000 元，每件可变成本 50 元，售价 80 元，求盈亏平衡点", ProblemType.APPLICATION),
        ("求解不等式 x² - 4 > 0", ProblemType.INEQUALITY),
        ("已知三角形的三边长分别为 3, 4, 5，求其面积", ProblemType.GEOMETRY),
        ("证明 √2 是无理数", ProblemType.PROOF),  # "证明" 为主导任务，数论为次要匹配
        ("求 100 以内的所有素数之和", ProblemType.NUMBER_THEORY),
        ("设总体 X ~ N(μ, σ²)，样本容量为 n，求 μ 的 95% 置信区间", ProblemType.STATISTICS),
        ("判断下列说法是否正确：f(x) 可导则 f(x) 连续", ProblemType.TRUE_FALSE),
        ("在空白处填入适当的值：x² + 6x + ___ = (x + 3)²", ProblemType.FILL_IN_BLANK),
    ]

    detector = ProblemTypeDetector()
    correct = 0
    total = len(test_cases)

    print("=" * 70)
    print("题型检测器 - 自测")
    print("=" * 70)

    for question, expected_type in test_cases:
        result = detector.detect(question)
        status = "OK" if result.primary_type is expected_type else "MISS"
        if result.primary_type is expected_type:
            correct += 1

        expected_str = expected_type.label() if expected_type else "None"
        actual_str = result.primary_label if result.primary_type else "未识别"
        all_types = ", ".join(
            f"{t.label()}({c:.2f})" for t, c in result.all_matches[:3]
        )

        print(f"\n{status} 题目: {question[:60]}")
        print(f"   期望: {expected_str}  |  实际: {actual_str}  |  置信度: {result.confidence:.2f}")
        print(f"   所有匹配: {all_types}")

    print(f"\n{'=' * 70}")
    print(f"准确率: {correct}/{total} = {correct/total*100:.1f}%")

    # 列出所有支持的题型
    print(f"\n已注册题型 ({len(detector.list_types())} 种):")
    category_width = max(len(t.category()) for t in detector.list_types())
    for t in detector.list_types():
        info = detector.get_type_info(t)
        print(f"  [{t.category():{category_width}}] {t.label():10s}  (置信度≥{info.min_confidence:.2f})")
