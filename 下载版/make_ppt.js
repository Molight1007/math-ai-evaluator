const pptxgen = require("pptxgenjs");
const path = require("path");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.title = "挑战杯揭榜挂帅 - 基于Intern-S1的数学智能体";
pres.author = "CSUST Team";

// =========================================================
// 颜色体系：深海科技蓝
// =========================================================
const C = {
  bg:      "0D1B2A",   // 深海蓝背景
  card:    "1A2E42",   // 卡片背景
  card2:   "162438",   // 次级卡片
  accent:  "00C5FF",   // 青蓝主色
  accent2: "0FA3E5",   // 辅助蓝
  gold:    "FFD166",   // 金色强调
  green:   "06D6A0",   // 绿色标识
  red:     "EF476F",   // 红色警示
  white:   "FFFFFF",
  gray:    "8BAAC2",   // 淡蓝灰
  lightBg: "F0F7FF",   // 浅色背景
};

// 辅助：生成shadow对象（每次调用返回新对象，避免PptxGenJS mutation bug）
const mkShadow = () => ({ type: "outer", blur: 8, offset: 3, angle: 135, color: "000000", opacity: 0.25 });

// =========================================================
// Slide 1: 封面
// =========================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };

  // 顶部装饰线
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  // 左侧垂直装饰条
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0.04, w: 0.06, h: 5.585, fill: { color: C.accent2 }, line: { color: C.accent2 } });

  // 右侧装饰几何
  s.addShape(pres.shapes.RECTANGLE, { x: 7.5, y: 1.0, w: 2.5, h: 3.2, fill: { color: C.card, transparency: 30 }, line: { color: C.accent, width: 1 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 7.7, y: 1.2, w: 2.1, h: 2.8, fill: { color: "000000", transparency: 60 }, line: { color: C.accent2, width: 1 } });
  // 右侧装饰文字
  s.addText("AI · MATH\nAGENT", { x: 7.6, y: 1.5, w: 2.2, h: 2.0, fontSize: 22, bold: true, color: C.accent, align: "center", valign: "middle", charSpacing: 3 });

  // 主标题区域
  s.addText("🏆  挑战杯·揭榜挂帅", { x: 0.3, y: 0.7, w: 6.8, h: 0.55, fontSize: 14, color: C.gold, bold: true, charSpacing: 4, margin: 0 });
  s.addText("基于 Intern-S1 的", { x: 0.3, y: 1.35, w: 6.8, h: 0.65, fontSize: 28, color: C.white, bold: true, margin: 0 });
  s.addText("数学智能体设计与推理创新", { x: 0.3, y: 1.95, w: 6.8, h: 0.75, fontSize: 28, color: C.accent, bold: true, margin: 0 });

  // 分隔线
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 2.82, w: 4.0, h: 0.04, fill: { color: C.gray }, line: { color: C.gray } });

  // 副标题信息
  const infoItems = [
    { icon: "📋", label: "赛题编号：XH-202627" },
    { icon: "🏢", label: "发榜单位：上海人工智能实验室" },
    { icon: "📅", label: "报名截止：2026年6月30日" },
    { icon: "⏰", label: "初赛提交：2026年9月5日" },
  ];
  infoItems.forEach((item, i) => {
    s.addText(`${item.icon}  ${item.label}`, {
      x: 0.3, y: 3.0 + i * 0.42, w: 6.5, h: 0.38,
      fontSize: 11, color: C.gray, margin: 0
    });
  });

  // 底部
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.425, w: 10, h: 0.2, fill: { color: C.card }, line: { color: C.card } });
  s.addText("长沙理工大学  ·  2026", { x: 0, y: 5.38, w: 10, h: 0.24, fontSize: 9, color: C.gray, align: "center", margin: 0 });
}

// =========================================================
// Slide 2: 目录
// =========================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  s.addText("CONTENTS", { x: 0.5, y: 0.3, w: 9, h: 0.3, fontSize: 10, color: C.gray, charSpacing: 5, margin: 0 });
  s.addText("目录", { x: 0.5, y: 0.55, w: 4, h: 0.5, fontSize: 26, color: C.white, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.08, w: 1.2, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  const items = [
    ["01", "比赛核心要求", "初赛/总决赛要求与评分标准"],
    ["02", "核心挑战与策略", "本质分析 + 系统架构设计"],
    ["03", "分阶段执行计划", "6个阶段，从6月到9月"],
    ["04", "创新点设计",     "必做创新 + 加分项"],
    ["05", "技术架构",       "项目结构 + 核心技术栈"],
    ["06", "风险与应对",     "5大风险评估与应对措施"],
  ];

  // 两列布局
  items.forEach((item, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.5 + col * 4.8;
    const y = 1.3 + row * 1.3;

    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.3, h: 1.1, fill: { color: C.card }, line: { color: C.card2 }, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.07, h: 1.1, fill: { color: C.accent }, line: { color: C.accent } });
    s.addText(item[0], { x: x + 0.15, y: y + 0.08, w: 0.7, h: 0.4, fontSize: 20, color: C.accent, bold: true, margin: 0 });
    s.addText(item[1], { x: x + 0.15, y: y + 0.45, w: 3.9, h: 0.32, fontSize: 12, color: C.white, bold: true, margin: 0 });
    s.addText(item[2], { x: x + 0.15, y: y + 0.73, w: 3.9, h: 0.28, fontSize: 9, color: C.gray, margin: 0 });
  });
}

