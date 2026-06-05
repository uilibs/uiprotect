# Installation

The package is published on [PyPI](https://pypi.org/project/uiprotect/) and can be installed with `pip` (or any equivalent):

```bash
pip install uiprotect
```

To use the command-line interface (the `uiprotect` console script), install
the `cli` extra, which pulls in [`typer`](https://typer.tiangolo.com/):

```bash
pip install "uiprotect[cli]"
```

`uiprotect` supports **Python 3.11+**.

Next, see the [usage](usage.md) page to see how to use it. If you plan to talk
to the documented [Public Integration API](usage.md#public-vs-private-api)
(API-key authentication), the usage page covers when to prefer it over the
private API.
