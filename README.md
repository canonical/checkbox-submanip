# oem-qa-submanip
A continuation of the submanip program on launchpad. It's meant to be a graphical editor of checkbox submissions. Edited submissions SHOULD NOT be submitted to C3.

# Development

Most of the dependencies are managed by `uv`. When creating a new virtual env, run the following:

```sh
uv venv -p /usr/bin/python3 --system-site-packages
```

because we need access to the system's `python3-checkbox-ng` package. Then 

```sh
# use activate.fish if on fish shell
source .venv/bin/activate
uv sync --active --python /usr/bin/python3
```
When updating dependencies, do:

```sh
uv sync --active -U --python /usr/bin/python3
```