// =========================================================
// Slide 3: 比赛要求 - 初赛
// =========================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  s.addText("01  比赛核心要求", { x: 0.4, y: 0.15, w: 9, h: 0.42, fontSize: 18, color: C.white, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 0.58, w: 1.5, h: 0.03, fill: { color: C.accent }, line: { color: C.accent } });

  // 初赛标题
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 0.75, w: 4.2, h: 0.36, fill: { color: C.accent2 }, line: { color: C.accent2 } });
  s.addText("📋  初赛要求（9月5日前提交）", { x: 0.4, y: 0.75, w: 4.2, h: 0.36, fontSize: 11, color: C.white, bold: true, align: "center", valign: "middle", margin: 0 });

  const initReqs = [
    ["✅ 推理求解", "理解自然语言数学问题，自主规划思路并求解"],
    ["✅ 过程解释", "以启发式表达方式解释推理过程"],
    ["✅ 结构化输出", "必须输出 JSON 格式结果（严格要求）"],
    ["✅ 多类型稳健", "覆盖18个子领域，共112道题目"],
  ];
  initReqs.forEach((r, i) => {
    const y = 1.2 + i * 0.75;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y, w: 4.2, h: 0.65, fill: { color: C.card }, line: { color: C.card2 } });
    s.addText(r[0], { x: 0.55, y: y + 0.05, w: 3.8, h: 0.28, fontSize: 11, color: C.accent, bold: true, margin: 0 });
    s.addText(r[1], { x: 0.55, y: y + 0.3, w: 3.8, h: 0.28, fontSize: 9, color: C.gray, margin: 0 });
  });

  // 评分标准
  s.addShape(pres.shapes.RECTANGLE, { x: 5.0, y: 0.75, w: 4.6, h: 0.36, fill: { color: C.gold }, line: { color: C.gold } });
  s.addText("🏅  评分标准（总分100分）", { x: 5.0, y: 0.75, w: 4.6, h: 0.36, fontSize: 11, color: C.bg, bold: true, align: "center", valign: "middle", margin: 0 });

  const scores = [
    ["60%", "答案正确性",     C.green,  "客观线性计分，必须输出JSON"],
    ["20%", "展示质量",       C.accent, "Demo、视频、报告完整性"],
    ["10%", "推理策略设计",   C.gold,   "模块设计、推理链、协作逻辑"],
    ["10%", "创新性扩展性",   C.red,    "机制创新、可迁移性、推广潜力"],
  ];
  scores.forEach((sc, i) => {
    const y = 1.2 + i * 0.75;
    s.addShape(pres.shapes.RECTANGLE, { x: 5.0, y, w: 4.6, h: 0.65, fill: { color: C.card }, line: { color: C.card2 } });
    s.addShape(pres.shapes.RECTANGLE, { x: 5.0, y, w: 0.07, h: 0.65, fill: { color: sc[2] }, line: { color: sc[2] } });
    s.addText(sc[0], { x: 5.15, y: y + 0.1, w: 0.7, h: 0.42, fontSize: 18, color: sc[2], bold: true, align: "left", margin: 0 });
    s.addText(sc[1], { x: 5.9, y: y + 0.06, w: 2.5, h: 0.28, fontSize: 11, color: C.white, bold: true, margin: 0 });
    s.addText(sc[3], { x: 5.9, y: y + 0.34, w: 2.9, h: 0.24, fontSize: 8.5, color: C.gray, margin: 0 });
  });

  // 底部关键约束
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 5.1, w: 9.2, h: 0.35, fill: { color: "2A1020" }, line: { color: C.red, width: 1 } });
  s.addText("❌  不允许仅通过提示词堆叠作答 | ❌  不允许人工逐题干预 | ✅  必须输出结构化 JSON + 日志", {
    x: 0.4, y: 5.1, w: 9.2, h: 0.35, fontSize: 9, color: C.red, align: "center", valign: "middle", margin: 0
  });
}

