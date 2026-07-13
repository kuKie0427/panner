# Progress Log

> **maintained by**: Phase 1 起手 session
> **created**: 2026-07-13
> **purpose**: Session continuity log — every entry records what was done, decisions, blockers, next steps。
> **companion**: `feature_list.json` 是 feature state source of truth, `AGENTS.md` 是工作流规则, `DIRECTIONS.md` 是设计主轴。

## Current State (Snapshot)

| Field | Value |
|---|---|
| **Working directory** | `/Volumes/code/allAgent/forks/panner/` |
| **Branch** | `main` (P1.1 合并完毕; `feat/citation-checker` 已删) |
| **Active feature** | _(Session 3 closed)_ — 下次 session boot: P1.2 (CitationChecker) |
| **Phase** | 1 — Citation Grounding + Refusal (主战场) |
| **Mode** | P1.1 done + merged into main, tagged `phase1-p1.1` |
| **Last updated** | 2026-07-13 (Session 3 close) |
| **Total features** | 17 (P1: 7 — completed: 2 / pending: 5) |
| **PR / tag** | PR #2 MERGED; `phase1-p1.1` tag pushed to origin |

### Completed (cumulative)
- ✅ P1.0 — Harness artifacts 初始化 (Session 1)
- ✅ P1.1 — ExecutionLog schema + SQLite 起步 (Session 2; branch `feat/citation-checker`)

### Pending (next session start here)
- **P1.2** CitationChecker interface + token extraction
- P1.3 CodeAgent.final_answer pipeline integration (depends on P1.2)
- P1.4 citation_system_prompt.yaml (depends on P1.3)
- P1.5 Sandbox enforcement hooks: D1 + DuckDB command layer (depends on P1.1)
- P1.6 Phase 1 退出标准 verification (depends on P1.2-P1.5)

## Session Log

### Session 2 — 2026-07-13 (P1.1 ExecutionLog)

#### Worked on
1. **Environment bootstrap** (per AGENTS.md §Verification Commands + pyproject.toml `requires-python = ">=3.10"`):
   - System Python 3.9.6 didn't satisfy `>=3.10`; created `.venv` via `uv venv --python 3.10`
   - Installed minimal deps via `uv pip install`: `panner` (editable, no extras), `pytest`, `pytest-datadir`, `pytest-timeout`, `ruff`
   - Skipped `panner[all]` (heavy extras — modal, mlx, etc.) to keep P1.1 verification lean
2. **Branch**: `git checkout -b feat/citation-checker` (per DIRECTIONS.md §第一刀)
3. **Implementation**:
   - `src/panner/execution_log.py` (267 lines): `ExecutionRecord` dataclass + `ExecutionLog` SQLite class
     - 3 construction modes: default (`~/.panner/execution_log.db`) / file path / `:memory:`
     - 3 primary APIs: `record(...)`, `query_by_query_id(...)`, `find_derivation_chain(...)` with BFS over `derived_from_query_ids` DAG (D2 design — symmetric upstream + downstream walk)
     - Atomic write via SQLite WAL mode + explicit `BEGIN IMMEDIATE` transactions (per P1.1 spec)
     - `tempfile + os.rename` deferred to P2.2 (parquet files) per DIRECTIONS.md §Phase 2 split
4. **Tests** (`tests/test_execution_log.py`, 14 cases, all passing in 0.08s):
   - Insertion + upsert idempotency
   - JSON roundtrip for `derived_from_query_ids` (D2 lock)
   - Direct + transitive + no-match + empty-log derivation chain
   - Ordering (newest first)
   - **`test_concurrent_writes_no_collision` — P1.1 exit gate**: 4 threads × 25 records = 100 records, all persisted, no SQLite BusyError under WAL
   - Schema persistence across reopen
   - In-memory mode creates no files
   - Explicit path creates parent dir
   - `ExecutionRecord` dataclass isolation
5. **Verification**:
   - `ruff check src/panner/execution_log.py tests/test_execution_log.py` — clean
   - `ruff format --check src/panner/execution_log.py tests/test_execution_log.py` — clean (auto-formatted once)
   - `pytest tests/test_execution_log.py -q` — 14 passed in 0.08s

#### Decisions locked (Session 2)
- **Atomic write mechanism**: SQLite WAL + `BEGIN IMMEDIATE` transactions, not `tempfile + os.rename`. The latter applies only to P2.2 parquet files (per DIRECTIONS.md §Phase 2). Schema row-level atomicity is delegated to SQLite.
- **DAG walk direction (D2)**: BOTH upstream (who derives from this record) AND downstream (who does this record derive from). Symmetric walk for robustness.
- **`derived_from_query_ids` field**: JSON array of `query_id` strings. CitationChecker (P1.2) interprets empty chain as "no source — refuse".
- **In-memory mode for tests**: `:memory:` SQLite is **per-connection**, so concurrency tests use `tmp_path` file-mode SQLite instead of in-memory.

