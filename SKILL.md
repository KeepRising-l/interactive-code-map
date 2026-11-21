---
name: interactive-code-map
description: >-
  Use this skill when the user wants to study, dissect, or present an existing
  multi-chain codebase by building an interactive SVG vector source code map
  HTML (e.g., "用交互式源码导图拆解这个项目", "按核心链路生成交互式 SVG 源码白板",
  "把复杂算法/并发链路画成可点选高亮源码的白板"). Produces one offline SVG
  three-column AI workbench HTML (left source drawer, center SVG whiteboard,
  right AI tutor with drag-to-quote and weakness diagnosis report) — not a
  Mermaid flowchart; use it when the user wants a spatial source explorer
  with interactive Q&A.
---

# Interactive Code Map v3.1（左源码 · 中矢量白板 · 右 AI 导师工作台）

把多链路、多模块的真实代码库提炼成 **1 个离线可交互 HTML**：
- **左侧源码抽屉**：精选核心类 100% 真源码、大白话笔记、`💡 面试高频追问` 与文件页签；
- **中间 SVG 无限白板**：全部总览 + 单条链路锁定 + **🎬 真实场景剧本回放** + 双击卡片拖动引用；
- **右侧 AI 源码导师**：OpenAI 兼容流式对话、拖拽卡片/类自动装配 **4 层精准上下文**、本地 `localStorage` 持久化 + JSON 导出/导入双保险、**📊 学习薄弱点诊断报告**。

**核心资产**：[assets/viewer-template.html](./assets/viewer-template.html) 是固定三栏渲染引擎。**生成 = 读盘提炼数据，替换 `__PAGE_TITLE__` 与 `__MAP_DATA__`，引擎代码一行不改。**

---

## 选卡与拆解标准

1. **单文件全局总览 + 一键固定单条链路**：默认只输出 1 个 `.html`；用户明确要求“只拆某一条链路/专题”时，用同一模板只生成该链路。
2. **核心源码精选 + 细粒度拆卡（10~45 行/卡）**：
   - 每条链路精选 **5~8 个真正有含金量的核心类**（并发控制、核心算法、状态机、主编排入口、安全校验），嵌入 **100% 完整真实源码**（行号与 IDE 1:1 对齐）。
   - 核心类内按“数据模型 / 关键常量参数 / 核心分支 / 异常与取消退出”拆成 **2~5 张细卡**（单卡高亮控制在 **10~45 行**，避免一张卡亮上百行）。
   - 外围 DTO、简单 CRUD、配置胶水保留为 `kind: "summary"` 衔接卡，不把样板代码塞进抽屉。
3. **跨链虚线 + 真实场景剧本（必须包含正常流与异常/兜底流）**：
   - 链路间共享组件或跨链调用必须用 `crossChain: true` 虚线标出，避免总览成为孤立平行线。
   - 必须设计 **2~4 个真实场景剧本（`scenarios`）**：至少 1 个正常端到端请求 + 至少 1 个并发取消/检索无果拒答/外部报错兜底剧本；每步写清“遇到什么 → 谁来解决 → 数据流转”，并用 `focusRanges` 精准指向直接解决该问题的 5~25 行源码。
4. **大白话 + 类比 + 面试追问**：每张 `core` 卡片都用纯文本 + `` `反引号` ``（**禁写裸 HTML 标签**）配通俗类比讲清参数/设计原因，并附 `interview` 面试高频追问与答法要点。

---

## 强制两步工作流

### 第 1 步：只读扫描 & 先报地图清单（未经用户确认，绝不直接生成 HTML）

1. 只读扫描目标项目的核心链路与难点类，不盲目通读无关模块。
2. 向用户呈报精简清单，等确认或删改后再进入第 2 步：
   - **核心链路（2~5 条）**：每条链路的起点、终点，以及 **5~8 个精选核心类** vs 外围 `summary` 节点。
   - **重点细拆的难点类**（算法参数、并发锁/取消、状态机等拆成哪些细卡）。
   - **🎬 拟设计的 2~4 个真实场景剧本**（名称、覆盖的正常/异常路径、跨越哪些类）。
   - **拟输出 HTML 路径**（默认保存在当前项目 `docs/interactive-code-map/` 或用户指定目录，绝不覆盖现有 `.drawio` 或业务源码）。

### 第 2 步：按数据规范注入模板 + 强制校验门禁

1. 完整阅读 [references/data-spec.md](./references/data-spec.md) 的 JSON Schema 与排版标准。
2. 写一个临时 Python 脚本（放在系统临时目录，不要污染用户仓库）：
   - **所有文件读写必须显式 `encoding="utf-8"`**。Windows 默认 cp936，源码里有中文/emoji 时会直接 `UnicodeEncodeError`。
   - 从磁盘读取选中核心类的真实文件，按行保留，脱敏任何硬编码 API Key / Token / 私钥（保持行数 1:1，脱敏行保留 `***REDACTED_KEY***` 标记）；`sources` 的每个元素必须是字符串。
   - 构建 JSON 时用 `json.dumps(..., ensure_ascii=False)`，再把所有 `<` 替换为 `\u003c`（JSON.parse 会自动还原）。只转义 `</` 挡不住 `<!--` 进入 script 转义态的问题。
   - 替换 `__PAGE_TITLE__` 与 `__MAP_DATA__` 写出目标 HTML。
   - **保留临时脚本直到校验通过**；未通过时改数据重跑，通过后再删除。
3. **运行校验门禁**（必须 **0 `[ERROR]`** 才允许交付，并对 `[WARN]` 逐条处理）：
   ```bash
   python "<技能目录>/scripts/validate_code_map.py" "<输出.html>" --source-root "<项目根目录>"
   ```
   传 `--source-root` 时会做行数 + 逐行内容比对（跳过含 `***REDACTED` 的行），能抓出“行数碰巧一样但读错文件/版本”的情况。若环境具备浏览器截图/无头渲染工具，建议再检查一次总览与三栏布局；没有则如实说明已通过静态与 JS 校验。
4. **生成同目录双端快捷启动器（解决浏览器 `file://` 跨域 CORS）**：
   ```bash
   python "<技能目录>/scripts/serve_map.py" --emit-bat "<输出.html>"
   ```
   会在同目录生成零依赖、无 BOM UTF-8 的 `<名称>-AI导师.bat`（只起本机 `127.0.0.1` 同源流式代理，不改动原 HTML）。

---

## 交付说明要求

交付时必须向用户同时写清两种打开方式：
1. **离线看图 / 看源码 / 跑剧本**：直接双击 `<输出.html>` 即可（零服务端依赖）；
2. **启用 AI 源码导师（100% 免除浏览器 CORS 拦截）**：
   - Windows：直接双击同目录 `<名称>-AI导师.bat`，自动拉起本机 `127.0.0.1` 同源流式代理并打开浏览器；
   - macOS / Linux：运行 `python "<技能目录>/scripts/serve_map.py" "<输出.html>"`。