// =========================================================
// Slide 4: 系统架构图
// =========================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  s.addText("02  数学智能体系统架构", { x: 0.4, y: 0.15, w: 9, h: 0.42, fontSize: 18, color: C.white, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 0.58, w: 1.8, h: 0.03, fill: { color: C.accent }, line: { color: C.accent } });

  // 输入
  s.addShape(pres.shapes.RECTANGLE, { x: 3.5, y: 0.75, w: 3.0, h: 0.48, fill: { color: C.card }, line: { color: C.accent, width: 1 }, shadow: mkShadow() });
  s.addText("📥  用户输入数学问题（自然语言）", { x: 3.5, y: 0.75, w: 3.0, h: 0.48, fontSize: 9.5, color: C.white, align: "center", valign: "middle", margin: 0 });

  // 各 Agent 节点
  const agents = [
    { num: "①", name: "题型分类器", desc: "自动识别18个子领域\nPDE / 复分析 / 拓扑...", color: C.accent, y: 1.42 },
    { num: "②", name: "知识检索 (RAG)", desc: "IMA知识库召回相关\n公式、方法、例题", color: C.accent2, y: 2.14 },
    { num: "③", name: "推理规划 Agent", desc: "CoT + 演绎推理\n知识增强Prompt", color: C.gold, y: 2.86 },
    { num: "④", name: "Intern-S1 API", desc: "调用模型推理\n（不改变模型参数）", color: C.green, y: 3.58 },
    { num: "⑤", name: "过程校验 Agent", desc: "自验证：代入检查\n量纲验证、逻辑审查", color: "#E06030", y: 4.30 },
  ];

  // 连接箭头（居中竖线）
  agents.forEach((a, i) => {
    if (i > 0) {
      const prevY = agents[i - 1].y + 0.52;
      s.addShape(pres.shapes.RECTANGLE, { x: 4.93, y: prevY, w: 0.14, h: a.y - prevY, fill: { color: C.gray }, line: { color: C.gray } });
    }
  });

  agents.forEach((a) => {
    const nodeColor = a.color.replace("#", "");
    s.addShape(pres.shapes.RECTANGLE, { x: 3.3, y: a.y, w: 3.4, h: 0.52, fill: { color: C.card }, line: { color: nodeColor, width: 1.5 }, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x: 3.3, y: a.y, w: 0.08, h: 0.52, fill: { color: nodeColor }, line: { color: nodeColor } });
    s.addText(`${a.num} ${a.name}`, { x: 3.45, y: a.y + 0.04, w: 3.0, h: 0.24, fontSize: 10.5, color: C.white, bold: true, margin: 0 });
    s.addText(a.desc.replace("\n", "  "), { x: 3.45, y: a.y + 0.27, w: 3.0, h: 0.22, fontSize: 8, color: C.gray, margin: 0 });
  });

  // 最后箭头
  s.addShape(pres.shapes.RECTANGLE, { x: 4.93, y: 4.82, w: 0.14, h: 0.22, fill: { color: C.gray }, line: { color: C.gray } });

  // JSON输出
  s.addShape(pres.shapes.RECTANGLE, { x: 3.0, y: 5.04, w: 4.0, h: 0.44, fill: { color: "062A15" }, line: { color: C.green, width: 1.5 }, shadow: mkShadow() });
  s.addText("⑥  输出：JSON { answer, reasoning, steps, verification }", {
    x: 3.0, y: 5.04, w: 4.0, h: 0.44, fontSize: 8.5, color: C.green, align: "center", valign: "middle", bold: true, margin: 0
  });

  // 右侧说明
  const rightNotes = [
    { icon: "🎯", text: "不改变模型参数" },
    { icon: "🧩", text: "Agent多模块协作" },
    { icon: "📚", text: "RAG知识库注入" },
    { icon: "✍️", text: "Prompt Engineering" },
  ];
  rightNotes.forEach((n, i) => {
    s.addText(`${n.icon}  ${n.text}`, { x: 7.5, y: 2.0 + i * 0.58, w: 2.2, h: 0.45, fontSize: 10, color: C.gray, margin: 0 });
  });
  s.addShape(pres.shapes.RECTANGLE, { x: 7.4, y: 1.7, w: 0.03, h: 3.0, fill: { color: C.card2 }, line: { color: C.card2 } });
}

