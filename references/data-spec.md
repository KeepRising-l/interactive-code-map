# 代码地图数据规范（`__MAP_DATA__` Schema · v3 兼容）

**核心铁律：生成 = 读盘提取源码 + 构造符合本规范的 JSON，替换进 [assets/viewer-template.html](../assets/viewer-template.html) 的 `__PAGE_TITLE__` 与 `__MAP_DATA__`。前端引擎代码一行不改。**

> **v3 说明**：v3 完全沿用同一套 `__MAP_DATA__` Schema（零破坏性变更）。右侧 AI 导师会自动读取此处提供的 `chains`、`cards`、`edges`、`sources` 与 `scenarios` 来装配 4 层精确上下文，并在生成「学习薄弱点诊断报告」时引用这里的链路、卡片与行号。

---

## 1. 顶层 JSON 结构

```json
{
  "projectTitle": "项目名 · 核心链路源码导图",
  "projectSubtitle": "3 条链路 · 12 个核心类 · 3 个场景剧本",
  "chains": [ ... ],
  "scenarios": [ ... ],
  "files": [ ... ],
  "sources": { "<fileKey>": ["line 1", "line 2", ...] },
  "themes": { "<themeId>": { ... } },
  "groups": [ ... ],
  "cards": [ ... ],
  "edges": [ ... ]
}
```

---

## 2. 各字段详细定义

### 2.1 `chains`（核心链路定义，数组，2~5 条最佳）

```json
{
  "id": "chat",
  "name": "① 对话与 ReAct 主链路",
  "color": "#2563eb",
  "description": "一句话概括本链路的起点、核心逻辑与终点。",
  "tour": ["chat_entry", "chat_async", "chat_route", "chat_react", "chat_final"]
}
```
- `tour`：按执行或阅读顺序排列的 `card.id` 数组；锁定单条链路时，底部导览条按此顺序引导单步阅读。

### 2.2 `scenarios`（🎬 真实场景剧本，数组，必配 2~4 个）

用真实的“用户问题 / 线上突发状况”把跨类甚至跨链路的协作过程串联成可单步播放的剧本：

```json
{
  "id": "sc_abort",
  "name": "剧本 2：用户刚看 1 秒突然停止生成",
  "badgeType": "error",
  "summary": "演示前端断连后，取消信号如何一路穿透到线程池与大模型 HTTP 流，避免白烧 Token。",
  "steps": [
    {
      "cardId": "app_sse",
      "stageType": "error",
      "situation": "浏览器点击停止，AbortController 断开 SSE 连接。",
      "resolution": "SseController 写流捕获 IOException，立刻调用 cancel.cancel()。",
      "dataFlow": "SSE Broken Pipe → AtomicBoolean(false → true)",
      "focusRanges": [[125, 135]]
    },
    {
      "cardId": "llm_stream",
      "stageType": "warn",
      "situation": "后台读流线程正从大模型逐行接收数据，若不及时刹停会继续烧费。",
      "resolution": "LlmClient.streamChat 每读一行先检查 isCancelled()，命中即 return 并关闭连接。",
      "dataFlow": "readLine() → isCancelled()==true → return & close()",
      "focusRanges": [[121, 127]]
    }
  ]
}
```
- `badgeType` / `stageType` 枚举：`"normal"`（正常主路·蓝）、`"warn"`（分支/降级/兜底·橙）、`"error"`（异常/拦截/取消·红）。
- 多链路项目**必须至少包含 1 个 `"normal"` 主流剧本 + 至少 1 个 `"warn"`/`"error"` 异常/兜底剧本**。
- `focusRanges`（强烈推荐）：针对当前剧本高亮该卡片内部**最直接解决此问题的 5~25 行**（例如正常剧本亮主分支、异常剧本亮 `catch`/`finally`）；若留空 `[]`，则复用卡片默认 `ranges`。

### 2.3 `files` 与 `sources`（核心类源码清单）

```json
"files": [
  { "key": "ChatService.java", "path": "src/main/java/.../ChatService.java", "chainIds": ["chat"] }
],
"sources": {
  "ChatService.java": ["package ...", "..."]
}
```
- **核心类精选原则**：每条链路精选 **5~8 个真正有含金量的核心类**（并发控制、核心算法、状态机、主编排类、安全校验），嵌入 **100% 完整真实源码**（按 `splitlines()` 拆成字符串数组，保持行号与 IDE **1:1 对齐**）。
- **跨链路共享文件**：某文件在多条链路都承担核心角色时，在 `chainIds` 中全部列出（如 `["chat", "react"]`）。
- **密钥脱敏红线**：若源文件内含真实 API Key / Token / 私钥 / 密码，读取后必须在**不增删换行符**的前提下替换为 `"***REDACTED_KEY***"`，确保行数严格不变。
- **每行必须是 JSON 字符串**：`sources` 里出现数字/对象会让抽屉渲染在 `line.slice` 处崩溃，校验器会直接报错。
- 校验器传 `--source-root` 时会逐行比对磁盘源码（含 `***REDACTED` 的行跳过），行数相同但内容漂移同样会失败。

