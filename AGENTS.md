# panner

面向数据分析师 / analytics engineer 会读 Python 的用户的 CodeAgent,跑在 DuckDB 嵌入式数据上。LLM 产 Python 代码(而非 tool-call JSON)以执行 SQL / dataframe 操作;**framework 强制每行答案附 `source_query_id`,无 grounding 一律拒答——不让 LLM 编数字**。

详细工程方向与设计决策见 [`DIRECTIONS.md`](./DIRECTIONS.md)(本 fork 主战场、4 Phase roadmap、3 个已锁设计决策、12 条 Pre-Flight checklist 均在其中)。

## Startup Workflow

Before writing code:

1. **Confirm working directory** with `pwd` — 必须落在 `allAgent/forks/panner/`,不是 `allAgent/` 根、不是 `src/panner/`。
2. **Read this file** completely。
3. **Read project docs if present** — `docs/ARCHITECTURE.md`、`docs/PRODUCT.md`、README、**`DIRECTIONS.md`(本 fork 必读)** 或等价文档。本项目目前 `docs/` 目录不存在,以 `DIRECTIONS.md` + `README.md` 为主入口。
4. **Read `feature_list.json`** to see current feature state。
5. **Review recent commits** with `git log --oneline -5`。

If baseline verification is failing, repair that first before adding new scope。

> 当前 `feature_list.json` 含 **17 个 feature**(P1: 7 / P2: 3 / P3: 2 / P4: 5),Phase 1 子任务粒度最细,P2-P4 较粗。active_feature 字段指向当前在做。

## Working Rules

- **One feature at a time**: Pick exactly one unfinished feature from `feature_list.json`。
- **Verification required**: Don't claim done without running verification commands。
- **Update artifacts**: Before ending session, update `progress.md` and `feature_list.json`。
- **Stay in scope**: Don't modify files unrelated to the current feature。
- **Read DIRECTIONS.md before claiming anything contradicts fork policy** — 本 fork 的主战场边界、Non-goals、4 Phase scope 均以 `DIRECTIONS.md` 为准。

## Required Artifacts

- `feature_list.json` — Feature state tracker(source of truth)。
- `progress.md` — Session continuity log。
- `session-handoff.md` — Optional, for larger sessions。

> 注:本仓库当前尚未生成上述产物文件。Phase 1 起手 commit 应同时初始化 `feature_list.json` 与 `progress.md` 框架,使后续 session 可走 harness workflow。

## Definition of Done

A feature is done only when ALL of the following are true:

- [ ] Target behavior is implemented。
- [ ] Required verification actually ran(tests / lint / type-check)。
- [ ] Evidence recorded in `feature_list.json` or `progress.md`。
- [ ] Repository remains restartable from standard startup path。

## End of Session

Before ending a session:

1. Update `progress.md` with current state。
2. Update `feature_list.json` with new feature status。
3. Record any unresolved risks or blockers。
4. Commit with descriptive message once work is in safe state。
5. Leave repo clean enough。

## Verification Commands

```bash
# Full verification (recommended)
make test
```

Required checks:

- `make quality` — ruff lint + ruff format check,覆盖 `src/` `tests/` `examples/`。
- `make style` — ruff 自动 format(含 `--fix`),提交前跑一次。
- `make test` — `pytest ./tests/`,含 sandbox / citation / refusal 三类 case。

环境前置:Python `>=3.10`(`pyproject.toml` 声明);开发依赖走 `pip install -e ".[dev]"` 或 `uv pip install -e "panner[dev] @ ."`。

## Escalation

If you encounter:

- **Architecture decisions**: Consult project architecture docs if present(`DIRECTIONS.md` 充当本 fork 的 architecture 主轴),otherwise ask user。
- **Unclear requirements**: Check product/requirements docs if present,otherwise ask user。
- **Repeated test failures**: Update progress, flag for human review。
- **Scope ambiguity**: Re-read `feature_list.json` for definition of done;若与 `DIRECTIONS.md` Non-goals 冲突,**引用 DIRECTIONS.md 的对应章节**,而非重新打开边界讨论。

---

## Panner Coding Conventions (preserved from prior AGENTS.md)

贡献 / 提 PR 时遵守:

- **Follow OOP principles** — 类 / 方法设计保持清晰职责与封装;避免函数式 / 过程式大杂烩堆在一个文件里。
- **Be Pythonic** — 用 type hints / dataclasses / context managers;命名遵守 PEP 8;避免 `from foo import *`。`pyproject.toml` 已配 ruff(`line-length=119`、`E/F/I/W` 选择集)。
- **Write unit tests for new functionality** — 每个新文件 / 新公共方法对应一份 `tests/test_*.py`;**先用 mock LLM 跑通再接真 LLM**(D3 双轨制:mock PR-快回归,真 LLM nightly)。

> 若本文档工作流规则与 `DIRECTIONS.md` 设计原则冲突,**以 `DIRECTIONS.md` 为准**——`DIRECTIONS.md` 是 fork 工程方向主轴,本文档是工作流护栏。

## Scope Boundaries (摘自 DIRECTIONS.md,工作流常引)

- ✅ 允许:DuckDB 嵌入式 / `authorized_imports` 白名单 / sandbox hook / framework-level citation enforcement / mock LLM PR 回归。
- ❌ OOS:multi-agent / multi-warehouse / 可视化 / PII 治理 / 跨会话 alias / 实时流 / `xlsx` 输入 / LLM-as-judge 当唯一 grounding。

完整 Non-goals 与 8 条 ⚠️ 失败模式 + 缓解矩阵,见 `DIRECTIONS.md`。
