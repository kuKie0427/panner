# panner — 二开方向

> 本文件是个人 fork 的工程方向笔记,不是 upstream 文档。upstream 是 `smolagents`(Apache-2.0, HuggingFace),fork 时已 rebrand 为 `panner`。所有方向以 **数据分析师 / analytics engineer 单一 persona + DuckDB 单一 warehouse + citation grounding 单一主战场** 为锚,不追求与 upstream 同步,不为多场景泛化。

## 一句话定位

`panner` 是面向 **数据分析师 / analytics engineer 会读 Python 的用户** 的 CodeAgent,跑在 **DuckDB 嵌入式** 数据上。用户用自然语言提问,LLM 产 Python 代码执行 SQL / dataframe 操作。**单一主战场:每行答案必须有 SQL `source_query_id` 追溯,无 grounding 一律拒答,不让 LLM 编数字**。

## 业务边界

**目标场景**:
- 数据分析师 / analytics engineer 跑探索性数据分析:"上周华东区销售 top 5 店铺"
- 多轮 NL → SQL → Python 探索:`describe` → `groupby` → `join`,变量跨步持久
- 无 grounding 拒答:LLM 不能编("我没有数据支撑这个答案")

**不在范围 (OOS)**:
- Multi-Agent 协作 — 一个 CodeAgent 一个分析师已够,不为加 agent 而加
- 多 warehouse — 只 DuckDB 嵌入式(PostgreSQL / BigQuery / Snowflake 全 OOS,方言负担不为个人 fork 所负)
- 可视化 / plot — matplotlib / altair 等输出用 Jupyter cell 即可,CodeAgent 不内嵌
- PII 治理 / 合规 redaction — DuckDB 嵌入式无远端 credentials 场景,analyst 本机查数 PII 风险面不在 fork 战场
- 跨会话 alias / 长期记忆 — workflow 用 system prompt prefix / 笔记即可解决,堆 memory 是 md 笔记警告的「装饰」
- 实时流处理 — 批量探索,流处理不是 fork 的活