// =========================================================
// Slide 5: 执行计划总览
// =========================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  s.addText("03  分阶段执行计划", { x: 0.4, y: 0.15, w: 9, h: 0.42, fontSize: 18, color: C.white, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 0.58, w: 1.5, h: 0.03, fill: { color: C.accent }, line: { color: C.accent } });

  const phases = [
    { num: "01", name: "基础搭建",    date: "6.8—6.22",  color: C.accent,  key: "跑通API→Agent→JSON最小闭环" },
    { num: "02", name: "知识库建设",  date: "6.15—7.6",  color: C.accent2, key: "18领域公式+方法+例题库" },
    { num: "03", name: "Prompt优化",  date: "7.1—7.20",  color: C.gold,    key: "长CoT+演绎推理+自验证模板" },
    { num: "04", name: "过程校验",    date: "7.15—7.31", color: C.green,   key: "数值验证+逻辑一致性+置信度" },
    { num: "05", name: "测试评估",    date: "8.1—8.20",  color: C.red,     key: "112题全量测试+逐领域调优" },
    { num: "06", name: "文档提交",    date: "8.15—9.5",  color: "#C084FC", key: "技术方案+视频+打包提交" },
  ];

  // 时间轴横线
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 1.5, w: 9.2, h: 0.04, fill: { color: C.card2 }, line: { color: C.card2 } });

  phases.forEach((p, i) => {
    const x = 0.4 + i * 1.55;
    const nodeColor = p.color.replace("#", "");

    // 节点圆点
    s.addShape(pres.shapes.OVAL, { x: x + 0.5, y: 1.37, w: 0.3, h: 0.3, fill: { color: nodeColor }, line: { color: nodeColor } });
    // 垂直连线（奇偶交错上下）
    const isUp = i % 2 === 0;
    const lineH = 0.6;
    const lineY = isUp ? 1.5 - lineH : 1.67;
    s.addShape(pres.shapes.RECTANGLE, { x: x + 0.63, y: lineY, w: 0.04, h: lineH, fill: { color: nodeColor }, line: { color: nodeColor } });

    // 卡片
    const cardY = isUp ? 0.75 : 2.35;
    s.addShape(pres.shapes.RECTANGLE, { x, y: cardY, w: 1.45, h: 1.45, fill: { color: C.card }, line: { color: nodeColor, width: 1 }, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y: cardY, w: 1.45, h: 0.07, fill: { color: nodeColor }, line: { color: nodeColor } });
    s.addText(p.num, { x: x + 0.05, y: cardY + 0.1, w: 0.55, h: 0.36, fontSize: 18, color: nodeColor, bold: true, margin: 0 });
    s.addText(p.name, { x: x + 0.05, y: cardY + 0.42, w: 1.35, h: 0.32, fontSize: 10, color: C.white, bold: true, margin: 0 });
    s.addText(p.date, { x: x + 0.05, y: cardY + 0.71, w: 1.35, h: 0.26, fontSize: 8.5, color: nodeColor, margin: 0 });
    s.addText(p.key,  { x: x + 0.05, y: cardY + 0.96, w: 1.35, h: 0.44, fontSize: 7.5, color: C.gray, margin: 0 });
  });

  // 底部关键里程碑
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 4.9, w: 9.2, h: 0.55, fill: { color: C.card }, line: { color: C.card2 } });
  s.addText("🎯  关键里程碑：  基线跑通 (6.22)  →  知识库就绪 (7.6)  →  Prompt优化 (7.20)  →  测试通过 (8.20)  →  提交 (9.5)", {
    x: 0.4, y: 4.9, w: 9.2, h: 0.55, fontSize: 10, color: C.gold, align: "center", valign: "middle", margin: 0
  });
}