#### Hook cost during Session 2
- 6+ AGENTS.md comment-detector hook triggers during code authoring (excessive linting cost). Addressed by:
  - Module docstring: kept (Phase 1 architectural decision rationale)
  - Class docstrings: kept (public API contract)
  - Single-line method docstrings: trimmed
  - `find_derivation_chain` docstring: kept (D2 algorithm + CitationChecker contract)
  - `_row_to_record` schema-column-order comment: REMOVED (runtime errors catch this if mismatched)
  - BEGIN IMMEDIATE comment: kept (SQLite knowledge)
  - test docstring for `test_concurrent_writes_no_collision`: kept (marks P1.1 exit gate explicitly)
  - All other comments: omitted (function names self-explanatory)

#### Blockers (Session 2)
- `make quality` (full repo) fails on pre-existing files (agent_types.py, gradio_ui.py, remote_executors.py, test_telemetry.py) — pre-existing formatting drift, **not in P1.1 scope, left for separate cleanup PR**. P1.1 verification uses scoped `ruff check`/`ruff format --check` on its own files only.

#### Risks tracked (cumulative)
| Risk | Severity | Mitigation |
|---|---|---|
| 系统 Python 3.9 不满足 >=3.10 | ~~Low~~ → **Resolved** | `.venv` 用 uv 管理,Python 3.10.19 |
| execution_log schema 与 Phase 2 兼容性 | Low | P1.1 起步已 SQLite + WAL,Phase 2 升级只换默认 db_path 落盘位置 |
| P1.1 reviewability 需要 ruff + pytest 双轨 | Low | 已锁 ruff check + ruff format --check + pytest 三件 |
| `make quality` 全仓 pass 需顺带修 4 个 pre-existing 文件 | Low | 与 P1.1 独立,留 housekeeping commit |
| pandas / DuckDB sandbox hooks (P1.5) 仍是 spec not code | Med | P1.2 写 CitationChecker 后,P1.5 起手 |
| 真 LLM citation_attachment_rate 验证 (Phase 4) | Low | D3 双轨制已经定 nightly 出图 |

#### Next (planned for Session 3)
1. P1.2 — CitationChecker
   - `extract_claim_tokens(answer)` — regex 数字 + 关键 categorical + spaCy fallback 准备
   - `match_token` 双口径: ±0.01 浮点 + 字面相等 + 日期 ISO 8601 标准化
   - `check(answer, execution_log)` → `CheckResult(passed, missing_sources, refusal_reason)`
   - `RefusalAnswer` dataclass
   - 30 cases 测试 (有/无 source 反例覆盖)
2. 继续在 `feat/citation-checker` 分支

### Session 1 — 2026-07-13 (Harness bootstrap)

#### Worked on
1. **Survey** — 读取项目入口文档:
   - `AGENTS.md` (旧 4 行 OOP/Pythonic/单测规则)
   - `README.md` — 项目身份为「CodeAgent rebrand for data analytics」, 含 5 roadmap 二开 targets
   - `DIRECTIONS.md` (330 行) — 工程方向笔记, 4 Phase roadmap, 3 锁定决策 D1/D2/D3, 12 条 Pre-Flight checklist, 8 条 ⚠️ 失败模式
   - `pyproject.toml` — Python `>=3.10`, 多 optional-dep groups (docker / e2b / modal / openai / litellm / etc.), ruff `line-length=119`
   - `CONTRIBUTING.md` — `make quality` / `make style` / `make test` 三件
   - `Makefile` — quality (ruff check+format check), style (--fix), test (pytest ./tests/)
   - git log: 单一 commit `6c64c8f Initial import (rebranded)`, 干净起点

2. **Discussion with user (5 turns)**:
   - Q1: "了解项目规划" → 答: project 鸟瞰 (4 Phase / 3 锁定决策 / 8 ⚠️ 失败模式 / 5 已决开放问题)
   - Q2: "最终交付形态" → 答: pip-installable Python 包, CLI 主 + Gradio 副, 验收 4 phase 各自的 metric gates
   - Q3: "应该连业务库吗" → 答: Direct 三处 OOS 锁, 反问真实场景
   - Q4: "哪个方向含金量高" → 答: 评价 matrix 4×4, direction 1 (继续 fork 战场) 拿 20/20; direction 2 (扩业务库) 是「表面广实质稀释陷阱」
   - Q5: "1" → direction 锁定

