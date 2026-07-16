# Releasing

Releases are published to PyPI **manually, by the sole maintainer**. There is
no CI publish workflow by design. Nothing but a local machine holding the maintainer's token can push a release.

## Cutting a release

```sh
# 1. Bump the version in pyproject.toml, commit, and tag
git tag v0.1.0 && git push origin main --tags

# 2. Build clean and publish
rm -rf dist
uv build
uv publish # uses UV_PUBLISH_TOKEN, or ~/.pypirc

# 3. Cut a matching GitHub Release for the tag (changelog / notes)
```

Verify the upload with `pip index versions saga-cli` or by visiting the PyPI project page.
