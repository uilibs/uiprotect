from __future__ import annotations

from dataclasses import dataclass

import typer

from ..api import ProtectApiClient
from ..cli import base
from ..data import MountType, Sensor, SensorScheduleMode

app = typer.Typer(rich_markup_mode="rich")

ARG_DEVICE_ID = typer.Argument(None, help="ID of sensor to select for subcommands")


@dataclass
class SensorContext(base.CliContext):
    devices: dict[str, Sensor]
    device: Sensor | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: str | None = ARG_DEVICE_ID) -> None:
    """
    Sensors device CLI.

    Returns full list of Sensors without any arguments passed.
    """
    protect: ProtectApiClient = ctx.obj.protect
    context = SensorContext(
        protect=ctx.obj.protect,
        device=None,
        devices=protect.bootstrap.sensors,
        output_format=ctx.obj.output_format,
    )
    ctx.obj = context

    if device_id is not None and device_id not in ALL_COMMANDS:
        if (device := protect.bootstrap.sensors.get(device_id)) is None:
            typer.secho("Invalid sensor ID", fg="red")
            raise typer.Exit(1)
        ctx.obj.device = device

    if not ctx.invoked_subcommand:
        if device_id in ALL_COMMANDS:
            ctx.invoke(ALL_COMMANDS[device_id], ctx)
            return

        if ctx.obj.device is not None:
            base.print_unifi_obj(ctx.obj.device, ctx.obj.output_format)
            return

        base.print_unifi_dict(ctx.obj.devices)


@app.command()
def camera(ctx: typer.Context, camera_id: str | None = typer.Argument(None)) -> None:
    """Returns or sets the paired camera for a sensor."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    if camera_id is None:
        base.print_unifi_obj(obj.camera, ctx.obj.output_format)
    else:
        protect: ProtectApiClient = ctx.obj.protect
        if (camera_obj := protect.bootstrap.cameras.get(camera_id)) is None:
            typer.secho("Invalid camera ID")
            raise typer.Exit(1)
        base.run(ctx, obj.set_paired_camera(camera_obj))


@app.command()
def is_tampering_detected(ctx: typer.Context) -> None:
    """Returns if tampering is detected for sensor"""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device
    base.json_output(obj.is_tampering_detected)


@app.command()
def is_alarm_detected(ctx: typer.Context) -> None:
    """Returns if alarm is detected for sensor"""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device
    base.json_output(obj.is_alarm_detected)


@app.command()
def is_contact_enabled(ctx: typer.Context) -> None:
    """Returns if contact sensor is enabled for sensor"""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device
    base.json_output(obj.is_contact_sensor_enabled)


@app.command()
def is_motion_enabled(ctx: typer.Context) -> None:
    """Returns if motion sensor is enabled for sensor"""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device
    base.json_output(obj.is_contact_sensor_enabled)


@app.command()
def is_alarm_enabled(ctx: typer.Context) -> None:
    """Returns if alarm sensor is enabled for sensor"""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device
    base.json_output(obj.is_alarm_sensor_enabled)


@app.command()
def is_light_enabled(ctx: typer.Context) -> None:
    """Returns if light sensor is enabled for sensor"""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device
    base.json_output(obj.is_light_sensor_enabled)


@app.command()
def is_temperature_enabled(ctx: typer.Context) -> None:
    """Returns if temperature sensor is enabled for sensor"""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device
    base.json_output(obj.is_temperature_sensor_enabled)


@app.command()
def is_humidity_enabled(ctx: typer.Context) -> None:
    """Returns if humidity sensor is enabled for sensor"""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device
    base.json_output(obj.is_humidity_sensor_enabled)


@app.command()
def set_status_light(ctx: typer.Context, enabled: bool) -> None:
    """Sets status light for sensor device."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_status_light(enabled))


@app.command()
def set_mount_type(ctx: typer.Context, mount_type: MountType) -> None:
    """Sets mount type for sensor device."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_mount_type(mount_type))


@app.command()
def set_motion(ctx: typer.Context, enabled: bool) -> None:
    """Sets motion sensor status for sensor device."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_motion_status(enabled))


@app.command()
def set_temperature(ctx: typer.Context, enabled: bool) -> None:
    """Sets temperature sensor status for sensor device."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_temperature_status(enabled))


@app.command()
def set_humidity(ctx: typer.Context, enabled: bool) -> None:
    """Sets humidity sensor status for sensor device."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_humidity_status(enabled))


@app.command()
def set_light(ctx: typer.Context, enabled: bool) -> None:
    """Sets light sensor status for sensor device."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_light_status(enabled))


@app.command()
def set_alarm(ctx: typer.Context, enabled: bool) -> None:
    """Sets alarm sensor status for sensor device."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_alarm_status(enabled))


@app.command()
def set_motion_sensitivity(
    ctx: typer.Context,
    sensitivity: int = typer.Argument(..., min=0, max=100),
) -> None:
    """Sets motion sensitivity for the sensor."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_motion_sensitivity(sensitivity))


@app.command()
def set_temperature_range(
    ctx: typer.Context,
    low: float = typer.Argument(..., min=0, max=44),
    high: float = typer.Argument(..., min=1, max=45),
) -> None:
    """Sets temperature safe range (in °C). Anything out side of range will trigger event."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_temperature_safe_range(low, high))


