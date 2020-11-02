"""Unifi Protect Data."""
import datetime
import enum
import logging
import struct
import zlib

WS_HEADER_SIZE = 8
_LOGGER = logging.getLogger(__name__)

EVENT_SMART_DETECT_ZONE = "smartDetectZone"
EVENT_MOTION = "motion"
EVENT_RING = "ring"

PROCESSED_EVENT_EMPTY = {
    "event_start": None,
    "event_score": 0,
    "event_thumbnail": None,
    "event_heatmap": None,
    "event_on": False,
    "event_ring_on": False,
    "event_type": None,
    "event_length": 0,
    "event_object": [],
}


@enum.unique
class ProtectWSPayloadFormat(enum.Enum):
    """Websocket Payload formats."""

    JSON = 1
    UTF8String = 2
    NodeBuffer = 3


def decode_ws_frame(frame, position):
    """Decode a unifi updates websocket frame."""
    # The format of the frame is
    # b: packet_type
    # b: payload_format
    # b: deflated
    # b: unknown
    # i: payload_size
    _, payload_format, deflated, _, payload_size = struct.unpack(
        "!bbbbi", frame[position : position + WS_HEADER_SIZE]
    )
    position += WS_HEADER_SIZE
    frame = frame[position : position + payload_size]
    if deflated:
        frame = zlib.decompress(frame)
    position += payload_size
    return frame, ProtectWSPayloadFormat(payload_format), position


def process_camera(server_id, host, camera):
    """Process the camera json."""
    # Get if camera is online
    online = camera["state"] == "CONNECTED"
    # Get Recording Mode
    recording_mode = str(camera["recordingSettings"]["mode"])
    # Get Infrared Mode
    ir_mode = str(camera["ispSettings"]["irLedMode"])
    # Get Status Light Setting
    status_light = str(camera["ledSettings"]["isEnabled"])

    # Get the last time motion occured
    lastmotion = (
        None
        if camera["lastMotion"] is None
        else datetime.datetime.fromtimestamp(int(camera["lastMotion"]) / 1000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )
    # Get the last time doorbell was ringing
    lastring = (
        None
        if camera.get("lastRing") is None
        else datetime.datetime.fromtimestamp(int(camera["lastRing"]) / 1000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )
    # Get when the camera came online
    upsince = (
        "Offline"
        if camera["upSince"] is None
        else datetime.datetime.fromtimestamp(int(camera["upSince"]) / 1000).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )
    # Check if Regular Camera or Doorbell
    device_type = (
        "camera" if "doorbell" not in str(camera["type"]).lower() else "doorbell"
    )
    # Get Firmware Version
    firmware_version = str(camera["firmwareVersion"])

    # Get High FPS Video Mode
    featureflags = camera.get("featureFlags")
    has_highfps = "highFps" in featureflags.get("videoModes", "")
    video_mode = camera.get("videoMode") or "default"
    # Get HDR Mode
    has_hdr = featureflags.get("hasHdr")
    hdr_mode = camera.get("hdrMode") or False

    # Add rtsp streaming url if enabled
    rtsp = None
    channels = camera["channels"]
    for channel in channels:
        if channel["isRtspEnabled"]:
            rtsp = f"rtsp://{host}:7447/{channel['rtspAlias']}"
            break

    return {
        "name": str(camera["name"]),
        "type": device_type,
        "model": str(camera["type"]),
        "mac": str(camera["mac"]),
        "ip_address": str(camera["host"]),
        "firmware_version": firmware_version,
        "server_id": server_id,
        "recording_mode": recording_mode,
        "ir_mode": ir_mode,
        "status_light": status_light,
        "rtsp": rtsp,
        "up_since": upsince,
        "last_motion": lastmotion,
        "last_ring": lastring,
        "online": online,
        "has_highfps": has_highfps,
        "has_hdr": has_hdr,
        "video_mode": video_mode,
        "hdr_mode": hdr_mode,
    }


def process_event(event, minimum_score, event_ring_check_converted):
    """Convert an event to our format."""
    event_type = event["type"]
    event_length = 0
    event_objects = None
    processed_event = {"event_on": False, "event_ring_on": False}

    if event["start"]:
        start_time = _process_timestamp(event["start"])
        event_length = 0
    else:
        start_time = None

    if event_type in (EVENT_MOTION, EVENT_SMART_DETECT_ZONE):
        if event["end"]:
            event_length = (float(event["end"]) / 1000) - (float(event["start"]) / 1000)
            if event_type == EVENT_SMART_DETECT_ZONE:
                event_objects = event["smartDetectTypes"]
        else:
            if int(event["score"]) >= minimum_score:
                processed_event["event_on"] = True
                if event_type == EVENT_SMART_DETECT_ZONE:
                    event_objects = event["smartDetectTypes"]
        processed_event["last_motion"] = start_time
    else:
        processed_event["last_ring"] = start_time
        if event["end"]:
            if (
                event["start"] >= event_ring_check_converted
                and event["end"] >= event_ring_check_converted
            ):
                _LOGGER.debug("EVENT: DOORBELL HAS RUNG IN LAST 3 SECONDS!")
                processed_event["event_ring_on"] = True
            else:
                _LOGGER.debug("EVENT: DOORBELL WAS NOT RUNG IN LAST 3 SECONDS")
        else:
            _LOGGER.debug("EVENT: DOORBELL IS RINGING")
            processed_event["event_ring_on"] = True

    processed_event["event_start"] = start_time
    processed_event["event_score"] = event["score"]
    processed_event["event_type"] = event_type
    processed_event["event_length"] = event_length
    if event_objects is not None:
        processed_event["event_object"] = event_objects
    if event["thumbnail"] is not None:  # Only update if there is a new Motion Event
        processed_event["event_thumbnail"] = event["thumbnail"]
    if event["heatmap"] is not None:  # Only update if there is a new Motion Event
        processed_event["event_heatmap"] = event["heatmap"]
    return processed_event


def _process_timestamp(time_stamp):
    return datetime.datetime.fromtimestamp(int(time_stamp) / 1000).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