### 2.4 `themes`（按类或模块配色）

```json
"themes": {
  "chat_svc": {
    "name": "ChatService.java",
    "label": "对话编排",
    "fill": "#eff6ff",
    "stroke": "#2563eb",
    "badgeBg": "#dbeafe",
    "badgeFg": "#1e40af",
    "groupBg": "rgba(239,246,255,0.55)",
    "edge": "#3b82f6"
  }
}
```

### 2.5 `groups`（类或阶段外框）

```json
{
  "id": "g_chat_svc",
  "chainId": "chat",
  "theme": "chat_svc",
  "title": "ChatService.java（异步编排 · 记忆 · 收尾）",
  "x": 360, "y": 40, "w": 620, "h": 310
}
```

### 2.6 `cards`（细粒度知识卡片，单卡核心行控制在 10~45 行）

```json
{
  "id": "cs_cancel",
  "chainId": "chat",
  "groupId": "g_chat_svc",
  "theme": "chat_svc",
  "kind": "core",
  "roleBadge": "⚡并发",
  "x": 384, "y": 86, "w": 265, "h": 88,
  "title": "Cancellation 协作式取消令牌",
  "subtitle": "AtomicBoolean 保证跨线程立即可见",
  "file": "ChatService.java",
  "ranges": [[35, 40]],
  "note": "这里用 `AtomicBoolean` 而不用普通 `boolean`，因为 HTTP 线程写取消标记、工作线程读取消标记，普通变量没有跨线程内存可见性保证。",
  "interview": "Java 为什么不直接 thread.stop() 强杀线程，而要写协作式取消？→ 答：强杀会破坏锁和未写完的 IO 状态导致数据损坏；协作式取消通过标志位让工作线程在安全点自行清理并退出。",
  "extraTag": "对应模块：ray-agent-domain"
}
```
- **`kind` 分级标准**：
  - `"core"`：核心类卡片。**单卡高亮控制在 10~45 行，绝不把 100+ 行的整个大方法塞成 1 张卡**。校验器 `> 45` 行告警、`> 70` 行直接判错。大类（如算法/编排类）拆成 **2~5 张卡**：数据模型 / 关键常量参数 / 核心分支 / 异常与取消退出。
  - `"summary"`：外围 DTO、纯 CRUD、配置胶水衔接卡，`file` 设 `""`、`ranges` 设 `[]`、`interview` 可留空。
- **纯文本 + 反引号约定（禁写裸 HTML）**：`note`、`interview`、`situation`、`resolution` 里一律写**纯文本**，代码符号用反引号 `` `List<String>` `` 包裹；**禁止**在 JSON 文案里写 `<code>`、`<br>`、`<div>` 等 HTML 标签（模板已做全量 HTML 转义与安全反引号高亮，防止泛型尖括号被吞）。

### 2.7 `edges`（矢量连接线）

```json
{
  "from": "app_sse",
  "to": "cs_cancel",
  "chainId": "chat",
  "label": "断连触发 cancel",
  "dir": "auto",
  "crossChain": false
}
```
- **跨链路虚线（`crossChain: true`）**：多链路项目在「全部总览」模式下，如果某条链路调用或复用了另一条链路的底层核心组件（如 ReAct 工具调用了知识库的检索器），必须用 `crossChain: true` 连出来，避免各链路变成孤立平行线。

---

## 3. 防重叠排版基准

- 推荐卡宽 `w = 245 ~ 275`，卡高 `h = 84 ~ 100`。
- 同组内相邻卡片间距：水平 `>= 55px`，垂直 `>= 40px`。
- 类分组框 `group` 相对内部卡片留白：左右各 `>= 22px`，顶部标题区留 `>= 44px`，底部留 `>= 20px`。校验器强制卡片不越界且顶部留白 `>= 44px`。
- 不同链路的布局区域（Zone）之间预留 `>= 140px` 隔离带，保证 `groups` 与 `cards` 均 **0 重叠**。

---

## 4. 生成与校验步骤

1. 在临时构建脚本里读取 `assets/viewer-template.html`，把构建好的 `payload`（`json.dumps(..., ensure_ascii=False)` 后把所有 `<` 替换为 `\u003c`，防止 `</script>` / `<!--` 破坏 script 标签）替换 `__MAP_DATA__`，把标题替换 `__PAGE_TITLE__`，写出到目标 `.html`。
2. 跑强制校验：
   ```bash
   python "<技能目录>/scripts/validate_code_map.py" "<输出.html>" --source-root "<项目根目录>"
   ```
   **0 `[ERROR]` 才允许交付**，所有 `[WARN]`（如单卡超过 45 行、缺少异常剧本、缺少跨链虚线、单卡范围重叠）逐条评估优化。校验通过后再删除临时脚本；所有文件读写显式使用 `encoding="utf-8"`。
