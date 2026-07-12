# panner

CodeAgent rebranded for data analytics. The LLM produces **Python code** (not tool-call JSON) to invoke tools, execute SQL, transform dataframes, and combine multi-step explorations — coherent state persists across steps via the executor's namespace.

Designed for natural-language-to-data workflows where the agent explores a warehouse iteratively (`describe` → `group by` → `join` → `plot`) without losing intermediate state.

## Design priorities

1. **Think in code, not tool JSON.** CodeAgent produces Python source each step. A 5-step exploration is one coherent program with shared variables — not five disconnected OpenAI-style tool calls whose outputs must be threaded back manually.
2. **AST-walked sandbox, not `exec()`.** `LocalPythonExecutor` parses code as AST and evaluates nodes individually with module/dangerous-function whitelists. No `os`, `subprocess`, `socket`, `shutil` by default. Add `pandas` / `sqlalchemy` / `duckdb` via explicit `authorized_imports`.
3. **Real isolation is one switch.** When dealing with untrusted queries, swap `LocalPythonExecutor` for `DockerExecutor` / `E2BExecutor` / `ModalExecutor` — Jupyter kernel gateway behind a container boundary.
4. **State persists across steps.** The executor's `self.state` dict holds DataFrame variables, schema dicts, and connection objects so multi-turn exploration doesn't re-run prior queries.

## Install (dev)

```bash
pip install -e ".[dev]"
# or via uv:
# uv pip install -e "panner[dev] @ ."
```

## Quickstart

```python
from panner import CodeAgent, InferenceClientModel
from panner.tools import LoadImageTool

agent = CodeAgent(
    model=InferenceClientModel(model_id="Qwen/Qwen2.5-Coder-32B-Instruct"),
    tools=[LoadImageTool()],
    authorized_imports=["pandas", "sqlalchemy"],
)
agent.run("Load `sales.csv`, give me top-5 stores by revenue, plot a bar chart.")
```

## Key directories

| Path | Purpose |
|---|---|
| `src/panner/agents.py` | `CodeAgent` and `ToolCallingAgent` loops |
| `src/panner/local_python_executor.py` | AST sandbox + `authorized_imports` |
| `src/panner/remote_executors.py` | Docker / E2B / Modal executors |
| `src/panner/tools.py` | `Tool` definition + `ToolCollection` |
| `src/panner/default_tools.py` | Built-in tools (web search, visit webpage, ...) |
| `src/panner/memory.py` | Agent memory primitives |
| `src/panner/utils.py` | `truncate_content` — large-output handling (**needs upgrade to result-file storage**) |
| `examples/` | Reference notebooks: text-to-SQL, RAG, sandboxed execution, multi-agent |

## Roadmap 二开 targets

- [ ] **Result storage layer**: replace `truncate_content`'s 20K-char hard cutoff with a tool-result-storage pattern that serializes oversized DataFrames to `~/.panner/<hash>.parquet` and keeps a 5-row preview + path in LLM context.
- [ ] **Schema memory**: blob the warehouse `information_schema` into agent state on first turn; refresh on demand.
- [ ] **Citation grounding**: extend the answer finalization step to require source-row references; configure refusal-when-no-grounding.
- [ ] **Sensitive-column redaction**: SQLAlchemy event hook to mask PII columns before the result reaches LLM context.
- [ ] **Eval suite**: three test groups — (a) numeric accuracy vs ground-truth SQL; (b) citation-attachment correctness; (c) refusal rate on out-of-scope queries.

## License

Apache-2.0. See [LICENSE](LICENSE).