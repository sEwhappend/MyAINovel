# My AI Novel

## 项目简介
My AI Novel 是一个本地运行的结构化小说生产流水线桌面程序。它通过兼容 OpenAI API 协议的 LLM 服务，辅助用户从世界书、资料库角色卡和总体框架出发，逐步完成大纲丰满、章节拆分、小节规划、正文粗稿、审稿、改写和定稿。

## 已实现功能
- 本地桌面 UI（PySide6 优先，自动回退到 legacy tkinter UI）。
- 小说项目创建和基础设定管理。
- 项目“总目标字数/篇幅”用于总体框架拆分后的章节/小节目标字数预算。
- Scrivener / Obsidian 风格项目文件夹：默认保存在 `projects/`，一个项目一个文件夹。
- 项目数据同步为人能直接打开的 `.json`、`.md` 文件；SQLite 保留为运行时索引和旧数据迁移来源。
- 世界观资料库：角色卡、地点、组织、规则、时间线、伏笔、禁止事项。
- 资料库写作优先级：组织/势力与角色卡优先，其次伏笔、地点和时间线。
- 丰满总体框架，并生成可确认的章节/小节拆分建议。
- 用户手动确认后拆分正式章节和小节。
- 确认拆分总体框架后，会自动把结构化字段中的角色卡、地点、组织/势力、规则、时间线、伏笔和禁止事项写入资料库候选。
- 章节/小节支持时间、地点、人物、目标、冲突等字段。
- 章节界面可调用资料库，把当前章节/小节相关资料作为写作参考展示。
- 章节人物字段可直接从资料库角色卡中选择。
- 章节地点字段可直接从资料库地点设定中选择；第一版仍保留手动输入。
- OpenAI-compatible LLM 配置和连接测试。
- 支持显式 HTTP/HTTPS 代理配置，例如 `http://127.0.0.1:7890`。
- 自动扫描 Provider 可用模型，读取 OpenAI-compatible `GET /models`。
- 支持手动模型候选；远程模型扫描失败时仍可使用已配置模型、手动候选或内置候选。
- 针对 `HTTP 403` / `error code 1010` 提供更明确连接诊断。
- 可修改最大 token、Temperature、Top-P、Top-K、Presence Penalty、Frequency Penalty。
- API key 保存到当前目录 `./.json/llm_config.json`。
- 模型和网络相关操作使用后台线程执行，避免长时间 API 请求卡住主窗口。
- 关键词、标签和可选向量检索。
- 多 Agent 固定流水线：全书架构、章节架构、小节规划、场景导演、对白心理、正文写作、审稿、改写。
- 版本保存、版本比较、定稿、取消定稿。
- “继续下一节”要求上一节已定稿。
- 全书 Word 导出：只导出已定稿小节，未定稿小节自动跳过。

## 架构说明
项目数据会同步到本地 `projects/` 项目文件夹，SQLite 继续作为运行时索引、调用日志和旧数据迁移来源。UI 只调用服务接口，不直接拼 LLM prompt。`NovelPipeline` 负责固定写作流水线，`LLMClient` 负责 OpenAI-compatible HTTP 请求，`NovelStore` 负责项目、资料、章节、小节、版本和日志，`project_files` 负责人类可读文件同步，`exporter` 负责 Word 导出。

## 目录结构
```text
.
├── run.py
├── README.md
├── LICENSE
├── requirements.txt
├── docs/
│   └── releases/
├── src/my_ai_novel/
│   ├── app.py
│   ├── llm.py
│   ├── models.py
│   ├── pipeline.py
│   ├── project_files.py
│   ├── prompts.py
│   ├── retrieval.py
│   ├── review.py
│   ├── storage.py
│   ├── exporter.py
│   └── ui.py
├── tests/
├── projects/      # 运行后生成，每个小说项目一个文件夹
├── data/          # 运行后生成，本地 SQLite 索引/日志/旧数据来源
└── .json/         # 运行后生成，本地 LLM 配置
```

## 环境要求
- Python 3.11+
- PySide6（默认 UI）
- CustomTkinter（legacy 回退 UI）
- 一个兼容 OpenAI API 协议的 LLM 服务，提供 `base_url` 和 `api_key`

## 安装
确认 Python 可用：

```bash
python --version
```

安装依赖：

```bash
python -m pip install -r requirements.txt
```

## 配置
在 UI 的“设置”页填写：
- Base URL
- API Key
- 代理地址，可选，例如 `http://127.0.0.1:7890`
- 正文模型
- 架构/审稿模型
- 可选 Embedding 模型
- 模型候选，每行一个模型 ID，可选
- 超时秒数
- 最大 token
- Temperature
- Top-P
- Top-K
- Presence Penalty
- Frequency Penalty

点击“扫描模型”可以自动请求：

```text
GET {base_url}/models
```

扫描成功后会显示可用模型列表，并在模型字段为空时自动填入推荐值。扫描失败不会覆盖已有模型配置。

