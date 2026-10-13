# GPT 内置浏览器研究流程

日常操作使用 [研究运行指南](run-research.md)。`pipeline run --source builtin-browser-dom`
会自动准备任务并打印续跑命令；`pipeline resume` 复用配置和已完成阶段。以下手动准备命令仍保留为接口参考。

此流程使用 Codex 内置浏览器的只读 DOM 接口。无需 Reddit 或 Google API Key。浏览器页面仍会向 Reddit 请求数据；不能将免 Key 描述为完全不用接口。

```mermaid
flowchart LR
    A[数据库中的研究计划] --> B[生成有限采集任务]
    B --> C[Codex 内置浏览器自动搜索]
    C --> D[原帖和已加载评论的 DOM 快照]
    D --> E[校验链接、时间和记录上限]
    E --> F[现有导入器和项目快照]
    F --> G[评论及父帖上下文]
    G --> H[真实模型判断和信号提取]
    H --> I[本次运行的报告和证据附录]
```

先使用已有配置创建数据库项目并选定研究计划。将 `PROJECT_ID`、`SINCE` 和 `UNTIL` 设为实际项目 ID 与带时区的时间窗口。复用现有数据库。采集和分析使用不同上限，避免为了限制模型调用而丢弃原始证据。

```bash
uv run reddit-market-intel pipeline browser-task \
  --project-id "$PROJECT_ID" \
  --since "$SINCE" \
  --until "$UNTIL" \
  --max-items 100 --max-queries 1 --max-discussions 12 \
  --output-path outputs/browser-task.json
```

让 Codex 执行任务文件中的 `instructions`。无需人工搜索、复制帖子或填写分析结果。Codex 使用 `cua_repl` 打开 `iab` 标签页，读取计划搜索的真实结果，访问观察到的讨论链接，执行任务的 `capture_script`。每页保存 `html`、`barrier`、`url`、`title` 和 UTC `captured_at`。可补充可见的 `omitted_controls` 文本。这些控件可能重复，不可相加为遗漏人数。

采集结果为 JSON：`{"task": <原任务对象>, "searches": [<搜索快照>], "discussions": [<讨论快照>]}`。用可用的本地文件保存工具写入结果。若工具不能直接导出文字文件，可以通过本地纯文本编辑器保存工具返回的数据。只保存工具返回的原始观测，不重新编写原文。

```bash
uv run reddit-market-intel pipeline run \
  --project-id "$PROJECT_ID" --source builtin-browser-dom \
  --browser-capture-path outputs/browser-capture.json \
  --max-items 100 --max-analysis-items 30 \
  --max-model-calls 65 --max-seconds 1800 \
  --output-dir outputs/contextual-research
```

`builtin-browser-dom` 不启动外部浏览器，也不使用 CDP、Chrome 配置或登录文件。终端不能直接调用 Codex 的浏览器工具。未提供采集文件时，运行返回 `awaiting_browser` 并保存任务。已有选定计划时模型调用为零；自动生成计划会计入预算。此能力是 Codex 工具驱动的完整研究流程，独立 CLI 后台运行仍需浏览器工具执行器。遇到验证、登录或封锁页面时停止，保留阻塞状态；人工完成验证后才能继续。

分析范围按帖子、评论及采集文件中的顺序取前 `max-analysis-items` 条。全部合格采集记录仍保存在项目中。此选择有顺序偏差。需要改进抽样时，应先说明选择规则，不能称其为随机样本。重复导入只有新增项目关联进入本次范围。无新证据时不生成报告。

评论的 `text` 只含本评论原文。分类和信号提取的 `metadata` 附带同一项目首次采集的 `parent_post`，以及能够确认的 `parent_comment`。父帖正文最多 6000 字符，父评论最多 2000 字符；截断状态单独记录。父级缺失时保持未知。不同项目的父帖不会进入上下文。父帖的购买意图不转移给评论作者。引文校验只接受当前记录正文中的原话。

时间窗口同时检查帖子和评论的原文时间。时间缺失、正文缺失或窗口外记录不作为近期证据。评论必须与本次窗口内的父帖一起采集。正文来自已加载 DOM；未加载、折叠、删除和隐藏内容不会补全。`num_comments` 是页面显示数，不能当作已采集数。即使数量相等，完整评论覆盖仍标为未知。保留原文链接、快照哈希、加载数、保留数及可见遗漏控件。
