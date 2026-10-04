---
hide:
  - navigation
---

# Command Line

The `uiprotect` command is provided to give a CLI interface to interact with your UniFi Protect instance as well. All
commands support JSON output so it works great with `jq` for complex scripting.

## Authentication

Following traditional [twelve factor app design](https://12factor.net/), the preferred way to provided authentication
credentials to provided environment variables, but CLI args are also supported.

!!! warning "About Ubiquiti SSO accounts"
Ubiquiti SSO accounts are not supported and actively discouraged from being used. There is no option to use MFA. You are expected to use local access user. `uiprotect` is not designed to allow you to use your owner account to access the your console or to be used over the public Internet as both pose a security risk.

### Environment Variables

```bash
export UFP_USERNAME=YOUR_USERNAME_HERE
export UFP_PASSWORD=YOUR_PASSWORD_HERE
export UFP_ADDRESS=YOUR_IP_ADDRESS
export UFP_PORT=443
# optional: set to false if you have a self-signed certificate
# export UFP_SSL_VERIFY=false

uiprotect nvr
```

### CLI Args

```bash
uiprotect -U YOUR_USERNAME_HERE -P YOUR_PASSWORD_HERE -a YOUR_IP_ADDRESS -p 443 --no-verify-ssl nvr
```

### Public-only mode

The credentials you supply decide which API the CLI talks to. An API key with
no username or password runs every command against Ubiquiti's
[Public Integration API](usage.md#public-vs-private-api): there is no private
login, no private bootstrap, and no password prompt. Device groups fetch only
the devices they need from the public API; a failed fetch (wrong host,
untrusted certificate, bad key) exits with the error instead of printing an
empty list.

```bash
export UFP_API_KEY=YOUR_API_KEY_HERE
export UFP_ADDRESS=YOUR_IP_ADDRESS

uiprotect cameras list-ids
```

Commands that have no public equivalent exit with an error telling you to
supply `--username`/`--password`. In this mode that covers:

- whole groups: `nvr`;
- top-level commands: `create-api-key`, `generate-sample-data`, `profile-ws`,
  `shell`;
- on every device group: `adopt`, `bridge`, `reboot`, `set-ssh`, `unadopt`,
  `update`, and `set-name` with no argument (clearing a name);
- `cameras`: `chime-type`, `play-audio`, `privacy-mode`, `save-snapshot`
  without `--package`, `save-video`, `set-camera-zoom`,
  `set-color-night-vision`, `set-ir-led-mode`, `set-motion-detection`,
  `set-person-track`, `set-recording-mode`, `set-ring-volume`,
  `set-speaker-volume`, `set-system-sounds`, `set-volume`, `set-wdr-level`,
  `smart-audio-detects`, `smart-detects`;
- `chimes`: `play`, `play-buzzer`, and `set-volume` / `set-repeat-times`
  without `--camera`;
- `lights`: `camera`;
- `sensors`: `camera`, `is-alarm-detected`, `set-mount-type`,
  `set-status-light`.

Everything else — `list-ids`, showing a device, `set-name NAME`, and the
remaining group commands (including `chimes cameras` and the camera RTSPS
stream commands) — works with the API key alone.

With no API key, or with a username or password but not both, the CLI runs in
hybrid mode and asks for the missing credential only when a command needs the
private API. It prompts only on an interactive terminal; a non-interactive run
exits with an error instead. For a device group (`cameras`, `chimes`, `lights`,
`sensors`, `viewers`) given an API key, it also points out that dropping the
username/password runs the group on the key alone. Public-API commands never
prompt: without an API key they fail with an "API key is required" error.

In hybrid mode, the device commands that also work on the API key alone
(`set-name NAME`, the public setters, the sensor reads other than
`is-alarm-detected` and `is-alarm-enabled`, `chimes set-volume` and
`set-repeat-times` with `--camera`) fetch the device from the public API and
act on it there, as in public-only mode, so they need an API key.
`cameras save-snapshot --package` reads the camera from the private bootstrap
but requests the snapshot from the public API, so it needs an API key too.

## Timezones

A number of commands allow you to enter a datetime as an argument or output files with the datetime in the filename. As a result, it is very important for `uiprotect` to know your consoles local timezone. If you on a physical machine (not docker/VM), chances are this is already set up correctly for you (`/etc/localtime`), but otherwise you may need to set the `TZ` environment variable. `TZ` can also be used to override your system timezone as well if for whatever reason you need to. It should be the [Olson timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) for the timezone that your UniFi Protect Instance is in.

```bash
TZ=America/New_York uiprotect --help
```

## Reference

```bash
$ uiprotect --help
Usage: uiprotect [OPTIONS] COMMAND [ARGS]...

UniFi Protect CLI
```

### Options

|      | Option                         | Required?          | Env            | Type           | Default | Description                                                                                                               |
| ---- | ------------------------------ | ------------------ | -------------- | -------------- | ------- | ------------------------------------------------------------------------------------------------------------------------- |
| `-U` | `--username`                   |                    | `UFP_USERNAME` | text           |         | UniFi Protect username. Prompted for when a command needs the private API.                                                |
| `-P` | `--password`                   |                    | `UFP_PASSWORD` | text           |         | UniFi Protect password. Prompted for when a command needs the private API.                                                |
| `-k` | `--api-key`                    |                    | `UFP_API_KEY`  | text           |         | UniFi Protect API key. On its own (no username/password) it runs the CLI in [public-only mode](#public-only-mode).        |
| `-a` | `--address`                    | :white_check_mark: | `UFP_ADDRESS`  | text           |         | UniFi Protect IP address or hostname                                                                                      |
| `-p` | `--port`                       |                    | `UFP_PORT`     | integer        | `443`   | UniFi Protect port                                                                                                        |
|      | `--verify-ssl/--no-verify-ssl` |                    |                | boolean        | `True`  | Verify SSL certificate. Use `--no-verify-ssl` for self-signed certificates. Will prompt to disable if verification fails. |
|      | `--output-format`              |                    |                | `json`,`plain` | `plain` | Preferred output format. Not all commands support both JSON and plain and may still output in one or the other.           |
| `-u` | `--include-unadopted`          |                    |                |                |         | Include devices not adopted by this NVR.                                                                                  |
|      | `--show-completion`            |                    |                |                |         | Show completion for the current shell, to copy it or customize the installation.                                          |
|      | `--help`                       |                    |                |                |         | Show help message and exit.                                                                                               |

### Subcommands

For any subcommand you can use `uiprotect COMMAND --help`

Commands are split between the reverse-engineered **private** API
(username/password auth) and Ubiquiti's documented **Public Integration API**
(API-key auth — see [Public vs. private API](usage.md#public-vs-private-api)).
The API column marks which is which.

`Hybrid` groups issue most of their writes through the Public Integration API.
With username/password they select the device from the private bootstrap and
expose their full command set; with [an API key alone](#public-only-mode) they
fetch only the device kinds a command needs from the Public Integration API and
expose only the commands that have a public equivalent. `Private` groups are unavailable in public-only mode.

| Command                | API     | Description                                                      |
| ---------------------- | ------- | ---------------------------------------------------------------- |
| `arm`                  | Public  | Arm profile and alarm commands.                                  |
| `bridges`              | Public  | Bridge commands.                                                 |
| `cameras`              | Hybrid  | Camera device CLI.                                               |
| `chimes`               | Hybrid  | Chime device CLI.                                                |
| `create-api-key`       | Private | Create a new API key for the current user.                       |
| `decode-ws-msg`        | —       | Decodes a base64 encoded UniFi Protect Websocket binary message. |
| `files-public`         | Public  | Device asset file commands.                                      |
| `fobs`                 | Public  | Key fob commands.                                                |
| `generate-sample-data` | Private | Generates sample data for UniFi Protect instance.                |
| `get-meta-info`        | Public  | Get metadata about the current UniFi Protect instance.           |
| `lights`               | Hybrid  | Lights device CLI.                                               |
| `link-stations`        | Public  | Link station and alarm hub commands.                             |
| `liveviews`            | Public  | Liveview commands.                                               |
| `nvr`                  | Private | NVR device CLI.                                                  |
| `profile-ws`           | Private | Profiles Websocket messages for UniFi Protect instance.          |
| `relays`               | Public  | Relay commands.                                                  |
| `sensors`              | Hybrid  | Sensors device CLI.                                              |
| `shell`                | Private | Opens iPython shell with Protect client initialized.             |
| `sirens`               | Public  | Siren commands.                                                  |
| `speakers`             | Public  | Speaker commands.                                                |
| `ulp-users-public`     | Public  | UniFi Identity (ULP) user commands.                              |
| `users-public`         | Public  | Protect user commands.                                           |
| `viewers`              | Hybrid  | Viewers device CLI.                                              |

#### Multiple Item CLI Commands

All adoptable device CLIs work on the idea you have multiple cameras or multiple lights. As such, they have four variations:

```bash
# list all devices
uiprotect cameras

# list short list of all devices
uiprotect cameras list-ids

# list a specific device
uiprotect cameras DEVICE_ID

# run a command against a specific device
uiprotect cameras DEVICE_ID COMMAND
```

!!! note
The "list all devices" and "list a specific device" commands always return raw JSON. These commands can be paired with [jq](https://stedolan.github.io/jq/) to parse and quick extra device data from them.

| Command            | Description                                                              |
| ------------------ | ------------------------------------------------------------------------ |
| `list-ids`         | Requires no device ID. Prints list of "id name" for each device.         |
| `set-person-track` | Requires device ID. Sets person auto tracking on or off for PTZ cameras. |

##### Examples

###### List All Cameras

=== "Plain"

    ```bash
    $ uiprotect cameras list-ids

    61b3f5c7033ea703e7000424: G4 Bullet
    61f9824e004adc03e700132c: G4 PTZ
    61be1d2f004bda03e700ab12: G4 Dome
    ```

=== "JSON"

    ```bash
    $ uiprotect --output-format json cameras list-ids

    [
      [
        "61b3f5c7033ea703e7000424",
        "G4 Bullet"
      ],
      [
        "61f9824e004adc03e700132c",
        "G4 PTZ"
      ],
      [
        "61be1d2f004bda03e700ab12",
        "G4 Dome"
      ],
      ...
    ]
    ```

###### Check if a Camera is Online

```bash
$ uiprotect cameras 61ddb66b018e2703e7008c19 | jq .isConnected
true
```

###### Take Snapshot of Camera

```bash
$ uiprotect cameras 61ddb66b018e2703e7008c19 save-snapshot output.jpg
```

#### Adoptable Devices CLI Commands

Adoptable devices (Cameras, Chimes, Lights, Sensors, Viewers) all have some commands in common.

| Command   | Description                                       |
| --------- | ------------------------------------------------- |
| `adopt`   | Adopts a device.                                  |
| `bridge`  | Returns bridge device if connected via Bluetooth. |
| `reboot`  | Reboots the device.                               |
| `unadopt` | Unadopt/Unmanage adopted device.                  |
| `update`  | Updates the device.                               |

Most of these are unavailable in public-only mode; see the list under
[Public-only mode](#public-only-mode).

#### Liveviews CLI

The `liveviews` command group is driven by the Public Integration API and
authenticates with an API key only (no username/password required). It exposes
four subcommands:

| Command  | Description                                                   |
| -------- | ------------------------------------------------------------- |
| `list`   | List all liveviews.                                           |
| `show`   | Show a single liveview by ID.                                 |
| `create` | Create a new liveview.                                        |
| `update` | Update an existing liveview; omitted fields keep their value. |

```bash
# list all liveviews
uiprotect liveviews list

# show a single liveview
uiprotect liveviews show LIVEVIEW_ID

# create a new liveview
uiprotect liveviews create \
  --name "Garage" \
  --owner USER_ID \
  --layout 4 \
  --slots '[{"cameras":["CAMERA_ID"],"cycleMode":"motion","cycleInterval":10}]'

# patch an existing liveview
uiprotect liveviews update LIVEVIEW_ID --name "New name"
```

`--slots` takes a JSON array of slot objects with keys `cameras`, `cycleMode`
(`motion` or `time`), and `cycleInterval`. `--layout` must be between 1 and 26.
See `uiprotect liveviews --help` (and `--help` on each subcommand) for the
full flag list.

#### Public Integration API Device Groups

The following command groups are driven by Ubiquiti's documented
[Public Integration API](usage.md#public-vs-private-api) and authenticate with
an API key (set `UFP_API_KEY`, or create one with `uiprotect create-api-key`),
not username/password. Each exposes `list` and (where applicable) `show`
subcommands plus group-specific actions; run `uiprotect <group> --help` for the
full flag list.

| Group              | Common subcommands                                                            |
| ------------------ | ----------------------------------------------------------------------------- |
| `arm`              | `list`, `status`, `set-profile`, `enable-alarm`, `disable-alarm`, `trigger`   |
| `bridges`          | `list`, `show`, `set-name`                                                    |
| `fobs`             | `list`, `show`, `set-name`                                                    |
| `files-public`     | `list`, `upload`                                                              |
| `link-stations`    | `list`, `show`, `set-name`, `trigger-output`                                  |
| `relays`           | `list`, `show`, `activate`, `set-name`, `set-status-light`                    |
| `sirens`           | `list`, `show`, `play`, `stop`, `test-sound`, `set-volume`                    |
| `speakers`         | `list`, `show`, `set-name`, `set-volume`, `set-mic-volume`, `set-mic-enabled` |
| `users-public`     | `list`, `show`                                                                |
| `ulp-users-public` | `list`, `show`                                                                |

```bash
# list public-API sirens (API key auth)
uiprotect sirens list

# rename a viewer with only an API key
uiprotect viewers VIEWER_ID set-name "Living Room"
```

The top-level `uiprotect get-meta-info` command is also Public-API driven.
`uiprotect create-api-key NAME` runs against the private, session-authenticated
(username/password) surface — you must already have a private session to mint
an API key.

#### Camera CLI

Inherits [Multiple Item CLI Commands](#multiple-item-cli-commands) and [Adoptable Devices CLI Commands](#adoptable-devices-cli-commands).

##### Examples

###### Take Snapshot of Camera

```bash
$ uiprotect cameras 61ddb66b018e2703e7008c19 save-snapshot output.jpg
```

###### Export Video From Camera

```bash
$ uiprotect cameras 61ddb66b018e2703e7008c19 save-video export.mp4 2022-6-1T00:00:00 2022-6-1T00:00:30
```

!!! note "Timezones"

    See the section on [Timezones](#timezones) for determining what timezone your datetimes are in.

###### Play Audio File to Cameras Speaker

```bash
$ uiprotect cameras 61ddb66b018e2703e7008c19 play-audio test.mp3
```

###### Include Unadopted Cameras in list

```bash
$ uiprotect -u cameras list-ids
```

###### Adopt an Unadopted Camera

```bash
$ uiprotect -u cameras 61ddb66b018e2703e7008c19 adopt
```

###### Enable SSH on Camera

```bash
$ uiprotect cameras 61ddb66b018e2703e7008c19 set-ssh true

# get current value to verify
$ uiprotect cameras 61ddb66b018e2703e7008c19 | jq .isSshEnabled
true
```

###### Reboot Camera

```bash
$ uiprotect cameras 61ddb66b018e2703e7008c19 reboot
```

###### Reboot All Cameras

```bash
for id in $(uiprotect cameras list-ids | awk '{ print $1 }'); do
    uiprotect cameras $id reboot
done
```

#### Chime CLI

Inherits [Multiple Item CLI Commands](#multiple-item-cli-commands) and [Adoptable Devices CLI Commands](#adoptable-devices-cli-commands).

##### Examples

###### Set Paired Cameras

```bash
$ uiprotect chimes 6275b22e00e3c403e702a019 cameras 61ddb66b018e2703e7008c19 61f9824e004adc03e700132c
```