// =========================================================
// Slide 6: 第一阶段详情（基础搭建）
// =========================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 0.14, w: 1.4, h: 0.38, fill: { color: C.accent }, line: { color: C.accent } });
  s.addText("阶段 01", { x: 0.4, y: 0.14, w: 1.4, h: 0.38, fontSize: 11, color: C.bg, bold: true, align: "center", valign: "middle", margin: 0 });
  s.addText("基础搭建  ·  6月8日 — 6月22日（2周）", { x: 1.9, y: 0.18, w: 7.8, h: 0.34, fontSize: 14, color: C.white, bold: true, margin: 0 });
  s.addText("目标：跑通 Intern-S1 API → 智能体 → JSON 输出的最小闭环", { x: 0.4, y: 0.58, w: 9, h: 0.28, fontSize: 10, color: C.gold, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 0.88, w: 9.2, h: 0.03, fill: { color: C.card2 }, line: { color: C.card2 } });

  const tasks1 = [
    { n: "1.1", t: "注册 Intern-S1 API，获取 Token，测试基本调用", d: "1天", o: "API 调用脚本" },
    { n: "1.2", t: "搭建 lagent 基线框架", d: "2-3天", o: "可运行的 Agent 骨架" },
    { n: "1.3", t: "实现题型分类器（18类）", d: "2天", o: "分类 Prompt + 测试" },
    { n: "1.4", t: "实现 CoT 推理链 Agent", d: "2天", o: "基础解题 Agent" },
    { n: "1.5", t: "实现 JSON 格式化输出", d: "1-2天", o: "符合比赛要求的结构化输出" },
    { n: "1.6", t: "端到端跑通 5 道样题，验证全流程", d: "2天", o: "验证全流程" },
  ];

  tasks1.forEach((t, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.4 + col * 4.8;
    const y = 1.02 + row * 1.42;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.4, h: 1.3, fill: { color: C.card }, line: { color: C.card2 }, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.07, h: 1.3, fill: { color: C.accent }, line: { color: C.accent } });
    s.addText(t.n, { x: x + 0.15, y: y + 0.06, w: 0.5, h: 0.3, fontSize: 13, color: C.accent, bold: true, margin: 0 });
    s.addText(t.t, { x: x + 0.15, y: y + 0.34, w: 3.9, h: 0.5, fontSize: 10, color: C.white, margin: 0 });
    s.addText(`🕐 ${t.d}`, { x: x + 0.15, y: y + 0.84, w: 1.5, h: 0.26, fontSize: 8.5, color: C.gold, margin: 0 });
    s.addText(`📄 ${t.o}`, { x: x + 1.8, y: y + 0.84, w: 2.4, h: 0.26, fontSize: 8.5, color: C.gray, margin: 0 });
  });
}

// =========================================================
// Slide 7: 18子领域覆盖
// =========================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  s.addText("02  知识库建设 — 18个子领域覆盖", { x: 0.4, y: 0.15, w: 9, h: 0.42, fontSize: 18, color: C.white, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 0.58, w: 1.8, h: 0.03, fill: { color: C.accent }, line: { color: C.accent } });

  const domains = [
    { name: "偏微分方程", pri: "🔴", color: "EF476F" },
    { name: "复分析", pri: "🔴", color: "EF476F" },
    { name: "拓扑学", pri: "🔴", color: "EF476F" },
    { name: "运筹学", pri: "🔴", color: "EF476F" },
    { name: "代数", pri: "🟡", color: "FFD166" },
    { name: "数论", pri: "🟡", color: "FFD166" },
    { name: "几何", pri: "🟡", color: "FFD166" },
    { name: "概率论", pri: "🟡", color: "FFD166" },
    { name: "统计学", pri: "🟡", color: "FFD166" },
    { name: "泛函分析", pri: "🟢", color: "06D6A0" },
    { name: "微分方程ODE", pri: "🟢", color: "06D6A0" },
    { name: "组合数学", pri: "🟢", color: "06D6A0" },
    { name: "图论", pri: "🟢", color: "06D6A0" },
    { name: "数值分析", pri: "🟢", color: "06D6A0" },
    { name: "实分析", pri: "🟢", color: "06D6A0" },
    { name: "抽象代数", pri: "🟢", color: "06D6A0" },
    { name: "数学物理", pri: "🟢", color: "06D6A0" },
    { name: "离散数学", pri: "🟢", color: "06D6A0" },
  ];

  const cols = 6;
  const cellW = 1.52;
  const cellH = 0.72;
  domains.forEach((d, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    const x = 0.25 + col * (cellW + 0.06);
    const y = 0.78 + row * (cellH + 0.1);

    s.addShape(pres.shapes.RECTANGLE, { x, y, w: cellW, h: cellH, fill: { color: C.card }, line: { color: d.color, width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: cellW, h: 0.05, fill: { color: d.color }, line: { color: d.color } });
    s.addText(String(i + 1).padStart(2, "0"), { x: x + 0.06, y: y + 0.1, w: 0.35, h: 0.25, fontSize: 9, color: d.color, bold: true, margin: 0 });
    s.addText(d.name, { x: x + 0.06, y: y + 0.33, w: cellW - 0.1, h: 0.3, fontSize: 9.5, color: C.white, bold: true, margin: 0 });
  });

  // 图例
  s.addText("🔴 高优先级  🟡 中优先级  🟢 一般", {
    x: 0.25, y: 5.18, w: 9.5, h: 0.3, fontSize: 10, color: C.gray, align: "center", margin: 0
  });
}

