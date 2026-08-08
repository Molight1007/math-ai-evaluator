from __future__ import annotations
"""
题型识别智能体（ClassifierAgent）
===============================

关键词匹配优先（借鉴 math_agent-main 的成功经验，无需额外 API 调用）：
- 20+ 领域关键词映射，高权重关键词（有限域、PDE、Cauchy 等）得分 ×3；
- 若关键词得分 ≥2 则直接采用，否则回退 LLM 分类；
- 全程通过 ``ctx.domain`` 与 trace 对外暴露。
"""

import logging
import re

from .base import BaseAgent, TaskContext

logger = logging.getLogger("MathPilot")

# ============================================================
# 关键词 → 领域映射表（借鉴 math_agent-main）
# ============================================================
_DOMAIN_KEYWORDS: list[dict] = [
    {"name": "抽象代数", "keywords": [
        "有限域", "伽罗瓦", "Galois", "正规子群", "商群",
        "群同态", "环同态", "同构", "理想", "素理想",
        "域扩张", "可分扩张", "本原元素", "代数闭包",
        "群", "环", "域", "模",
    ]},
    {"name": "数学分析", "keywords": [
        "可微", "可导", "可积", "一致收敛", "一致连续", "Lipschitz",
        "中值定理", "泰勒展开", "洛必达", "极值", "最值",
        "广义积分", "反常积分", "无穷积分", "瑕积分",
        "级数", "幂级数", "收敛半径", "逐项", "傅里叶级数",
        "极限", "导数", "微分", "积分", "连续",
        "∫", "lim", "f'",
    ]},
    {"name": "线性代数", "keywords": [
        "Jordan", "若尔当", "特征多项式", "最小多项式", "对角化",
        "幂零", "正定", "半正定", "正交", "酉矩阵",
        "线性空间", "线性变换", "不变子空间", "核", "像", "秩",
        "矩阵", "行列式", "特征值", "特征向量",
        "相似", "合同", "二次型", "标准形",
    ]},
    {"name": "几何", "keywords": [
        "直线方程", "平面方程", "公垂线", "曲线", "曲面",
        "二次曲面", "主轴变换", "配方", "Frenet", "曲率", "挠率", "标架",
        "切向量", "法向量", "参数方程", "坐标变换", "投影",
    ]},
    {"name": "微分几何", "keywords": [
        "黎曼", "流形", "曲率张量", "度量张量", "联络", "Riemann",
        "测地线", "第一基本形式", "第二基本形式",
    ]},
    {"name": "复分析", "keywords": [
        "复变", "解析函数", "柯西", "留数", "共形映射",
        "Cauchy", "亚纯", "辐角", "极点", "Laurent", "奇点",
    ]},
    {"name": "实分析", "keywords": [
        "测度", "勒贝格", "Lebesgue", "可测", "Lp", "L^p",
        "几乎处处", "依测度收敛",
    ]},
    {"name": "偏微分方程", "keywords": [
        "偏微分", "PDE", "波动方程", "热传导", "拉普拉斯", "泊松",
        "u_t", "∂u", "Δu",
    ]},
    {"name": "拓扑学", "keywords": [
        "拓扑", "同胚", "连通性", "紧性", "同伦", "基本群",
        "开集", "闭集", "豪斯多夫",
    ]},
    {"name": "概率论", "keywords": [
        "概率", "随机变量", "期望", "方差", "分布", "马尔可夫",
        "概率论与数理统计",
    ]},
    {"name": "统计学", "keywords": [
        "统计", "假设检验", "回归", "贝叶斯", "t检验", "p值", "置信区间",
        "概率论与数理统计",
    ]},
    {"name": "数论", "keywords": [
        "素数", "整除", "同余", "Diophantine", "费马", "欧拉函数", "二次剩余",
    ]},
    {"name": "组合数学", "keywords": [
        "组合", "排列", "计数", "生成函数", "C(n,k)", "递推", "容斥",
    ]},
    {"name": "图论", "keywords": [
        "图", "树", "路径", "着色", "匹配", "连通图", "欧拉回路", "哈密顿",
    ]},
    {"name": "数值分析", "keywords": [
        "数值", "有限元", "迭代法", "插值", "FEM", "牛顿法",
    ]},
    {"name": "运筹学", "keywords": [
        "线性规划", "整数规划", "动态规划", "网络流", "最优化", "约束优化",
    ]},
    {"name": "不定积分", "keywords": ["不定积分"]},
    {"name": "定积分", "keywords": ["定积分", "定积分的应用"]},
    {"name": "多元函数积分学", "keywords": [
        "重积分", "二重积分", "三重积分", "曲线积分", "曲面积分",
    ]},
    {"name": "常微分方程", "keywords": [
        "常微分", "ODE", "微分方程", "特征方程", "通解", "特解",
    ]},
    {"name": "无穷级数", "keywords": [
        "无穷级数", "数项级数", "函数项级数", "幂级数", "收敛域",
    ]},
]