模型发现采用配置优先策略：

1. 优先使用你已经填写的正文模型、审稿模型、Embedding 模型。
2. 其次使用“模型候选”里手动填写的模型 ID。
3. 再尝试远程 `GET /models`。
4. 如果远程主机关闭连接或 `/models` 不可用，会按 Provider host 显示少量内置候选。

内置候选只用于帮你填表，不代表账号一定有权限；最终是否可用以“测试连接”和实际生成结果为准。

如果“测试连接”显示 `HTTP 403` 且包含 `1010`，通常不是程序语法错误，而是 Provider 侧拒绝访问。常见原因包括：

- `base_url` 填错，尤其是多写或少写 `/v1`
- API key 没有模型或接口权限
- Provider 网关或 Cloudflare 访问规则拦截
- 当前网络、IP、地区或来源被限制
- 该 Provider 不允许普通客户端直接访问对应端点

如果 Provider 后台没有收到请求，请先填写“代理地址”后重试。第一版只支持 HTTP/HTTPS 代理地址；`socks5://` 需要额外依赖，当前未实现。

配置保存到当前工作目录下：

```text
.json/llm_config.json
```

## 项目文件
默认项目目录：

```text
projects/
  project-<id>-<项目名>/
    project.json
    worldbook.md
    style.md
    library/
    chapters/
    versions/
    exports/
```

旧 SQLite 数据会在程序启动或 `NovelStore` 初始化时自动同步到项目文件夹。第一版同步方向是 SQLite 到项目文件夹；暂不实现从文件夹反向覆盖 SQLite。

## 运行
```bash
python run.py
```

## 测试
```bash
python -B -m unittest discover -s tests
```

## 使用示例
1. 运行 `python run.py`。
2. 在“项目”页创建小说项目，填写世界书、写作风格和总体概括。
   “总目标字数/篇幅”可以填写 `80000`、`8万字`、`约10万` 这类值。
3. 在“资料库”页用“角色卡”类型维护人物资料。
4. 在“设置”页填写 LLM API 信息并测试连接。
5. 在“设置”页点击“扫描模型”，确认可用模型并保存配置。
6. 在“总框架”页点击“丰满总体框架”。
7. 检查候选框架后点击“确认并拆分章节”。
8. 确认拆分后，去“资料库”页检查自动创建的候选资料，必要时补全或修改。
9. 在“章节”页编辑章节和小节的时间、地点、人物、目标和目标字数；人物可从资料库角色卡中选择，地点可从资料库地点设定中选择。
10. 点击“调用资料库”查看写作参考。
11. 在“写作”页生成粗稿、审稿、改写、锁定定稿。
12. 当前小节定稿后点击“继续下一节”。
13. 在“项目”页点击“导出全书 Word”，导出的 `.docx` 保存在当前项目 `exports/` 目录，未定稿小节会被跳过。

## 主要设计决策
- 第一版核心逻辑使用 Python 标准库，桌面 UI 使用 CustomTkinter 改善观感。
- 项目文件夹作为可读数据副本，SQLite 保留为索引和旧数据迁移来源。
- Word 导出用标准库生成基础 `.docx`，不引入 `python-docx` 依赖。
- API key 不进入 SQLite，只保存在当前目录 `.json/`。
- 无 embedding 模型时，检索自动降级到关键词和标签。
- 定稿内容默认锁定，普通生成和改写不能覆盖。
- 模型发现参考 opencode/Codex 的配置优先思路，不把远程 `/models` 当成唯一来源。
- 资料库采用“候选先落库、用户再确认修改”的工作流：拆分总体框架后自动创建候选资料，但章节界面仍允许手动输入，避免第一版强行阻塞写作。
- 总目标字数在确认拆分时落到小节 `target_words`：模型没有给字数时均分，模型给出的总和偏差明显时按比例归一化。
- 长耗时模型调用和模型扫描在后台线程执行，完成后再刷新 UI。

## 已知限制
- 当前自动化测试没有打开真实 tkinter 主窗口做人工点击验证。
- 未在当前环境使用真实 API key 测试连接。
- 未在当前环境使用真实本地代理访问外部 Provider。
- 未确认内置模型候选是否匹配用户具体 Provider 账号权限。
- 第一版项目文件同步以 SQLite 为当前运行时索引；从项目文件夹反向导入/合并尚未实现。
- 自动资料库候选只从结构化字段提取，不从自然语言大纲中强行抽取实体。
- 字数预算按全书小节统一归一化；第一版不做复杂章节级权重或高潮/过渡权重分配。
- 第一版 Word 导出只包含基础段落结构，暂不包含复杂样式。
- OOC、世界观矛盾等审稿判断依赖资料库质量和模型能力。
- 第一版未实现云同步、多用户、富文本编辑器和插件系统。

## 后续计划
优化数据库的提示词，增加更好的ui，支持模型的分段写入：实现正常剧情普通模型写作，r剧情用特定模型写作