// =========================================================
// Slide 8: 创新点
// =========================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  s.addText("04  创新点设计", { x: 0.4, y: 0.15, w: 9, h: 0.42, fontSize: 18, color: C.white, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 0.58, w: 1.2, h: 0.03, fill: { color: C.accent }, line: { color: C.accent } });

  // 必做创新
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 0.72, w: 4.3, h: 0.34, fill: { color: C.accent }, line: { color: C.accent } });
  s.addText("🚀  必做创新点（对应A档评分）", { x: 0.4, y: 0.72, w: 4.3, h: 0.34, fontSize: 10.5, color: C.bg, bold: true, align: "center", valign: "middle", margin: 0 });

  const must = [
    { icon: "🤝", title: "多Agent协作架构", desc: "题型分类→推理→校验→格式化\n完整多智能体流水线", score: "推理策略 10分" },
    { icon: "🎯", title: "领域自适应Prompt", desc: "18子领域各自独立优化\n的Prompt模板体系", score: "推理策略 10分" },
    { icon: "🔄", title: "过程校验闭环", desc: "自动验证→错误时\n自动触发重新推理", score: "创新性 10分" },
    { icon: "💡", title: "启发式解释生成", desc: "不仅展示推理，还生成\n教育性可读解释", score: "创新性 10分" },
  ];

  must.forEach((m, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.4 + col * 2.2;
    const y = 1.14 + row * 1.5;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 2.0, h: 1.35, fill: { color: C.card }, line: { color: C.accent, width: 1 }, shadow: mkShadow() });
    s.addText(m.icon, { x: x + 0.1, y: y + 0.1, w: 0.4, h: 0.4, fontSize: 16, margin: 0 });
    s.addText(m.title, { x: x + 0.1, y: y + 0.44, w: 1.8, h: 0.34, fontSize: 10, color: C.white, bold: true, margin: 0 });
    s.addText(m.desc, { x: x + 0.1, y: y + 0.74, w: 1.8, h: 0.38, fontSize: 8, color: C.gray, margin: 0 });
    s.addShape(pres.shapes.RECTANGLE, { x: x, y: y + 1.12, w: 2.0, h: 0.23, fill: { color: "062035" }, line: { color: "062035" } });
    s.addText(`📊 ${m.score}`, { x: x, y: y + 1.12, w: 2.0, h: 0.23, fontSize: 7.5, color: C.accent, align: "center", margin: 0 });
  });

  // 加分创新
  s.addShape(pres.shapes.RECTANGLE, { x: 5.0, y: 0.72, w: 4.6, h: 0.34, fill: { color: C.gold }, line: { color: C.gold } });
  s.addText("⭐  加分创新点（冲击擂主）", { x: 5.0, y: 0.72, w: 4.6, h: 0.34, fontSize: 10.5, color: C.bg, bold: true, align: "center", valign: "middle", margin: 0 });

  const bonus = [
    { icon: "🔮", title: "超长程推理管理", desc: "复杂多轮推理的中间状态管理与回溯机制" },
    { icon: "🚦", title: "题型自动路由", desc: "根据问题特征自动选择最优求解策略" },
    { icon: "🔧", title: "外部工具集成", desc: "集成SymPy符号计算，数值求解器辅助验证" },
    { icon: "📈", title: "知识库自进化", desc: "解题过程中发现的新方法自动入库" },
  ];

  bonus.forEach((b, i) => {
    const y = 1.14 + i * 0.95;
    s.addShape(pres.shapes.RECTANGLE, { x: 5.0, y, w: 4.6, h: 0.82, fill: { color: C.card }, line: { color: C.gold, width: 0.5 } });
    s.addShape(pres.shapes.RECTANGLE, { x: 5.0, y, w: 0.07, h: 0.82, fill: { color: C.gold }, line: { color: C.gold } });
    s.addText(`${b.icon}  ${b.title}`, { x: 5.15, y: y + 0.06, w: 4.2, h: 0.3, fontSize: 11, color: C.gold, bold: true, margin: 0 });
    s.addText(b.desc, { x: 5.15, y: y + 0.38, w: 4.2, h: 0.35, fontSize: 9, color: C.gray, margin: 0 });
  });
}

