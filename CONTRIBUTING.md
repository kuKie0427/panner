# Contributing

## Dev install

```bash
pip install -e ".[dev]"
# or via uv:
# uv pip install -e "panner[dev] @ ."
```

## Quality and tests

```bash
make quality    # ruff lint
make style      # ruff format
make test       # pytest suite
```

## Pull requests

- Open a PR with a clear description of motivation and approach.
- Keep changes scoped. Split large refactors into multiple PRs.
- Add or update tests for any new behavior you introduce.