@app.command()
def set_humidity_range(
    ctx: typer.Context,
    low: float = typer.Argument(..., min=1, max=98),
    high: float = typer.Argument(..., min=2, max=99),
) -> None:
    """Sets humidity safe range (in relative % humidity). Anything out side of range will trigger event."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_humidity_safe_range(low, high))


@app.command()
def set_light_range(
    ctx: typer.Context,
    low: float = typer.Argument(..., min=1, max=999),
    high: float = typer.Argument(..., min=2, max=1000),
) -> None:
    """Sets light safe range (in lux). Anything out side of range will trigger event."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_light_safe_range(low, high))


@app.command()
def remove_temperature_range(ctx: typer.Context) -> None:
    """Removes temperature safe ranges so events will no longer fire."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.remove_temperature_safe_range())


@app.command()
def remove_humidity_range(ctx: typer.Context) -> None:
    """Removes humidity safe ranges so events will no longer fire."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.remove_humidity_safe_range())


@app.command()
def remove_light_range(ctx: typer.Context) -> None:
    """Removes light safe ranges so events will no longer fire."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.remove_light_safe_range())


@app.command()
def set_name_public(ctx: typer.Context, name: str) -> None:
    """Sets sensor name via the public API."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_name_public(name))


@app.command()
def set_temperature_settings_public(
    ctx: typer.Context,
    is_enabled: bool | None = typer.Option(None),
    low_threshold: float | None = typer.Option(None),
    high_threshold: float | None = typer.Option(None),
    margin: float | None = typer.Option(None),
) -> None:
    """Updates temperature alert settings via the public API."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(
        ctx,
        obj.set_temperature_settings_public(
            is_enabled=is_enabled,
            low_threshold=low_threshold,
            high_threshold=high_threshold,
            margin=margin,
        ),
    )


@app.command()
def set_humidity_settings_public(
    ctx: typer.Context,
    is_enabled: bool | None = typer.Option(None),
    low_threshold: int | None = typer.Option(None),
    high_threshold: int | None = typer.Option(None),
    margin: int | None = typer.Option(None),
) -> None:
    """Updates humidity alert settings via the public API."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(
        ctx,
        obj.set_humidity_settings_public(
            is_enabled=is_enabled,
            low_threshold=low_threshold,
            high_threshold=high_threshold,
            margin=margin,
        ),
    )


@app.command()
def set_light_settings_public(
    ctx: typer.Context,
    is_enabled: bool | None = typer.Option(None),
    low_threshold: int | None = typer.Option(None),
    high_threshold: int | None = typer.Option(None),
    margin: int | None = typer.Option(None),
) -> None:
    """Updates light (lux) alert settings via the public API."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(
        ctx,
        obj.set_light_settings_public(
            is_enabled=is_enabled,
            low_threshold=low_threshold,
            high_threshold=high_threshold,
            margin=margin,
        ),
    )


@app.command()
def set_motion_settings_public(
    ctx: typer.Context,
    is_enabled: bool | None = typer.Option(None),
    sensitivity: int | None = typer.Option(None),
    sensitivity_when_armed: int | None = typer.Option(None),
) -> None:
    """Updates motion detection settings via the public API."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(
        ctx,
        obj.set_motion_settings_public(
            is_enabled=is_enabled,
            sensitivity=sensitivity,
            sensitivity_when_armed=sensitivity_when_armed,
        ),
    )


@app.command()
def set_glass_break_settings_public(
    ctx: typer.Context,
    is_enabled: bool | None = typer.Option(None),
    sensitivity: int | None = typer.Option(None),
    sensitivity_when_armed: int | None = typer.Option(None),
) -> None:
    """Updates glass-break detection settings via the public API."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(
        ctx,
        obj.set_glass_break_settings_public(
            is_enabled=is_enabled,
            sensitivity=sensitivity,
            sensitivity_when_armed=sensitivity_when_armed,
        ),
    )


@app.command()
def set_alarm_public(ctx: typer.Context, enabled: bool) -> None:
    """Sets alarm detection setting via the public API."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_alarm_settings_public(enabled))


@app.command()
def set_schedule_mode_public(ctx: typer.Context, mode: SensorScheduleMode) -> None:
    """Sets the arm-schedule mode via the public API."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_schedule_mode_public(mode))


@app.command()
def set_arm_profiles_public(ctx: typer.Context, arm_profile_ids: list[str]) -> None:
    """Sets the arm-profile ids via the public API."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_arm_profile_ids_public(arm_profile_ids))


@app.command()
def set_custom_sensitivity_public(ctx: typer.Context, enabled: bool) -> None:
    """Toggles custom armed sensitivity via the public API."""
    base.require_device_id(ctx)
    obj: Sensor = ctx.obj.device

    base.run(ctx, obj.set_custom_sensitivity_when_armed_public(enabled))
