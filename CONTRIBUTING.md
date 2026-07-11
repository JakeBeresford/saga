# Contributing

Thanks for your interest in Saga.

## Development setup

```sh
git clone https://github.com/JakeBeresford/saga
cd saga
uv pip install -e . pytest   # or: pip install -e . pytest
```

Run the tests:

```sh
python -m pytest
```

Lint, format, and type-check (install the dev tools with `uv sync --group dev`):

```sh
uv run ruff check .          # lint
uv run ruff format .         # auto-format
uv run ty check .            # type check
```

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
- Make sure `python -m pytest` passes and `ruff`/`ty` are clean before opening a
  PR. CI runs the suite on Python 3.11–3.13 plus a lint/format/type-check job.

## Reporting issues

Open an issue at https://github.com/JakeBeresford/saga/issues with steps to
reproduce, the command you ran, and what you expected to happen.