// =========================================================
// Slide 9: 技术架构
// =========================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  s.addText("05  技术架构", { x: 0.4, y: 0.15, w: 9, h: 0.42, fontSize: 18, color: C.white, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 0.58, w: 1.0, h: 0.03, fill: { color: C.accent }, line: { color: C.accent } });

  // 技术栈
  const stack = [
    { layer: "Agent框架", tech: "InternLM/lagent  （官方基线）", color: C.accent },
    { layer: "模型API", tech: "Intern-S1 API  ·  Studio控制台", color: C.accent2 },
    { layer: "知识库", tech: "腾讯 IMA（已接入）  ·  RAG召回", color: C.gold },
    { layer: "符号计算", tech: "SymPy  ·  辅助验证计算结果", color: C.green },
    { layer: "Demo前端", tech: "Gradio / Streamlit  ·  快速构建", color: "C084FC" },
    { layer: "评测系统", tech: "Python 自研  ·  批量跑分 + 报告", color: "FB923C" },
    { layer: "版本控制", tech: "Git + GitHub  ·  MolightMA", color: "94A3B8" },
  ];

  stack.forEach((st, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.4 + col * 4.8;
    const y = 0.75 + row * 0.9;
    const nodeColor = st.color.replace("#", "");
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.4, h: 0.76, fill: { color: C.card }, line: { color: nodeColor, width: 0.8 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.07, h: 0.76, fill: { color: nodeColor }, line: { color: nodeColor } });
    s.addText(st.layer, { x: x + 0.18, y: y + 0.1, w: 1.3, h: 0.28, fontSize: 9, color: nodeColor, bold: true, margin: 0 });
    s.addText(st.tech, { x: x + 0.18, y: y + 0.38, w: 3.9, h: 0.28, fontSize: 10, color: C.white, margin: 0 });
  });

  // 目录结构（最后一项单独占整行）
  const y7 = 0.75 + 3 * 0.9;
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: y7, w: 9.2, h: 0.76, fill: { color: C.card }, line: { color: "94A3B8", width: 0.8 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: y7, w: 0.07, h: 0.76, fill: { color: "94A3B8" }, line: { color: "94A3B8" } });
  s.addText("项目结构", { x: 0.6, y: y7 + 0.1, w: 1.3, h: 0.28, fontSize: 9, color: "94A3B8", bold: true, margin: 0 });
  s.addText("agent/  ·  prompts/  ·  knowledge/  ·  evaluation/  ·  api/  ·  demo/  ·  docs/  ·  scripts/", {
    x: 0.6, y: y7 + 0.38, w: 8.7, h: 0.28, fontSize: 9.5, color: C.white, margin: 0
  });
}

// =========================================================
// Slide 10: 风险与应对
// =========================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  s.addText("06  风险识别与应对措施", { x: 0.4, y: 0.15, w: 9, h: 0.42, fontSize: 18, color: C.white, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 0.58, w: 1.8, h: 0.03, fill: { color: C.accent }, line: { color: C.accent } });

  const risks = [
    {
      risk: "API 限流影响批量测试",
      prob: "中", impact: "高",
      action: "提前测试流控上限，设计请求间隔与重试策略",
      color: C.gold,
    },
    {
      risk: "某些子领域模型能力不足",
      prob: "高", impact: "中",
      action: "强化该领域知识库 + Prompt，必要时用数值方法兜底",
      color: C.red,
    },
    {
      risk: "JSON 格式输出不稳定",
      prob: "中", impact: "高",
      action: "多层级格式校验 + 自动修复 Parser + 重试机制",
      color: C.red,
    },
    {
      risk: "时间紧张，功能未完成",
      prob: "中", impact: "高",
      action: "优先保证60%客观分（答案正确率），再争取主观分",
      color: C.gold,
    },
    {
      risk: "知识库内容覆盖不足",
      prob: "低", impact: "中",
      action: "先覆盖🔴高优先级4个领域，逐步扩充到全部18个",
      color: C.green,
    },
  ];

  risks.forEach((r, i) => {
    const y = 0.75 + i * 0.87;
    const probColor = r.prob === "高" ? C.red : r.prob === "中" ? C.gold : C.green;
    const impColor = r.impact === "高" ? C.red : r.impact === "中" ? C.gold : C.green;

    s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y, w: 9.2, h: 0.76, fill: { color: C.card }, line: { color: C.card2 }, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y, w: 0.07, h: 0.76, fill: { color: r.color }, line: { color: r.color } });

    s.addText(r.risk, { x: 0.6, y: y + 0.1, w: 4.5, h: 0.3, fontSize: 11, color: C.white, bold: true, margin: 0 });
    s.addText(`🚨  ${r.action}`, { x: 0.6, y: y + 0.43, w: 6.5, h: 0.28, fontSize: 9, color: C.gray, margin: 0 });

    s.addText(`概率: ${r.prob}`, { x: 7.5, y: y + 0.1, w: 1.0, h: 0.26, fontSize: 8.5, color: probColor, bold: true, align: "center", margin: 0 });
    s.addText(`影响: ${r.impact}`, { x: 8.5, y: y + 0.1, w: 1.0, h: 0.26, fontSize: 8.5, color: impColor, bold: true, align: "center", margin: 0 });
  });
}

