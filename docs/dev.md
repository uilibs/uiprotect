---
hide:
  - navigation
---

# Development

## Setup

### With VS Code

Development with this project is designed to be done via VS Code + Docker. It is a pretty standard Python package, so feel free to use anything else, but all documentation assumes you are using VS Code.

- [VS Code](https://code.visualstudio.com/) + [Remote Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
- [Docker](https://docs.docker.com/get-docker/)
  - If you are using Linux, you need Docker Engine 19.0 or newer and you need to enable [Docker Buildkit](https://docs.docker.com/develop/develop-images/build_enhancements/)
  - If you are using Docker Desktop on MacOS or Windows, you will need Docker Desktop 3.2.0 or newer

Once you have all three setup,

1. Clone repo
2. Open the main folder
3. You should be prompted to "Reopen folder to develop in a container". If you are not, you can open the [Command Palette](https://code.visualstudio.com/docs/getstarted/userinterface#_command-palette) run the "Remote-Containers: Reopen in Container" command.

This should be all you need to do to get a working development environment. The docker container will automatically be build and VS Code will attach itself to it. The integrated terminal in VS Code will already be set up with the `uiprotect` command.

### Docker (without VS Code)

You can still setup develop without VS Code, but it is still recommended to use the development container to ensure you have all of the required dependencies. As a result, the above requirement for Docker is still needed.

Once you have Docker setup,

1. Clone repo
2. Build and open dev container

   ```bash
   docker buildx build -f Dockerfile --target=dev -t uiprotect-dev .
   docker run --rm -it -v "$(pwd)":/workspaces/uiprotect uiprotect-dev bash
   ```

## Authenticating with your Local Protect Instance

The project allows you to create an environment file to put your local protect instance data into so you do not need to constantly enter in or accidentally commit it to the Git repo.

Make a file in the root of the project named `.env` with the following and change accordingly:

```
UFP_USERNAME=YOUR_USERNAME_HERE
UFP_PASSWORD=YOUR_PASSWORD_HERE
UFP_ADDRESS=YOUR_IP_ADDRESS
UFP_PORT=443
# set to true if you have a valid HTTPS certificate for your instance
UFP_SSL_VERIFY=false
```

## Linting and Testing

The following scripts exist to easily format, lint and test code in the same fashion as CI:

```
pre-commit run --all-files
.bin/test-code
```

These commands are also all available as [VS Code tasks](https://code.visualstudio.com/Docs/editor/tasks) as well. Tests are also fully integration with the Testing panel in VS Code and can be easily debug from there.

If you are not using the dev container, the same checks run under Poetry:

```bash
poetry install --all-extras
poetry run pre-commit run --all-files
poetry run pytest
```

## Updating Requirements

To regenerate the pinned release cache used for testing and CI, run the
`.bin/update-release-cache` script.

There is also a [VS Code task](https://code.visualstudio.com/Docs/editor/tasks) to run this as well.

## Generating Test Data

All of the tests in the project are ran against that is generated from a real UniFi Protect instance and then anonymized so it is safe to commit to a Git repo. To generate new sample test data:

```
uiprotect generate-sample-data
```

This will gather test data for 30 seconds and write it all into the `tests/sample_data` directory. During this time, it is a good idea to generate some good events that can tested. An example would be to generate a motion event for a FloodLight, Camera and/or Doorbell and then also ring a Doorbell.

- All of the data that is generated is automatically anonymized so nothing sensitive about your NVR is exposed. To skip anonymization, use the `--actual` option.
- To change output directory for sample data use the `-o / --output` option.
- To adjust the time adjust how long to wait for Websocket messages, use the `-w / --wait` option.
- To automatically zip up the generated sample data, use the `--zip` option.

```bash
export UFP_SAMPLE_DIR=/workspaces/uiprotect/test-data
uiprotect generate-sample-data
```

### Real Data in Tests

`pytest` will automatically also use the `UFP_SAMPLE_DIR` environment variable to locate sample data for running tests. This allows you to run `pytest` against a real NVR instance.

```bash
export UFP_SAMPLE_DIR=/workspaces/uiprotect/test-data
pytest
```

## Adding a public API endpoint

The uniform slice of the Public Integration API surface on `ProtectApiClient` is declared with decorators from `uiprotect._public_api`. You keep the hand-written `async def` signature and one-line docstring (mypy-strict and the rendered API reference depend on them); the decorator supplies the body — path binding, payload assembly, dispatch through the existing `api_request_*` helpers, and model construction. The body is a stub (`raise NotImplementedError`, which is never reached because the decorator replaces it).

There are three forms:

```python
from ._public_api import public_get, public_patch, public_post

# List GET — one model per array entry (items=, plural)
@public_get("/v1/cameras", items=PublicCamera)
async def get_cameras_public(self) -> list[PublicCamera]:
    """Get all cameras using public API."""
    raise NotImplementedError

# Object GET — a single model (item=, singular); placeholders bind from same-named params
@public_get("/v1/cameras/{camera_id}", item=PublicCamera)
async def get_camera_public(self, camera_id: str) -> PublicCamera:
    """Get a specific camera using public API."""
    raise NotImplementedError

# Flat PATCH — body is the non-None keyword params, snake_case → camelCase
@public_patch("/v1/fobs/{fob_id}", item=Fob)
async def update_fob_public(self, fob_id: str, *, name: str | None = None) -> Fob:
    """Patch key-fob settings using public API."""
    raise NotImplementedError

# Fire-and-forget POST — path-only, no body, no return value
@public_post("/v1/sirens/{siren_id}/stop")
async def stop_siren_public(self, siren_id: str) -> None:
    """Stop an active siren."""
    raise NotImplementedError
```

`item=` always means a single model, `items=` a list; `public_get` takes exactly one of them (XOR), while `public_patch` returns one `item=` and `public_post` takes neither. Each decorator registers its `(verb, path)` against the class at import time; declaring the same `(verb, path)` twice raises immediately. The signature is validated at decoration too — every `{placeholder}` must name a real parameter, and a body-less `public_get`/`public_post` may not carry any non-placeholder parameter — so a declaration that lies fails the import, not a later call. The model class is passed as an argument (`item=`/`items=`), so `_public_api.py` imports nothing from `uiprotect.data` and stays circular-import-safe.

**The PATCH form is flat-body only.** A `@public_patch` body is built mechanically: every non-`None` keyword parameter becomes one camelCase wire key, and an empty body raises `BadRequest("At least one parameter must be provided")`. Path placeholders never leak into the body. This rule is correct only for genuinely uniform methods — anything that groups keys into nested objects (`ledSettings`/`osdSettings`), renames non-mechanically, validates ranges, carries a nullable `_UNSET` sentinel, or writes through to the public bootstrap cache (e.g. `update_camera_public`, `update_light_public`, `update_viewer_public`) stays hand-written. When in doubt, keep the body hand-written — behavior parity beats terseness. The hand-written exceptions are covered by their recorded example calls.