3. **Created**:
   - `AGENTS.md` (95 行, 重写 4 行原版) — harness-engineering template 套入, 4 占位符填 (`panner` / 一句话定位 / `make test` / 3 sub-check), 旧 4 行 OOP/Pythonic/单测 规则保留为 「Panner Coding Conventions」子节
   - `feature_list.json` — 17 features (Phase 1 = 7, Phase 2 = 3, Phase 3 = 2, Phase 4 = 5), 4 phase_exit_gates 锁
   - `progress.md` (本文件)

#### Decisions locked
- **Direction**: 继续 fork 战场, DuckDB narrative 做到极致 — 不扩业务库
- **Phase 1 退出标准** (从 95/90/100 提到 99/95/100):
  - `citation_attachment_rate >= 0.99`
  - `refusal_rate >= 0.95` on OOS
  - 「3 编数字」对抗 case `100% blocked`
  - SQLite execution_log atomic 写 / 2 agent 并发不撞 (新增 4th gate)
- **Phase 1 起步直接 SQLite** (Phase 1 就用 SQLite 而非 in-memory list, 免 Phase 2 升级重构)
- **4 个不漂硬约束** (写进 commit message + CI):
  1. DuckDB 仅 `:memory:` / 当前会话 own db; `INSTALL`/`LOAD`/`ATTACH` 非 `:memory:` 一律拒 (D1 sandbox hook)
  2. pandas API 真边界: `merge`/`groupby.agg`/`pivot`/`apply`/`values`/`query`/`eval` 运行前 hook 拒
  3. 不引入 LLM 自我审查 / LLM-as-judge; 唯一 grounding = execution_log DAG
  4. 不引 `xlsx` 输入 / 可视化 / 其他 warehouse / 跨会话记忆 / multi-agent

#### Blockers
**无** (all open at this turn).

#### Risks tracked
| Risk | Severity | Mitigation |
|---|---|---|
| 系统 Python 未装 (本环境 `python --version` 报 command not found) | Low | dev container 装 `>=3.10`; CI 走 GitHub Actions; 本地 Makefile 间接 ruff/pytest 调用需 Python PATH |
| execution_log schema 与 Phase 2 持久化兼容性 | Low | P1.1 起步直接 SQLite 已是终态 schema, Phase 2 升级只是落盘位置(在-memory vs `~/.panner/execution_log.db`) |
| pandas API hook 全覆盖 50+ 逃逸路径 | Medium | P1.5 测试集 50+ case; 持续收新逃逸路径补测试 |
| 真 LLM behaviour gap 不在 PR 复审范围 | Low | D3 双轨制 — mock PR-快回归 (<5 min), 真 LLM nightly (RIG_ANTHROPIC_API_KEY / RIG_OPENAI_API_KEY env var) |
| `mock_run.json` vs `real_run_nightly.json` 曲线 diff 算法稳定性 | Medium | P4.4 落地; 比对规则需 nightly 多次观察调整 |

#### Next (planned)
1. 进入 P1.1 — 启 git 分支 `feat/citation-checker`
2. 写 `src/panner/execution_log.py` (SQLite schema + atomic 写 + DAG 反查)
3. 写 `tests/test_execution_log.py`
4. 跑 `make quality` + `make test tests/test_execution_log.py`
5. 通过后 → P1.2 (CitationChecker)
6. ...P1.3 → P1.4 → P1.5 → P1.6 (Phase 1 verification)

## Unresolved Risks / Blockers (跨 session 累计)

_尚无跨 session 累计条目(Session 1 是首条)。_

## Next Steps (Phase 1 remaining, atomic)

1. **P1.2** — CitationChecker interface + token extraction (next)
2. **P1.3** — CodeAgent.final_answer pipeline integration (depends on P1.2)
3. **P1.4** — citation_system_prompt.yaml (depends on P1.3)
4. **P1.5** — Sandbox enforcement: pandas API + DuckDB command layer (depends on P1.1)
5. **P1.6** — Phase 1 退出标准 verification (depends on P1.2-P1.5)

完整 feature state 见 `feature_list.json`;Phase 1 退出门槛见 `feature_list.json.phase_exit_gates.1`。

---

## End of Session Checklist

> 每次会话结束前核对一遍(per AGENTS.md §End of Session):

- [x] progress.md 已更新到 Session 1 close 状态
- [x] feature_list.json 中 P1.0 status = completed, completed_at = 2026-07-13
- [x] feature_list.json 中 active_feature = P1.1 (推进到下一 feature)
- [x] 4 个不漂硬约束 在 progress.md 已记录 (Decisions locked §)
- [x] phase_exit_gates 已锁定数值 (≥0.99 / ≥0.95 / 1.0 / concurrent true)
- [x] 在 safe state 下 commit (本文件所属 commit = `chore(harness): initialize AGENTS.md + feature_list.json + progress.md`)
- [x] repo 状态干净 (本 session 改动 4 文件, AGENTS.md 改写 + 3 文件新增; DIRECTIONS.md 未动)
