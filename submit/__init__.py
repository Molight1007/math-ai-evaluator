"""submit 包：多智能体数学推理智能体（MathPilot 多智能体版）。

同时兼容两种导入布局：
- 平台把本目录加入 sys.path，使用顶层名：``from user_agent import ReasoningAgent``
- 评测器以项目根为 sys.path，使用包名：``from submit.user_agent import ReasoningAgent``
见各模块内部 `try/except ImportError` 回退。
"""