// =========================================================
// Slide 11: 立即行动清单
// =========================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  s.addText("本周立即行动清单", { x: 0.4, y: 0.15, w: 9, h: 0.42, fontSize: 18, color: C.white, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 0.58, w: 1.5, h: 0.03, fill: { color: C.accent }, line: { color: C.accent } });

  const actions = [
    { n: "01", task: "注册 Intern-S1 API，获取 Token", when: "今天", color: C.red, icon: "🔑" },
    { n: "02", task: "克隆 lagent 基线框架，跑通 Demo", when: "今天-明天", color: C.red, icon: "📦" },
    { n: "03", task: "测试 API 调用（简单数学题）", when: "明天", color: C.gold, icon: "🧪" },
    { n: "04", task: "搭建项目骨架（目录结构 + Git）", when: "明天", color: C.gold, icon: "🏗️" },
    { n: "05", task: "整理第一批知识库内容（PDE + 复分析）", when: "本周", color: C.accent, icon: "📚" },
    { n: "06", task: "设计第一版 System Prompt 模板", when: "本周", color: C.accent, icon: "✍️" },
  ];

  actions.forEach((a, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.4 + col * 4.8;
    const y = 0.76 + row * 1.5;
    const nodeColor = a.color.replace("#", "");

    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 4.4, h: 1.35, fill: { color: C.card }, line: { color: nodeColor, width: 1 }, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x: x + 3.6, y, w: 0.8, h: 0.36, fill: { color: nodeColor }, line: { color: nodeColor } });
    s.addText(a.when, { x: x + 3.6, y, w: 0.8, h: 0.36, fontSize: 8.5, color: a.color === C.red ? C.white : C.bg, bold: true, align: "center", valign: "middle", margin: 0 });
    s.addText(a.icon, { x: x + 0.1, y: y + 0.1, w: 0.5, h: 0.5, fontSize: 18, margin: 0 });
    s.addText(`${a.n}.`, { x: x + 0.55, y: y + 0.12, w: 0.4, h: 0.3, fontSize: 12, color: nodeColor, bold: true, margin: 0 });
    s.addText(a.task, { x: x + 0.1, y: y + 0.6, w: 4.0, h: 0.62, fontSize: 10.5, color: C.white, margin: 0 });
  });
}

// =========================================================
// Slide 12: 结尾
// =========================================================
{
  const s = pres.addSlide();
  s.background = { color: C.bg };

  // 背景装饰
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });
  s.addShape(pres.shapes.OVAL, { x: 6.5, y: 0.5, w: 4.5, h: 4.5, fill: { color: C.card, transparency: 70 }, line: { color: C.accent2, width: 0.5 } });
  s.addShape(pres.shapes.OVAL, { x: 7.0, y: 1.0, w: 3.5, h: 3.5, fill: { color: C.card2, transparency: 50 }, line: { color: C.accent, width: 0.5 } });

  s.addText("WE ARE READY!", { x: 0.5, y: 0.9, w: 6.5, h: 0.4, fontSize: 12, color: C.accent, charSpacing: 5, bold: true, margin: 0 });
  s.addText("让数学智能体\n走向更高舞台", { x: 0.5, y: 1.35, w: 6.5, h: 1.4, fontSize: 34, color: C.white, bold: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 2.88, w: 3.0, h: 0.04, fill: { color: C.accent }, line: { color: C.accent } });

  const finals = [
    "🏆  目标：初赛高分入围，总决赛冲刺奖项",
    "🤖  基于 Intern-S1 API + 多 Agent 协作架构",
    "📅  截止：2026年9月5日初赛提交",
    "🔗  GitHub: github.com/Molight1007/-csust",
  ];
  finals.forEach((f, i) => {
    s.addText(f, { x: 0.5, y: 3.1 + i * 0.5, w: 7.5, h: 0.4, fontSize: 11, color: C.gray, margin: 0 });
  });

  // 底部 bar
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.225, w: 10, h: 0.4, fill: { color: C.accent }, line: { color: C.accent } });
  s.addText("长沙理工大学  ·  XH-202627  ·  2026 挑战杯揭榜挂帅", {
    x: 0, y: 5.225, w: 10, h: 0.4, fontSize: 10, color: C.bg, align: "center", valign: "middle", bold: true, margin: 0
  });
}

// =========================================================
// 保存 - 输出到脚本所在目录，使用相对路径
// =========================================================
const outputPath = path.join(__dirname, "挑战杯计划书.pptx");
pres.writeFile({ fileName: outputPath })
  .then(() => console.log("✅ PPT 生成完成：" + outputPath))
  .catch(err => { console.error("❌ 生成失败:", err); process.exit(1); });
