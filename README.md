# interactive-code-map (v3.1)

**把多链路复杂源码仓库，提炼成一个「左真源码 · 中 SVG 矢量白板 · 右 AI 私教工作台」的单文件交互式学习工具。**

> 零前端外部依赖（不用 Mermaid、不引 CDN），嵌入与 IDE 行号 **1:1 对齐的真实源码**，同时自带 **零跨域（No-CORS）本机流式代理** 与自动化校验门禁。

---

## 核心特性

### 三栏协同源码工作台

1. **左栏 · 1:1 真实源码抽屉**
   - 嵌入精选核心类（并发控制、核心算法、状态机、主编排入口）的完整磁盘源码，行号与 IDE 严格对齐。
   - 多语言词法高亮、卡片大白话笔记与 **`💡 面试高频追问`**、顶部文件页签切换。
   - 点击高亮代码行，可反向聚焦定位到画布对应卡片；支持直接拖拽文件页签/抽屉头部到右侧向 AI 提问。
2. **中栏 · 自研 SVG 无限矢量白板**
   - **🌐 全部链路总览 + 单链锁定**：默认总览全局及跨链虚线协作；选中单条链路可隐藏/淡化无关节点，并触发底部单步导览条（支持 `← / →` 键盘切换）。
   - **🎬 真实场景剧本演练**：内置正常主链路 + 异常/取消/降级剧本，分步展示“遇到什么问题 → 谁来解决 → 数据如何流转”，并联动 `focusRanges` 精准高亮直接解决问题的一小段源码。
   - **双击拖卡引用**：在画布上双击任意卡片即可拖进右侧 AI 对话框作为精确上下文（也支持点卡片右上角 **`+AI`**）。
3. **右栏 · AI 源码导师工作台**
   - **4 层上下文工程**：全局导图骨架 → 引用的真实源码（含前后 ±15 行缓冲、上下游 1 跳邻居、当前剧本步骤）→ 6 轮滑动窗口 + 历史引用去重 + 滚动摘要。
   - **零 CORS 跨域**：配套极简本机同源代理 [serve_map.py](./scripts/serve_map.py) 与双击 `.bat` 启动器，解决浏览器 `file://` 或跨端口直连大模型网关被拦截的问题。
   - **本地持久化 + 双保险备份**：配置、对话历史与学习统计保存在浏览器 `localStorage`，支持随时 **`💾 导出 / 📂 导入`** JSON 备份。
   - **📊 学习薄弱点诊断报告**：结合已探索盲区、卡片追问热度和剧本深度，一键生成诊断报告与针对性面试自测题，支持导出 Markdown。

---

## 安装方法

直接 `git clone` 到对应 Agent 工具的 Skills 目录即可：

```bash
# Antigravity / Codex（工作区级，在目标项目根目录执行）
git clone https://github.com/KeepRising-l/interactive-code-map.git .agents/skills/interactive-code-map

# Claude Code（全局用户级）
git clone https://github.com/KeepRising-l/interactive-code-map.git ~/.claude/skills/interactive-code-map

# Claude Code（工作区级，在目标项目根目录执行）
git clone https://github.com/KeepRising-l/interactive-code-map.git .claude/skills/interactive-code-map
```

确保本机已安装 **Python 3.10+**（校验与本机代理仅用标准库，零 `pip` 依赖）；可选安装 **Node.js**（用于在校验阶段自动运行 `node --check` 检查内联 JS 语法）。

---

## 使用方式

### 1. 向你的 AI Coding Agent 发起指令

安装好技能后，可以在任意代码仓库里直接这样说：

- `"用 interactive-code-map 技能把本项目的核心并发链路与主流程拆解成交互式源码导图"`
- `"按核心链路生成交互式 SVG 源码白板，附带正常流和异常兜底剧本"`

Agent 会严格执行 [SKILL.md](./SKILL.md) 的两步工作流：

1. **只读扫描 & 报清单确认**：先呈报拟拆解的链路、精选核心类、细卡拆分与真实场景剧本，等你确认后再动手；
2. **注入模板 & 门禁校验**：生成单文件 HTML → 自动运行 [validate_code_map.py](./scripts/validate_code_map.py)（校验证书/密钥脱敏、行号与磁盘 1:1 对齐、卡片零重叠、JS 语法等，**0 Error** 才算通过）→ 生成同目录 `-AI导师.bat` 启动器。

### 2. 打开导图（两种模式按需选）

| 使用场景 | 打开方式 | 说明 |
| :--- | :--- | :--- |
| **纯离线看图 / 查源码 / 跑剧本** | 直接双击生成的 `*.html` | 零服务端依赖，随时随地离线打开 |
| **启用右侧 AI 源码导师**（无 CORS 限制） | Windows：双击同目录 `*-AI导师.bat`<br>macOS / Linux：`python scripts/serve_map.py <path-to-html>` | 在本机 `127.0.0.1` 拉起静态页与同源流式代理 `/__llm_proxy__`，绕开浏览器跨域预检限制 |

### 3. 配置 AI 导师模型

在右侧 AI 导师面板点击 **`⚙️ 配置`**，支持任意 OpenAI 兼容接口（如 DeepSeek、OpenAI、SiliconFlow、Ollama、火山方舟、智谱及本机中转网关，路径自动兼容 `/v1`、`/v3`、`/v4`、`/openai` 与完整 `/chat/completions`）：

- **Base URL**：例如 `https://api.deepseek.com/v1` 或 `http://127.0.0.1:<port>/v1`
- **API Key**：仅保存在当前源的浏览器 `localStorage` 中，**永远不会写入导图 HTML**（本机环回地址 `127.0.0.1` / `localhost` 可留空）
- **Model**：例如 `deepseek-chat`
- 填好后可先点 **`🔌 测试连接`** 验证连通性，再点 **`保存配置`**。

---

## 仓库目录结构

```text
interactive-code-map/
├── SKILL.md                       # Skill 主指令与两步工作流规范
├── README.md                      # 项目说明（本文件）
├── LICENSE                        # MIT 开源协议
├── .gitignore
├── assets/
│   └── viewer-template.html       # 固定三栏 SVG 白板 + 源码抽屉 + AI 导师引擎模板
├── references/
│   └── data-spec.md               # __MAP_DATA__ JSON Schema 与排版规范
└── scripts/
    ├── validate_code_map.py       # 导图质量门禁校验器（重叠/源码对齐/脱敏/JS语法）
    └── serve_map.py               # 本机同源流式代理 + Windows .bat 启动器生成脚本
```

相关文件索引：
- 技能定义：[SKILL.md](./SKILL.md)
- 前端引擎模板：[assets/viewer-template.html](./assets/viewer-template.html)
- 数据规范：[references/data-spec.md](./references/data-spec.md)
- 质量校验器：[scripts/validate_code_map.py](./scripts/validate_code_map.py)
- 本地同源代理：[scripts/serve_map.py](./scripts/serve_map.py)
- 开源协议：[LICENSE](./LICENSE)