# 高权重关键词（出现即得分 ×3）
_HI_WEIGHT: frozenset = frozenset({
    "有限域", "PDE", "Cauchy", "Lebesgue", "Riemann", "Galois",
    "Nash", "Frenet", "Jordan", "FEM",
    "同调", "上同调", "黎曼", "同胚", "偏微分", "留数",
    "本原元素", "广义积分", "反常积分", "Jordan标准形",
    "二重积分", "三重积分", "曲线积分", "曲面积分",
    "傅里叶级数", "勒贝格", "伽罗瓦",
})

# 已知有效领域（与 prompts/policy.py 中 DOMAIN_HINTS 键保持一致）
_KNOWN_DOMAINS: frozenset = frozenset({
    "数学分析", "线性代数", "几何", "抽象代数", "复分析",
    "实分析", "偏微分方程", "拓扑学", "微分几何",
    "概率论", "统计学", "概率论与数理统计",
    "数论", "组合数学", "图论", "数值分析", "运筹学",
    "不定积分", "定积分", "定积分的应用",
    "多元函数积分学", "常微分方程", "无穷级数",
    "函数极限与连续", "导数与微分", "微分中值定理",
    "多元函数微分学", "曲线与曲面积分",
    "向量代数与空间解析几何",
    "泛函分析", "离散数学", "数学物理",
})

CLASSIFY_PROMPT = """你是一位数学题目分类专家。请判断以下题目属于哪个数学领域。

可选领域：
函数极限与连续、导数与微分、微分中值定理、不定积分、定积分、定积分的应用、
多元函数微分学、多元函数积分学、曲线与曲面积分、常微分方程、无穷级数、
向量代数与空间解析几何、线性代数、概率论与数理统计、偏微分方程、复分析、
拓扑学、运筹学、代数、数论、几何、概率论、统计学、泛函分析、组合数学、
图论、数值分析、实分析、离散数学、数学物理、抽象代数

请只输出领域名称，不要输出任何其他内容。"""


def _keyword_classify(problem: str) -> tuple[str, int]:
    """关键词匹配分类，返回 (领域名, 得分)"""
    best_domain, best_score = "", 0
    for entry in _DOMAIN_KEYWORDS:
        score = 0
        for kw in entry["keywords"]:
            if kw.lower() in problem.lower():
                score += 3 if kw in _HI_WEIGHT else 1
        if score > best_score:
            best_score = score
            best_domain = entry["name"]
    return best_domain, best_score


class ClassifierAgent(BaseAgent):
    name = "Classifier"

    def run(self, ctx: TaskContext) -> TaskContext:
        if not self.config.enable_domain_hint:
            ctx.domain = None
            self.record(ctx, "classify", "领域提示已禁用，使用通用策略")
            return ctx

        # 第一优先级：关键词匹配（无需 API 调用，借鉴 math_agent-main）
        domain, score = _keyword_classify(ctx.problem)
        if score >= 2:
            # 对已知领域做标准化映射
            for known in _KNOWN_DOMAINS:
                if domain == known or domain in known or known in domain:
                    domain = known
                    break
            ctx.domain = domain
            self.record(ctx, "classify",
                        f"题型分类结果(关键词): {domain} (得分={score})", domain=domain)
            logger.info("Domain classified (keyword): %s (score=%d)", domain, score)
            return ctx

        # 第二优先级：LLM 分类已移除（提速）。
        # 实测 Intern-S 不遵守"只输出领域名"指令，会把整段解题推理当作输出返回，
        # 既浪费一次完整生成时间，还会把噪音文本注入 domain 提示词。
        # 关键词未命中时直接进入低分兜底 / 通用策略。

        # 关键词低分时，若 ≥1 仍采用（比"未知"好）
        if score >= 1:
            ctx.domain = domain
            self.record(ctx, "classify",
                        f"题型分类结果(关键词低分): {domain} (得分={score})", domain=domain)
            logger.info("Domain classified (keyword low): %s (score=%d)", domain, score)
            return ctx

        ctx.domain = None
        self.record(ctx, "classify",
                    f"分类失败（关键词得分={score}，LLM也失败），使用通用策略")
        return ctx
