"""简化版领域 skill 加载器：基于关键词匹配 top-1 学科，返回 skill.md 全文。

从 ICMA/utils/skills_loader.py 提取 DOMAIN_ALIASES 关键词表与匹配逻辑，
不含 LLM 分类器与 embedding 索引，与融合建议"仅关键词 top1，不用 LLM 分类器"一致。
"""
import re
from pathlib import Path

SKILLS_BASE = Path(__file__).resolve().parent / "skills"

DOMAIN_ALIASES = {
    "概率论": [
        "依概率", "依分布", "几乎必然", "随机变量", "分布函数", "概率收敛",
        "中心极限定理", "大数定律", "Slutsky", "贝叶斯", "全概率",
        "二项分布", "泊松分布", "指数分布", "正态分布", "矩母函数", "特征函数",
    ],
    "随机过程": [
        "Brownian", "布朗", "Wiener", "首达时", "停时", "鞅", "Markov链",
        "马尔可夫", "Poisson过程", "泊松过程", "生灭过程", "更新过程", "随机游走",
    ],
    "数学分析": [
        "一致收敛", "函数列", "函数项级数", "逐点收敛", "极限函数", "可导",
        "导数列", "Taylor", "泰勒", "幂级数", "含参积分", "广义积分", "上确界",
    ],
    "统计推断": [
        "最大似然", "MLE", "置信区间", "假设检验", "拒绝域", "显著性水平",
        "p值", "p-value", "样本", "估计量", "无偏", "方差估计",
        "极大似然", "矩估计", "Fisher", "C-R", "第二类错误", "功效",
        "似然比", "检验统计量", "临界值",
    ],
    "复分析": ["留数", "解析", "全纯", "Cauchy", "柯西", "Laurent", "洛朗", "极点"],
    "抽象代数": ["有限域", "群", "环", "理想", "同态", "子群", "正规子群", "域扩张"],
    "高等代数": ["矩阵", "特征值", "特征向量", "线性空间", "秩", "行列式", "二次型"],
    "常微分方程": ["常微分", "ODE", "初值问题", "通解", "特解", "Wronskian"],
    "偏微分方程": ["偏微分", "PDE", "热方程", "波动方程", "Laplace方程", "边值问题"],
    "泛函分析": ["Banach", "Hilbert", "有界线性算子", "泛函", "弱收敛", "紧算子"],
    "拓扑学": ["拓扑", "开集", "闭集", "紧致", "连通", "同胚", "基本群"],
    "微分几何": ["流形", "曲率", "测地线", "联络", "切空间", "第一基本形式"],
    "数值分析": [
        "插值", "Newton", "迭代", "误差", "数值积分", "Runge-Kutta",
        "中心差分", "数值微分", "复化", "梯形公式", "Simpson", "Romberg",
        "Frobenius", "条件数", "Euler", "稳定区间", "Doolittle", "LU分解",
    ],
    "测度积分": ["测度", "可测", "Lebesgue", "勒贝格", "几乎处处", "支配收敛", "Fatou"],
    "运筹学": ["线性规划", "单纯形", "对偶", "运输问题", "排队", "决策树"],
    "离散数学": ["图", "树", "组合", "递推", "生成函数", "布尔", "命题逻辑"],
    "线性回归": [
        "回归", "最小二乘", "OLS", "残差", "t检验", "F检验", "R方",
        "\\beta", "标准误", "SSE", "SSR", "SST", "S_{xx}", "S_{xy}",
        "ANOVA", "方差分析表", "均值响应", "预测区间", "Gauss-Markov",
        "Durbin-Watson", "BLUE", "偏F", "多重共线性", "VIF",
    ],
    "非基础及进阶课程": ["进阶", "高级课程", "研究生"],
}


def _scan_categories() -> list:
    if not SKILLS_BASE.exists():
        return []
    return sorted(p.name for p in SKILLS_BASE.iterdir() if p.is_dir())


def _build_keywords_index(categories: list) -> dict:
    idx = {}
    for cat in categories:
        kw = {cat}
        kw.update(DOMAIN_ALIASES.get(cat, []))
        md = SKILLS_BASE / cat / f"{cat}skill.md"
        if md.exists():
            text = md.read_text(encoding="utf-8")
            for line in text.splitlines():
                s = line.strip().lstrip("#").strip()
                s = re.sub(r"^\d+\.\s*", "", s)
                if 1 < len(s) <= 12 and not s.startswith("|"):
                    kw.add(s)
        idx[cat] = list(kw)
    return idx


_CATEGORIES = _scan_categories()
_KEYWORDS_INDEX = _build_keywords_index(_CATEGORIES)


def find_candidate_categories(problem: str, top_k: int = 5) -> list:
    scores = {}
    for cat, kws in _KEYWORDS_INDEX.items():
        hits = sum(1 for kw in kws if kw and kw in problem)
        scores[cat] = hits
    ranked = sorted(scores.items(), key=lambda x: (x[1], x[0]), reverse=True)
    return [(cat, score) for cat, score in ranked[:top_k] if score > 0]


def load_top1_skill(problem: str) -> str:
    """关键词匹配 top-1 学科，返回该学科 skill.md 全文。无匹配返回空字符串。"""
    candidates = find_candidate_categories(problem, top_k=1)
    if not candidates:
        return ""
    cat = candidates[0][0]
    md = SKILLS_BASE / cat / f"{cat}skill.md"
    if md.exists():
        return md.read_text(encoding="utf-8")
    return ""
