# Contributing

Thanks for your interest in Saga.

## Development setup

```sh
git clone https://github.com/JakeBeresford/saga
cd saga
uv sync --group dev   # install the package plus the dev/test tools
```

Validate your changes with the same checks CI runs:

```sh
scripts/check.sh   # lint + type-check + test — the full gate
scripts/lint.sh    # ruff check, ruff format --check, and ty type-check
scripts/test.sh    # pytest
```

`scripts/check.sh` is the gate to run before opening a PR. Auto-fix formatting
with `uv run ruff format .`, and run a single test with
`uv run pytest tests/test_model.py::test_name`.

To try the CLI against a real repo while developing, install it as an editable
tool and run it from inside any git checkout:

```sh
uv tool install --editable .
saga --base main --head my-feature
```

## Pull requests

- Keep changes focused and match the existing style.
- Add or update tests for any behavior change — the core model logic in
  `saga/model.py` is unit-tested in `tests/test_model.py`.
- Make sure `scripts/check.sh` passes before opening a PR. CI runs the same
  checks: the test suite on Python 3.11–3.13 plus a lint/format/type-check job.

## Reporting issues

Open an issue at https://github.com/JakeBeresford/saga/issues with steps to
reproduce, the command you ran, and what you expected to happen.
