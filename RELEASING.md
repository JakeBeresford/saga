# Releasing

Releases are published to PyPI **manually, by the sole maintainer**. There is
no CI publish workflow by design — nothing but a local machine holding the
maintainer's token can push a release.

## One-time setup

1. On [PyPI](https://pypi.org): create the account, enable **2FA**, and remain
   the **sole Owner** of `saga-cli`. Do not add other Owners or Maintainers.
2. For the **first** upload the project does not exist yet, so create an
   **account-scoped** API token, publish once (below), then immediately create a
   **project-scoped** token for `saga-cli` and delete the account-scoped one.
3. Store the token locally only — e.g. `~/.pypirc`, or export it per release:
   ```sh
   export UV_PUBLISH_TOKEN=pypi-…
   ```

## Cutting a release

```sh
# 1. Bump the version in pyproject.toml, commit, and tag
git tag v0.1.0 && git push origin main --tags

# 2. Build clean and publish
rm -rf dist
uv build
uv publish            # uses UV_PUBLISH_TOKEN, or ~/.pypirc

# 3. Cut a matching GitHub Release for the tag (changelog / notes)
```

Verify the upload with `pip index versions saga-cli` or by visiting the PyPI
project page.