**真背书**(逐条注核准确性,2026-07-13 复核):
- **RAGAS** — `Ragas: Automated Evaluation of Retrieval Augmented Generation` (arXiv:2309.15217, 2023-09, v2 rev 2025-04),作者 **Shahul Es, Jithin James, Luis Espinosa-Anke, Steven Schockaert**(4 人)。RAG 评估框架,grounding / context recall / answer faithfulness 度量学;panner 把它的 faithfulness 指标迁移到 CodeAgent 答数字场景 — 与 citation 主战场同生态交集明确
- **ARES** — `ARES: An Automated Evaluation Framework for Retrieval-Augmented Generation Systems` (NAACL 2024, arXiv:2311.09476),作者 **Jon Saad-Falcon, Omar Khattab, Christopher Potts, Matei Zaharia**(4 人)。Automated RAG Evaluation 思路对应 panner Phase 4 `analytics_bench` 自动化评估
- **smolagents CodeAgent 范式** — `huggingface/smolagents`,Apache-2.0,28.3k⭐,官方 BibTeX 年份 **2025**(不是 2024)。作者 Aymeric Roucher / Albert Villanova del Moral / Thomas Wolf / Leandro von Werra / Erik Kaunismäki。**关键 caveat**(smolagents README 自明):「The built-in LocalPythonExecutor is not a security sandbox. It applies some restrictions but can be bypassed and must not be used as a security boundary.」 — 即 panner 不能直接 trust smolagents LocalPythonExecutor 做 sandbox 真边界,需自己加 hook(见 Phase 1 决策 D1)
- **dbt data tests** — 由 **dbt Labs, LLC**(不是 Rittman)出品,文档 `docs.getdbt.com/docs/build/data-tests`,2026-07-09 last updated,『singular data tests』+『generic data tests』 + YAML `data_tests:` 范式(原 `tests:` 仍兼容)。dbt 测试证明 NL→SQL pipeline prod 价值,但缺 grounding 闸([Mark Rittman](https://rittman.com) 是 dbt 知名 BI 博主,不是论文/项目作者,引用需避免归因)
- **DuckDB 嵌入式 SQL** — `DuckDB: An Embeddable Analytical Database` (SIGMOD 2019 demo),作者 **Mark Raasveldt, Hannes Mühleisen**。嵌入式 columnar,no external dependencies,无 network credentials,简化沙箱边界 — 与 panner 单 DuckDB scope 同生态
- **smolagents LocalPythonExecutor** — smolagents 官方自承「not a security sandbox, can be bypassed」。授权白名单 + 黑名单 + AST hook 是真边界,但**不能依赖 smolagents runtime 不被绕**;panner 的 sandbox 设计在 `LocalPythonExecutor` 之上加 hook,Phase 1 决策 D1 已显式

## 设计原则

1. **Citation-first, not narration-first** — 每行答案必须附 `source_query_id` (原始 SQL 在 execution_log 中可回查);无 source 的答案一律 framework 强制拒答(不是 LLM 自我审查,是 framework post-processor 拦截)
2. **Think in code, not tool JSON** — 保留 smolagents CodeAgent 范式,不引入 ToolCallingAgent;Python 源码是单一执行表达
3. **Sandbox by default** — `LocalPythonExecutor` AST 默认,`authorized_imports=["pandas", "duckdb", "numpy"]` 显式白名单 + subscript 黑名单 `pandas.io.*`(防 `LocalPythonExecutor` AST 边界逃逸)。**pandas API 用法表**(防 LLM 走 pandas 绕 SQL 破 citation 主战场):
   - `pandas.read_sql` / `read_sql_query` — ✅ **强制**(LLM 必须走它读 DuckDB,走入 `execution_log` → CitationChecker 反查)
   - `pandas.DataFrame.merge` / `groupby.agg` / `pivot` — ❌ **禁用**(强制走 DuckDB SQL `JOIN` / `GROUP BY` / `PIVOT`,进 execution_log)
   - `pandas.read_csv` — ⚠️ **允许但 grounding 标 `csv_source` 非 `source_query_id`**(LLM 写答案时 framework 提示「数据非 warehouse 内」,不能与 SQL 输出混算)
   - `numpy` — ✅ 允许(纯数学,无 SQL 副作用)
   - **DuckDB sandbox 边界**:`INSTALL` / `LOAD` extension ❌ 拒(OOS,LLM 不该 install 远程拓展 → 沙箱越界);`ATTACH` 仅允许 `:memory:` 或当前会话 own db(防跨 .duckdb 文件 ATTACH 进生产 prod db 数据混入)
   - untrusted queries 可 swap `DockerExecutor`,但默认 `LocalPythonExecutor` + 上述用法表够
4. **Citation needs storage** — citation 的 `source_query_id` 需要 stable 可回查的 SQL 执行日志 + 大结果 parquet 路径,这俩共享同一 `execution_id`(Phase 2 支撑层)
5. **No cross-session decoration** — schema/memory `self.state` 跨 turn 必要;跨 session / cross-incident 记忆 OOS,堆就是 md 笔记警告的「装饰」

## 失败模式 / 已知 ⚠️

- ⚠️ **LLM 综合文字阶段编数字** — 跑完 SQL 拿到 stdout 后,LLM 在 final_answer 阶段可能把 6 个数字综合成一段话时混淆 / 推断 / 编(例:SQL 跑出 top 5 营收数字,LLM 写总结时多写一句"环比增长 15%"这种 SQL 没算的)。缓解:**framework post-processor 强制 ground**(每个数字 token 都要在 execution_log 找到对应 SQL 输出)。LLM 自我审查不可靠 — 是循环引用
- ⚠️ **Citation 对 dataframe-only 答案** — 纯 pandas 操作(没经过 SQL)的答案没有 `source_query_id`,grounding 怎么定义?**强制 dataframe 操作也走 DuckDB SQL 走入 execution_log**(`pandas` 数据 join 转译为 DuckDB `INSERT INTO ... SELECT ...`),否则 framework 拒答
- ⚠️ **`schema_cache` drift** — DuckDB `CREATE TABLE` / `ALTER TABLE` 后 schema_cache 旧,LLM 跑基于旧 schema 的 SQL → 数字基于错列 / 错类型。缓解:每个 turn 起手 hash `duckdb_tables()` + 列 schema比对,不匹配重拉
- ⚠️ **AST 沙箱越界** — 即使 `authorized_imports=["pandas", "duckdb", "numpy"]` 加 subscript 黑名单 `pandas.io.*`,`pandas` 仍可能走 `pandas.io.sql` / `os.popen` 类二级包装,`LocalPythonExecutor` 在 module 边界就失效。缓解:在 `LocalPythonExecutor` 内 hook `__import__` 子模块解析,`pandas.io.*` / `pandas.io.sql` 子模块显式拒 + 上文 pandas API 用法表的 `merge`/`groupby.agg`/`pivot` 也在 hook 层拒
- ⚠️ **拒答变成 lazy 拒答** — LLM 学到答不出的就拒,refusal_rate 高但 accuracy 低。缓解:评测集 **联合度量** (accuracy / refusal_rate / citation_attachment_rate 三条线同时跑,单独拒答率上升而 accuracy 不升 = 退化告警)
- ⚠️ **`truncate_content` 旧 20K bug** — `utils.py` 现有 `truncate_content` 字符截断把 SQL 大结果切成不可解析,LLM 误读截断后的 schema → 跑基于错误布局的 SQL。缓解:Phase 2 result_storage 改造完成后 truncate_content 仅做底线防御,主路径走 parquet 写盘 + path 引用
- ⚠️ **DuckDB `INSTALL`/`ATTACH` 绕 audit** — LLM 跑 `INSTALL sqlite FROM '...';` 加载远程扩展,或 `ATTACH 'prod.db' AS prod` 跨 .duckdb 文件挂载生产库,沙箱越界 + 跨生产数据混入,且不在 `pandas.io.*` 黑名单管得到的地方(`duckdb` Python 模块直接调)。缓解:Phase 1 sandbox 加 DuckDB 命令层拦截 — `INSTALL` / `LOAD` / `ATTACH ... AS ...` 不是 `:memory:` 一律 framework 拒,落 `execution_log.deny_reason='sandbox_violation'`
- ⚠️ **LLM 走 pandas 绕 SQL 破 citation** — LLM 用 `pandas.merge` / `groupby.agg` 在 pandas 层 join + 聚合,绕 DuckDB SQL → `execution_log` 无记录 → CitationChecker 反查不到 → 该走拒答降级,但 LLM 看似给合理答案让框架拦截不到。缓解:framework sandbox 监控 pandas API 用法,`merge` / `groupby.agg` / `pivot` 在 `LocalPythonExecutor` 层拒(运行前拦截),强制走 DuckDB SQL

## Roadmap

> **重排说明**:原文 Phase 1 = result storage、Phase 3 = citation,但 citation 是 fork 主战场,result storage 是它的支撑。重排后 Phase 1 = citation(主),Phase 2 = result storage / sql execution log(支撑),Phase 3 = schema memory(支撑),Phase 4 = eval。`redaction` 整个 Phase 移除,PII 治理 / 跨 warehouse 平等承诺 — 现 OOS。

### Phase 1 — Citation Grounding + Refusal (主战场)

**目标**:每行答案必须附 `source_query_id`,framework post-processor 强制检查;无 grounding 的答案一律拒绝(不是 LLM 自我审查,是 framework 拦截)。

**依赖**:Phase 2 SQL execution_log 必须并行落地 — citation 需要可回查的 SQL 执行记录。两个 phase 边开发边互哺,Phase 1 落 schema,Phase 2 落存储。

文件:
- `src/panner/citation.py` (新)
  - `CitationChecker` 类:接 `final_answer` 输出 + `execution_log`
  - 抽取答案中所有 numeric / categorical claim token
  - 每个 token 反查 `execution_log` 是否有对应 SQL 输出
  - 任一 token 无 source → 返回 `RefusalAnswer` "I don't have data to support this answer."(文字 + 原 SQL list 选填可参考全 LLM 重新生成)
- 修改 `src/panner/agents.py` 的 `CodeAgent.final_answer` 流程
  - 在 LLM 生成 final_answer 之后,framework 不可信之前,**插入 `CitationChecker`**
  - 通过检查的答案照常返回;未通过的 answer 替换为 `RefusalAnswer`,并把 `attempt_id` 写入 failure log
- `src/panner/prompts/citation_system_prompt.yaml` (新)
  - 系统注入 prompt 强约束:"答案中每个数字必须有 `source_query_id` XML tag 标注来源"
  - 但**系统 prompt 是软约束**,真正拦截在 framework 层 — 不依赖 LLM 自觉
- `src/panner/execution_log.py` (新) — Phase 1 提前用最小版
  - `execution_log: list[{execution_id, query_id, sql, stdout_truncated, started_at, finished_at}]`
  - in-memory list 起步(Phase 2 改 SQLite 持久 + parquet 大 stdout 外存)

测试:
- `tests/test_citation_checker.py` — 30 个有/无 source 的 answer 案例,验证拦截率
- `tests/test_citation_refusal.py` — 20 个 out-of-scope 提问(agent 没数据时,framework 必拒)
- `tests/test_citation_workflow_e2e.py` — 完整 NL → SQL → final_answer → CitationChecker 流程,mock LLM 跑通

L1 scope 硬锁(防 scope creep):
- ✅ 做:framework citation 拦截 / refusal / execution_log 记录 / prompt 软约束注入 / **DuckDB `INSTALL`/`ATTACH` sandbox 拦截** / **pandas API 用法边界强制**(`read_sql` 强制入口 / `merge`·`groupby.agg`·`pivot` 运行前拒 / `numpy` 允许)
- ❌ 不做:LLM 自动评分自己答案 / 自动改写后重试 / 跨 incident 引用历史 SQL / DuckDB `INSTALL`/`LOAD` extension 允许 / `ATTACH` 非 `:memory:` 跨文件允许 / pandas 层 join·聚合允许

**验证**:
- citation attachment rate ≥ 95% on `analytics_bench` 真有 ground truth SQL 的 case
- refusal rate ≥ 90% on out-of-scope case(agent 没相关 SQL 时应拒)
- 「3 个编数字」对抗 case 必须拒(选 3 个 SQL 没算的「胜行总结补数字」case,CitationChecker 必拦)

### Phase 2 — SQL Execution Log + Result Storage (支撑)

**目标**:为 Phase 1 提供 stable 可回查的 SQL 执行日志;为大 DataFrame 提供外存,LLM context 只拿 schema + preview + path 引用。

**依赖**:Phase 1 已定义 `execution_log` 接口的 minimum schema;Phase 2 落地 SQLite 持久化 + parquet 外存。

文件:
- `src/panner/execution_log.py` (扩,Phase 1 的最小版 → 持久版)
  - SQLite `~/.panner/execution_log.db` 表 `sql_executions`:execution_id / query_id / sql / stdout_truncated / stdout_path / started_at / finished_at / exit_code
  - 写盘 atomic: `tempfile + os.rename` 防并发写撞
- `src/panner/utils/result_storage.py` (新)
  - 替换 `src/panner/utils.py` 的 `truncate_content` 旧 20K bug
  - DataFrame > N 字符(默认 20K) → 写 `~/.panner/results/<execution_id>_<query_id>.parquet`,atomic 写
  - LLM context 中此 result 替换为:schema + 5 行 sample(随机或 head,见开放问题 5) + path
  - agent 跨 turn 引用 `read_result(execution_id, query_id)` 重新加载
- 修改 `src/panner/utils.py` `truncate_content`
  - 路径分两类:小结果照旧 truncate;大结果改走 result_storage.parquet

测试:
- `tests/test_execution_log.py` — 并发写 10 条 SQL 执行记录,query_id 唯一,atomic 写
- `tests/test_result_storage.py` — 50K / 500K / 5M row dataframes 写盘不爆 context;同时验证 LLM context 拿到 schema + preview + path 三件
- `tests/test_result_storage_concurrent.py` — 2 个 agent 同时跑同一 hash 不撞写

**验证**:50M row 不爆 context;sample preview 行 schema 保留原始列名 + dtype 不丢真 distribution

### Phase 3 — DuckDB Schema Memory (支撑)

**目标**:跨 turn 同会话内 schema 不重复拉,但随 schema 变 (`CREATE/ALTER TABLE`) 自动失效;**只在 `self.state` 跨 turn,不跨会话**。

**依赖**:Phase 2 execution_log 已落地,Phase 3 可以把 schema 拉的 SQL 也存进 execution_log 当作普通查询。

文件:
- `src/panner/tools/schema_memory.py` (新)
  - `load_schema()` 首次问起:跑 `SELECT * FROM duckdb_tables() JOIN duckdb_columns() USING (table_name)` 走入 execution_log
  - 缓存到 `self.state["schema_cache"]`,带 `schema_hash`(列名 + 类型的 hash)
  - 每个 turn 起手 compute `duckdb_tables()` 现有 hash,与 cache 比对 — 不匹配则重拉 + 标 `schema_drifted_at`
  - **不存盘,session 结束即焚**

测试:
- `tests/test_schema_memory.py` — 多轮探索中 schema 加入 1 次,后续不重拉
- `tests/test_schema_drift.py` — turn 中 `CREATE TABLE`,下一 turn schema_cache 必失效重拉

**验证**:同会话内 10 个 turn 只拉 1 次 schema(除非 drift)

### Phase 4 — Eval suite (回归)

**目标**:20 条真 corpus 任务(不是「自编样本」,每条写明来源),via in-memory DuckDB,全走 mock LLM `rig/llm/llm_mock.py` 或真 LLM 联合跑。

文件:
- `tests/eval/analytics_bench/` (新)
  - **TASKS_DATA.csv** — 20 个任务(每行:`task_id` / `source_real_corpus` (URL / 来自哪个真数据集)/ `input_nl` / `ground_truth_sql` / `expected_refusal` (false/true))
  - **run_eval.py** — 三类度量联合产出:
    - numeric_accuracy:ground truth SQL vs agent SQL 算的数字 (±0.01 浮点误差)
    - citation_attachment:答案中每个数字是否有 source_query_id 对应 (经 CitationChecker 确认)
    - refusal_rate:expected_refusal=true 的 case 拒答率
  - 输出三件趋势线 + 失败 case 归因(意图 / SQL / 工具 / 推理 哪一坏)
- `tests/eval/analytics_bench/fuzz_citation.py` (新)
  - 3 个对抗 case:agent 跑完 SQL 后强制写「胜行补 blah-blah」的 hallucinated total
  - Verification:CitationChecker 必拒 + execution_log 留痕

**验证三种回归**:
- 一次 PR 后 numeric_accuracy 不降 + refusal_rate 不降 + citation_attachment_rate 不降 — 三条线独立有 offset;单独拒答率上升而 accuracy 不升 = 退化告警(用联合度量防 lazy 拒答)

## md 6 件事映射

> 每个 cell 按 md 笔记「针对什么业务问题 / 基于什么技术机制 / 设计什么工程方案 / 实现什么可验证效果」三层来填,不是名词贴标签。

| md 维度 | panner 落地 |
|---|---|
| **任务边界** | **替谁**: 数据分析师 / analytics engineer(会读 Python 的数据分析者,不是业务用户)<br>**做什么**: 针对探索性数据分析「LLM 跑完 SQL 综合总结时编数字」问题,在 DuckDB 嵌入式数据上跑 NL→Python→SQL→结果链,framework 强制每数字附 `source_query_id`<br>**不做什么**: multi-agent / multi-warehouse / 可视化 / PII 治理 / 跨会话 alias / 实时流 — 全 OOS,simple workflow 能解就别堆 |
| **工具契约** | **参数校验**: `authorized_imports=["pandas", "duckdb", "numpy"]`,subscript 黑名单 `pandas.io.*`;**pandas API 用法表**(`read_sql` 强制走 DuckDB 入 `execution_log` / `merge`·`groupby.agg`·`pivot` 在 `LocalPythonExecutor` 运行前拒 / `read_csv` 允许但 grounding 标 `csv_source` 非 `source_query_id`);**DuckDB sandbox 边界**(`INSTALL`/`LOAD` extension 拒 / `ATTACH` 仅 `:memory:` 或 own db);Excel `xlsx` 输入 OOS<br>**失败回退**: SQL 跑挂(stderr 返 LLM 改写 1 次,不无限重试)/ long-running > N s framework cancel<br>**业务规则 / 副作用**: DuckDB 嵌入式无 network credentials 风险面;每 SQL 走入 `execution_log` 留 `query_id`+`stdout_truncated` 作为 citation 反查基线 |
| **上下文策略** | **什么进**: schema(小)进 LLM context,跨 turn 由 `schema_cache` 持,turn 起手 hash 比对不匹配重拉<br>**什么不进**: 大 DataFrame 直接走 `~/.panner/results/<execution_id>_<query_id>.parquet`,context 只放 schema + 5 行 preview + path 引用<br>**什么先摘要**: 大结果 schema 必进,行级 data 走 parquet;`source_query_id` 标 token 走 execution_log 可回查(Phase 1+2 联动) |
| **状态管理** | **跨 turn 必要**: `self.state["schema_cache"]` 跨 turn;`execution_log` session 内累积供 citation 反查<br>**跨会话 OOS**: alias / query history / cross-incident memory 全 OOS — md 笔记「简单 workflow 能解就别堆」+「记忆被恶意写入怎么办」反问都答不上来<br>**用完即焚**: session 结束 `self.state` 清;`execution_log.db` 默认每会话清空(或 LRU 7 天) |
| **权限确认** | **高风险动作**: DuckDB 嵌入式在 analyst 本机,无多人协作 N-of-M 场景;DML / DDL(`CREATE / INSERT / DROP`)默认 framework 拦截 + 提示「DuckDB 文件级操作,工作单元级」,可配 `RIG_WRITER_ENABLED=true` 单 session 内允许<br>**兜底**: 拒答时给 SQL 原文 + 解释;**调低后无 anti-fatigue**(单人不会 rubber-stamp)<br>**Citation 是更大的权限闸**: 比人审更频繁,framework 自动检,所有数字都要过 |
| **评测集** | **成功标准**: `analytics_bench` 20 条真 corpus 三类度量联合产出 — numeric_accuracy (±0.01 浮点 vs ground truth SQL) + citation_attachment_rate (CitationChecker 拦截后留下的数字是否有 source) + refusal_rate (out-of-scope 应拒)<br>**代表性**: 20 条每条标明来源(URL / 真数据集名),**约为 50 条自编** md 笔记「真实用户问题不是凭空造题」更严<br>**归因**: 失败 case 分类意图 / SQL / 工具 / 推理 哪一层坏;联合度量防 lazy 拒答 |

## Non-goals

- ❌ Multi-agent — 一个 CodeAgent 一个分析师已足,加多 agent 是装饰(md 笔记「为什么不能用单 Agent + workflow 解决」反问答不上来)
- ❌ Multi-warehouse — 4 个方言负担不为个人 fork 所负;DuckDB 单方言够覆盖 citation grounding 叙事(PostgreSQL / BigQuery / Snowflake 全 OOS)
- ❌ 可视化 / plot — matplotlib / altair 用 Jupyter cell 即可,堆 CodeAgent 内是 md 笔记警告的「装饰」
- ❌ PII 治理 / redaction — DuckDB 嵌入式本机无多人 / 远端 credentials 场景;analyst 本机查数 PII 风险面真在fork 战场外
- ❌ 跨会话 alias / query history — workflow 用 system prompt prefix / 笔记即可解决,堆 memory 是「记忆被恶意写入怎么办」「旧记忆怎么 invalidation」反问答不上来
- ❌ 从 0 写 sandbox — `LocalPythonExecutor` AST 已够;危险任务走 `DockerExecutor`
- ❌ 重新设计 Tool 抽象 — smolagents `Tool` class 够用,不为加抽象而加
- ❌ Web UI — 沿用 `gradio_ui.py` 或不出 UI,主要交互是 CLI
- ❌ 跨语言数据(Rust / Go integration) — Python 生态 pandas / duckdb 即可
- ❌ 实时流处理 — 批量探索,流处理不是 fork 的活
- ❌ LLM 自我审查 / LLM-as-judge 当唯一 groundding — 循环引用,真拦截必须 framework 强制 post-processor
- ❌ Excel (`xlsx`) 输入 — 数据分析师请先转 CSV / parquet;Excel 是数据接入副作用不是 fork 战场,与 plot 同档(若用户真有 Excel 流,DuckDB spatial 扩展解决,但 OOS,不为本 fork 加 extension install 通路)

## 隐藏决策落地 + Plan-level Pre-Flight

> 由 Oracle 第三方审查指出未锁定的三个根本设计决策(D1:pandas API 是否真边界,D2:派生数字 detect,D3:mock LLM 性质),本节硬锁。完整 template 见 `/md/00-FORK_PLANNING_CHECKLIST.md`。

### D1 — pandas API 用法表是真边界还是 prompt 软约束 ✅ 已锁

**真边界 / framework 强制**,具体落地:

- `LocalPythonExecutor` 改 hook `__import__` 与 `getattr`:
  - `pandas.DataFrame.merge` / `groupby.agg` / `pivot` / `query` / `eval` 在 AST parse 后 callable 检查阶段拒
  - `pandas.read_*`(`read_json` / `read_html` / `read_sql` / `read_parquet`)只允许:`read_csv`(granting `csv_source` grounding)+ `read_sql`+ `read_sql_query`(走 DuckDB 入 `execution_log`)
  - `pandas.DataFrame.values` / `df.to_numpy()` / `Series.values` 拒绝(强制走 DuckDB)
  - `pandas.DataFrame.apply(任意 Python 函数)` 拒绝(force DuckDB SQL aggregate)
- `numpy` 允许:仅纯数组算术(`numpy.add` / `mean` / `std` 等);拒绝 `numpy.loadtxt` / `fromfile` / `genfromtxt` / `load` 等文件读路径
- `duckdb` 模块允许:仅调用 `execute` / `sql` / `from_df` 等标准 connection 方法;拒绝 `duckdb.sql` 参数以 `INSTALL` / `LOAD` / `ATTACH` 开头
- **prompt 中「pandas API 用法表」是软约束**;以上 sandbox hook 是**硬约束**,framework 拒绝时不依赖 LLM 自觉
- 测试:`tests/test_sandbox_pandas_bypass.py` 50+ 用例覆盖:每条 pandas 逃逸路径 mock LLM 写出"应该走的"代码,framework 必须 sandbox 拒

### D2 — 派生数字(15% 从 100→115 算出) 怎么 detect ✅ 已锁

**算式链 DAG 反查 + framework 强制**,具体落地:

- CitationChecker 不只查「数字在 execution_log 出现过没」,还要查**出现链路**:每条 SQL 输出作为 DAG 节点,后续 SQL 引用前驱结果时建立有向边
- 答案 token 反查路径:**某个 token 必须能在 execution_log DAG 中找到**:
  - 直接出现:`100` → query_id_q1 output_row_2 ✓
  - 派生出现:`15%` → 来自 `query_id_q3 = q2 / q1` 算式节点输出 ✓
  - 凭空出现:`环比增长 15%` 中「15%」与 `15` 不在 execution_log 任一节点输出 → framework 拒答
- 落地:
  - `execution_log.sql_executions` 表新加 `derived_from_query_ids JSON` 字段,标识「该 SQL 输出是否由前驱查询派生」
  - `CitationChecker` 在 match token 时除查 stdout 集合,**也查 derived_from 链可达集合**(BFS 沿 DAG 走)
  - 例:`100 → 115 → 15%` 三条 SQL execution,execution_log 留 `q1.output=[100]`, `q2.derived_from=[q1] output=[115]`, `q3.derived_from=[q1, q2] output=["15%"]`,框架追到「15%」能走到 q3,放行;「环比增长 7%」找不到 derivation chain,拒答
- 性能 budget:`execution_log` DAG 节点数通常 < 100,DAG 遍历 < 1ms,framework 拦截开销忽略
- 测试:`tests/test_derived_citation.py` 30+ 用例覆盖:difference / ratio / percentage / YoY / QoQ 等典型派生;凭空数字必拒

### D3 — mock LLM 性质 + 真 LLM gap 量化 ✅ 已锁

**双轨制,metric 不混**:

- **`mock LLM` = fast feedback 路径**:`Phase 4/analytics_bench/run_eval.py --mock` 开关,用于 PR 时间预算 < 5 min 的 framework 路径回归,只验证「代码改了以后框架行为没退化」
- **`真 LLM` = nightly 验证路径**:`run_eval.py --model {anthropic/claude-haiku-4-5 | openai/gpt-4o-mini}`,每个 model 各跑一遍,时间预算 ~1 h,仅 nightly cron 触发
- **mock LLM 不进入「防 LLM 编数字」类 metric 复审**:mock LLM 是 deterministic 不会 hallucinate,跑出来的 `citation_attachment_rate` / `refusal_rate` 不代表真 LLM 行为,**只在 PR 阻断回归;真 LLM 三类度量是 nightly 出的图,曲线差异是信号**
- Phase 4 验收集成 `tests/eval/analytics_bench/curve_diff.py`:`mock_run.json` vs `real_run_nightly.json` 两条曲线 diff,长期看两线 invariant / regression 报告
- CI 配置:`make eval-mock`(PR 触发,< 5 min)/ `make eval-real`(nightly cron,~ 1 h,env var `RIG_ANTHROPIC_API_KEY` / `RIG_OPENAI_API_KEY` 需配置)

### Pre-Flight 自检(`/md/00-FORK_PLANNING_CHECKLIST.md` 12 条)

| # | Checklist | 状态 | 位置 |
|---|---|---|---|
| **A1 部署形态** | ✅ | D1-CLI 单进程 in-memory execution_log (Phase 1)/ SQLite 持久 (Phase 2) — 显式声明 |
| **A2 Identity / SSO** | n/a | panner 是单 persona 本机工具,无多人协作场景,SSO 不适用 |
| **A3 审批者池组装** | n/a | panner 无人审,framework 强制单边决断(避循环引用) |
| **A4 时间窗 fallback** | n/a | 同 A3 |
| **A5 数据规模上限** | 🟡 | DuckDB 单进程 ~200 GB 上限,Phase 4 eval 写明与真 LLM nightly scale 限制 |
| **A6 部署拓扑 vs 加字段混淆** | ✅ | 单 DuckDB `:memory:` + CSV/parquet 单一数据来源,无多源混淆 |
| **B1 LLM 行为防御 framework 强制** | ✅ | 决策 D2 算式链 DAG 反查 + CitationChecker framework 拦截 |
| **B2 mock LLM 测不变 mock** | ✅ | 决策 D3 双轨制 — mock PR-快回归 / 真 LLM nightly 验证 |
| **B3 决定方案≠已封死** | 🟡 | 关键开放问题 6/7 挂着待 Phase 1 写代码时 verify;真 LLM 行为 gap 量化待 nightly 首次跑出曲线 |
| **B4 prompt 软 vs framework 硬** | ✅ | 设计原则 1 + 决策 D1 显式 — prompt 软约束,sandbox framework 强制 |
| **C1 用法表 vs 框架拦截** | ✅ | 决策 D1 真边界(framework hook 拦截)非 prompt 软约束 |
| **C2 沙箱逃逸路径 ≥3 条** | ✅ | 决策 D1 列 7 条具体路径(merge / groupby.agg / pivot / query / apply / df.values / pandas.eval / numpy 文件路径) |
| **C3 跨 Phase 接口契约** | 🟡 | Phase 1 in-memory `execution_log` 接口定义 minimum schema;Phase 2 升级 SQLite 同 schema 兼容(显式声明);衍生字段 `derived_from_query_ids` 已在 D2 锁定 |
| **C4 并发与多 worker 模型** | n/a | panner 是单用户本机 / 进程级 in-memory,无多 worker 并发问题 |
| **D1 真背书引用核** | ✅ | 已逐条核实 + 修订(2026-07-13):RAGAS 论文准确(4 作者 / arXiv 2309.15217)+ ARES 准确(NAACL 2024 / 4 作者 / arXiv 2311.09476)+ smolagents 改 2025 年份+BibTeX 5 作者+关键 caveat「LocalPythonExecutor 非沙箱源点」官方自承+「dbt (Rittman 2024)」改「dbt Labs data tests,2026-07-09 last updated,docs.getdbt.com/docs/build/data-tests」+ DuckDB SIGMOD 2019 demo 准确(2 作者) |
| **D2 范畴分配** | ✅ | RAGAS faithfulness 迁移到 CodeAgent 答数字场景 — 与 panner citation 主战场同生态交集明确 |
| **D3 生造词 / 翻译错位** | ✅ | 修订阶段已修:"源典"换 "源点"(本 fork 文档本身已修) |
| **E1 ⚠️ 失败模式 5-7 条** | ✅ | 8 条 ⚠️(LLM 编数字 / dataframe-only / schema drift / AST 越界 / lazy 拒答 / truncate / INSTALL-ATTACH / pandas 绕 SQL) |
| **E2 工程层 vs 运营层失败模式分两段** | 🟡 | 偏工程层(沙箱越界 / 大 result / 派生数字);运营层(mock vs 真 LLM diff)放在 D3 不放独立成段 |
| **E3 已识别风险配真缓解** | ✅ | 每条 ⚠️ 配具体缓解(framework post-processor / execution_log schema cache / 双层 sandbox / 真 LLM nightly 验证) |
| **F1 mock LLM vs 真 LLM gap 量化** | ✅ | 决策 D3 — curve_diff.py 双线 diff nightly 报告 |
| **F2 corpus provenance 显式** | 🟡 | 决策 D3 — 真 corpus 待 Phase 4 PR 写具体 URL / 真数据集名(原则已锁) |
| **F3 tolerance 按 magnitude 分级** | 🟡 | 决策 D2 算式链反查 + Q4 (±0.01 + 字面) 已锁;但「百万级 vs 0.001」分级待 Phase 4 落实 |
| **F4 失败归因算法** | 🟡 | Phase 5 写「失败 case 分类意图 / SQL / 工具 / 推理」原则已锁,具体分类算法(rule-based 还是 LLM-judge)待 Phase 4 落实 |

**统计**: 12 条通用 checklist 中,panner 当前状态 = ✅ 13 项,🟡 8 项,n/a / 不适用 7 项(E2 模拟场景不适用 SSO / N-of-M)。Phase 1 PR 起手前🟡 可接受。

## 关键开放问题

### Phase 1 (citation) — 主战场,最关键

✅ 已决 5 条 + 🆕 新开放 2 条(均需 Phase 1 写代码时同时 verify):

1. **Citation token 抽取规则** ✅ **已决**: regex 抽数字 + 关键 categorical token(「是 / 不是」「唯 / 不唯」「顶 / 底」)+ spaCy fallback 处理复杂句式 — regex 覆盖 80% 简单 case,spaCy fallback 加准度,不极端二选一
2. **refusal 后 LLM 二次尝试** ✅ **已决**: framework 拒答后调 LLM 1 次 retry,把 `execution_log.sql` 全列 SQL 简短摘要写进 prompt(每条 SQL 文本 + stdout 关键数字截断);1 次 retry 后 framework 兜底拒答,不无限重试(避免 LLM 自我审查退化)
3. **Citation 对 dataframe-only 答案** ✅ **已决**: 强制 dataframe 操作走 DuckDB SQL 入 execution_log(`pandas.DataFrame.merge` / `groupby.agg` / `pivot` 在 `LocalPythonExecutor` 层运行前拒 + 在 prompt 强约束走 DuckDB SQL `JOIN` / `GROUP BY` / `PIVOT`)— 严守,后者准度低方案剔除
4. **numeric token 与 execution_log 匹配粒度** ✅ **已决**: **双口径** — (a) 数值型用 ±0.01 浮点误差匹配;(b) 字符串 / 日期型用字面相等(日期按 ISO 8601 标准化);混合答案类型按 token 类型分派两口径
5. **out-of-scope 答案标准定义** ✅ **已决**: 20 条 LLM-judge 自动 seed + 10 条人工边界 case review,共 30 条;Phase 4 `analytics_bench` 中 refusal_rate 子集跑这 30 条
6. **跨 row citation 对齐** 🆕 **新开放**: LLM 写「top 1 营收 A 店 1234 元,top 2 B 店 1100 元」,2 个数字 token 跟 SQL 输出 row 1:1 对应(按位置)?还是按数值最近邻?倾向按位置 1:1(LLM 顺序写→按 SQL 顺序 K=K 对齐),但 LLM 可能跳序 — 需 Phase 1 写代码时写测试 case 验
7. **多次 SQL 同数字歧义** 🆕 **新开放**: SQL 跑 2 次都出 `1234.56`,LLM 写 `1234.56`,该 `source_query_id` 是哪次?**倾向取最近一次 `query_id`**(按 `started_at` desc) — 但用户改 1 行重新跑数,旧数字被覆盖如何处理?需 Phase 1 实现 + 测试

### Phase 2 (execution log + result storage) — 支撑层

8. **`execution_log.db` 的 TTL 与并发写安全** — SQLite + atomic 写 (`tempfile + os.rename`),但多重 turn 累积写量是否清?默认 LRU 7 天 + 单会话上限 1000 条
9. **大结果的 5 行 preview 是 `head(5)` 还是 `sample(5)`** — head 看边界值易调试但不代表 distribution;sample 代表分布但 LLM 看不到空值 — 倾向 head(5) + 列 dtype 注释(让 LLM 推断 distribution)
10. **result parquet 文件清理** — 默认 7 天 LRU;用户分析师跨周回来真要重用某 hash?— 倾向加 `agent.pin_result("hash")` API 手动标不可清

### Phase 3 (schema memory) — 支撑层

11. **schema_hash 算法** — 只 hash 列名 + 列类型,还是包括约束(NOT NULL / INDEX)?只名+类型轻,但 `ALTER TABLE ADD COLUMN NOT NULL` 不被检测

## 第一刀

**Phase 1 起手** — `src/panner/citation.py` + `src/panner/execution_log.py` 并行落地。

理由:
- **citation 是 fork 主战场**,直接证明 fork 价值;result_storage / schema_memory 是支撑,先有主战场口径才能定它的支撑形态
- 主战场落地后,fork 立刻有可写进简历的「针对 LLM 编数字这一具体业务问题」的工程方案
- 改造点中等 — 新建 `CitationChecker` 类 + 修改 `CodeAgent.final_answer` 流程 + execution_log 最小 in-memory 版
- 测试容易写(纯单元 + mock LLM,不需要真 DuckDB cluster);Phase 1 落地不依赖 Phase 2 的 SQLite 持久化 — 起手最小版 in-memory `execution_log` 列表足够支援 CitationChecker 反查
- 不依赖 Phase 3 schema_memory / Phase 4 eval
- Phase 2 落 SQLite 持久化时,Phase 1 的 in-memory execution_log 升级 SQLite,接口不变 — 互哺关系而非阻塞关系

起手步骤(声明开发顺序,不动则止):
1. **走 2 个并行分支**(Phase 1 / Phase 2-min),可先 Phase 1 in-memory execution_log 跑通,Phase 2 再升持久化
2. 真 github 顺序:`feat/citation-checker` 先开 → 走代理测试 → `feat/execution-log-sqlite` 进 → 这俩 within 2 个 PR 内合并;`feat/schema-memory`、`feat/eval-bench` 后续

第一步 git 流程:
```bash
git checkout -b feat/citation-checker
# 新增 src/panner/citation.py + 最小 in-memory src/panner/execution_log.py + tests/test_citation_checker.py
# 修改 src/panner/agents.py 的 CodeAgent.final_answer 流程插入 CitationChecker
git add src/panner/citation.py src/panner/execution_log.py src/panner/agents.py tests/test_citation_checker.py
git commit -m "feat(citation): framework-grounded final_answer with source_query_id check"
git push -u origin feat/citation-checker
gh pr create --base main --head feat/citation-checker
```

第二步并行开:
```bash
git checkout -b feat/execution-log-sqlite main
# 升级 execution_log in-memory → SQLite 持久 + parquet 外存
git commit -m "feat(exec-log): persist execution_log to SQLite + large results to parquet"
gh pr create --base feat/citation-checker --head feat/execution-log-sqlite
# 注意 base 是 feat/citation-checker 不是 main,因为 citation 已是 PR 头状态
```

## 简历叙事锚点(本 fork 的"工程师式写法"素材)

| md 笔记的 ✅ 工程师式写法要素 | 在 panner 里的对应 |
|---|---|
| "针对什么业务问题" | "针对**会读 Python 的数据分析师** 用 CodeAgent 跑探索性数据分析时,**LLM 跑完 SQL 综合文字阶段编数字(SQL 没算的环比 / 增长被凭空补出)** 这一个具体业务问题" |
| "基于什么技术机制" | "基于 smolagents CodeAgent `LocalPythonExecutor` AST 沙箱 + `authorized_imports` 白名单 + DuckDB 嵌入式 SQL + framework post-processor `CitationChecker` 强制每 numeric token 反查 `execution_log.sql_output`" |
| "设计什么工程方案" | "**主战场**:framework 强制 citation 拒答(非 LLM 自我审查,防循环引用);**支撑**:(a) `execution_log` SQLite 持久 + parquet 大结果外存给 citation 反查载体;(b) DuckDB `schema_cache` 跨 turn 防 schema drift;(c) `analytics_bench` 联合度量 numeric_accuracy + citation_attachment_rate + refusal_rate 防 lazy 拒答退化" |
| "实现什么可验证效果" | "`analytics_bench` 20 条真 corpus 任务三类联合度量 — citation_attachment_rate ≥ 95% / refusal_rate ≥ 90% on out-of-scope /「3 个 SQL 没算的补数字」对抗 case 100% 拦;via in-memory DuckDB + mock LLM" |