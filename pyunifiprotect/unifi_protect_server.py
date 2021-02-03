"""Unifi Protect Server Wrapper."""

import asyncio
import datetime
import json as pjson
import logging
import time

import aiohttp
from aiohttp import client_exceptions
import jwt

from .const import SERVER_ID, SERVER_NAME
from .unifi_data import (
    DEVICE_MODEL_LIGHT,
    EVENT_MOTION,
    EVENT_RING,
    EVENT_SMART_DETECT_ZONE,
    PRIVACY_OFF,
    PRIVACY_ON,
    PROCESSED_EVENT_EMPTY,
    TYPE_RECORD_NEVER,
    ZONE_NAME,
    ProtectDeviceStateMachine,
    ProtectEventStateMachine,
    ProtectWSPayloadFormat,
    camera_event_from_ws_frames,
    camera_update_from_ws_frames,
    decode_ws_frame,
    event_from_ws_frames,
    light_event_from_ws_frames,
    light_update_from_ws_frames,
    process_camera,
    process_event,
    process_light,
)

DEVICE_UPDATE_INTERVAL_SECONDS = 60
WEBSOCKET_CHECK_INTERVAL_SECONDS = 120
LIGHT_MODES = ["off", "motion", "always"]
LIGHT_ENABLED = ["dark", "fulltime"]
LIGHT_DURATIONS = [15000, 30000, 60000, 300000, 900000]


class Invalid(Exception):
    """Invalid return from Authorization Request."""


class NotAuthorized(Exception):
    """Wrong username and/or Password."""


class NvrError(Exception):
    """Other error."""


_LOGGER = logging.getLogger(__name__)


class UpvServer:  # pylint: disable=too-many-public-methods, too-many-instance-attributes
    """Updates device States and Attributes."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        username: str,
        password: str,
        verify_ssl: bool = False,
        minimum_score: int = 0,
    ):
        self._host = host
        self._port = port
        self._base_url = f"https://{host}:{port}"
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._minimum_score = minimum_score
        self.is_unifi_os = None
        self.api_path = "api"
        self.ws_path = "ws"
        self._is_authenticated = False
        self._last_device_update_time = 0
        self._last_websocket_check = 0
        self.access_key = None
        self._processed_data = {}
        self._event_state_machine = ProtectEventStateMachine()
        self._device_state_machine = ProtectDeviceStateMachine()

        self._motion_start_time = {}
        self.last_update_id = None

        self.req = session
        self.headers = None
        self.ws_session = None
        self.ws_connection = None
        self.ws_task = None
        self._ws_subscriptions = []
        self._is_first_update = True

    @property
    def devices(self):
        """ Returns a JSON formatted list of Devices. """
        return self._processed_data

    async def update(self, force_camera_update=False) -> dict:
        """Updates the status of devices."""

        current_time = time.time()
        device_update = False
        if (
            not self.ws_connection
            and force_camera_update
            or (current_time - DEVICE_UPDATE_INTERVAL_SECONDS)
            > self._last_device_update_time
        ):
            _LOGGER.debug("Doing device update")
            device_update = True
            await self._get_device_list(not self.ws_connection)
            self._last_device_update_time = current_time
        else:
            _LOGGER.debug("Skipping device update")

        if (
            self.is_unifi_os
            and (current_time - WEBSOCKET_CHECK_INTERVAL_SECONDS)
            > self._last_websocket_check
        ):
            _LOGGER.debug("Checking websocket")
            self._last_websocket_check = current_time
            await self.async_connect_ws()

        # If the websocket is connected/connecting
        # we do not need to get events
        if self.ws_connection or self._last_websocket_check == current_time:
            _LOGGER.debug("Skipping update since websocket is active")
            return self._processed_data if device_update else {}

        self._reset_device_events()
        updates = await self._get_events(lookback=10)

        return self._processed_data if device_update else updates

    async def async_connect_ws(self):
        """Connect the websocket."""
        if self.ws_connection is not None:
            return

        if self.ws_task is not None:
            try:
                self.ws_task.cancel()
                self.ws_connection = None
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Could not cancel ws_task")
        self.ws_task = asyncio.ensure_future(self._setup_websocket())

    async def async_disconnect_ws(self):
        """Disconnect the websocket."""
        if self.ws_connection is None:
            return

        await self.ws_connection.close()
        await self.ws_session.close()

    async def server_information(self):
        """Returns a Server Information for this NVR."""
        return await self._get_server_info()

    async def check_unifi_os(self):
        """Check to see if the device is running unifi os."""
        if self.is_unifi_os is not None:
            return

        response = await self.request("get", url=self._base_url, allow_redirects=False)
        if response.status != 200:
            return
        if response.headers.get("x-csrf-token"):
            self.is_unifi_os = True
            self.api_path = "proxy/protect/api"
            self.ws_path = "proxy/protect/ws"
            self.headers = {"x-csrf-token": response.headers.get("x-csrf-token")}
        else:
            self.is_unifi_os = False
        _LOGGER.debug("Unifi OS: %s", self.is_unifi_os)

    async def ensure_authenticated(self):
        """Ensure we are authenticated."""
        if self.is_authenticated() is False:
            await self.authenticate()

    async def authenticate(self):
        """Authenticate and get a token."""
        await self.check_unifi_os()
        if self.is_unifi_os:
            url = f"{self._base_url}/api/auth/login"
            self.req.cookie_jar.clear()
        else:
            url = f"{self._base_url}/api/auth"

        auth = {
            "username": self._username,
            "password": self._password,
            "remember": True,
        }

        response = await self.request("post", url=url, json=auth)
        if self.is_unifi_os is True:
            self.headers = {
                "x-csrf-token": response.headers.get("x-csrf-token"),
                "cookie": response.headers.get("set-cookie"),
            }
        else:
            self.headers = {
                "Authorization": f"Bearer {response.headers.get('Authorization')}"
            }
        self._is_authenticated = True
        _LOGGER.debug("Authenticated successfully!")

    def is_authenticated(self) -> bool:
        """Check to see if we are already authenticated."""
        if self._is_authenticated is True and self.is_unifi_os is True:
            # Check if token is expired.
            cookies = self.req.cookie_jar.filter_cookies(self._base_url)
            token_cookie = cookies.get("TOKEN")
            if token_cookie is None:
                return False
            try:
                jwt.decode(
                    token_cookie.value,
                    options={"verify_signature": False, "verify_exp": True},
                )
            except jwt.ExpiredSignatureError:
                _LOGGER.debug("Authentication token has expired.")
                return False
            except Exception as broad_ex:  # pylint: disable=broad-except
                _LOGGER.debug("Authentication token decode error: %s", broad_ex)
                return False

        return self._is_authenticated

    async def _get_api_access_key(self) -> str:
        """get API Access Key."""
        if self.is_unifi_os:
            return ""

        access_key_uri = f"{self._base_url}/{self.api_path}/auth/access-key"
        async with self.req.post(
            access_key_uri,
            headers=self.headers,
            ssl=self._verify_ssl,
        ) as response:
            if response.status == 200:
                json_response = await response.json()
                return json_response["accessKey"]
            raise NvrError(
                f"Request failed: {response.status} - Reason: {response.reason}"
            )

    async def _get_unique_id(self) -> None:
        """Get a Unique ID for this NVR."""

        return await self._get_server_info()[SERVER_ID]

    async def _get_server_info(self) -> None:
        """Get Server Information for this NVR."""

        await self.ensure_authenticated()

        bootstrap_uri = f"{self._base_url}/{self.api_path}/bootstrap"
        response = await self.req.get(
            bootstrap_uri,
            headers=self.headers,
            ssl=self._verify_ssl,
        )
        if response.status != 200:
            raise NvrError(
                f"Fetching Unique ID failed: {response.status} - Reason: {response.reason}"
            )
        json_response = await response.json()
        nvr_data = json_response["nvr"]

        return {
            SERVER_NAME: nvr_data["name"],
            "server_version": nvr_data["version"],
            SERVER_ID: nvr_data["mac"],
            "server_model": nvr_data["type"],
            "unifios": self.is_unifi_os,
        }

    async def _get_device_list(self, include_events) -> None:
        """Get a list of devices connected to the NVR."""

        await self.ensure_authenticated()

        bootstrap_uri = f"{self._base_url}/{self.api_path}/bootstrap"
        response = await self.req.get(
            bootstrap_uri,
            headers=self.headers,
            ssl=self._verify_ssl,
        )
        if response.status != 200:
            raise NvrError(
                f"Fetching Camera List failed: {response.status} - Reason: {response.reason}"
            )
        json_response = await response.json()
        server_id = json_response["nvr"]["mac"]
        if not self.ws_connection and "lastUpdateId" in json_response:
            self.last_update_id = json_response["lastUpdateId"]

        self._process_cameras_json(json_response, server_id, include_events)
        self._process_lights_json(json_response, server_id, include_events)

        self._is_first_update = False

    def _process_cameras_json(self, json_response, server_id, include_events):
        for camera in json_response["cameras"]:

            # Ignore cameras adopted by another controller on the same network
            # since they appear in the api on 1.17+
            if "isAdopted" in camera and not camera["isAdopted"]:
                continue

            camera_id = camera["id"]

            if self._is_first_update:
                self._update_device(camera_id, PROCESSED_EVENT_EMPTY)
            self._device_state_machine.update(camera_id, camera)
            self._update_device(
                camera_id,
                process_camera(
                    server_id,
                    self._host,
                    camera,
                    include_events or self._is_first_update,
                ),
            )

    def _process_lights_json(self, json_response, server_id, include_events):
        for light in json_response["lights"]:

            # Ignore lights adopted by another controller on the same network
            # since they appear in the api on 1.17+
            if "isAdopted" in light and not light["isAdopted"]:
                continue

            light_id = light["id"]

            if self._is_first_update:
                self._update_device(light_id, PROCESSED_EVENT_EMPTY)
            self._device_state_machine.update(light_id, light)

            self._update_device(
                light_id,
                process_light(
                    server_id, light, include_events or self._is_first_update
                ),
            )

    def _reset_device_events(self) -> None:
        """Reset device events between device updates."""
        for device_id in self._processed_data:
            self._update_device(device_id, PROCESSED_EVENT_EMPTY)

    async def _get_events(
        self, lookback: int = 86400, camera=None, start_time=None, end_time=None
    ) -> None:
        """Load the Event Log and loop through items to find motion events."""

        await self.ensure_authenticated()

        now = int(time.time() * 1000)
        if start_time is None:
            start_time = now - (lookback * 1000)
        if end_time is None:
            end_time = now + 10000
        event_ring_check_converted = now - 3000

        event_uri = f"{self._base_url}/{self.api_path}/events"

        params = {
            "end": str(end_time),
            "start": str(start_time),
        }
        if camera:
            params["cameras"] = camera
        response = await self.req.get(
            event_uri,
            params=params,
            headers=self.headers,
            ssl=self._verify_ssl,
        )
        if response.status != 200:
            raise NvrError(
                f"Fetching Eventlog failed: {response.status} - Reason: {response.reason}"
            )

        updated = {}
        for event in await response.json():
            if event["type"] not in (EVENT_MOTION, EVENT_RING, EVENT_SMART_DETECT_ZONE):
                continue

            camera_id = event["camera"]
            self._update_device(
                camera_id,
                process_event(event, self._minimum_score, event_ring_check_converted),
            )
            updated[camera_id] = self._processed_data[camera_id]

        return updated

    async def get_raw_events(self, lookback: int = 86400) -> None:
        """Load the Event Log and return the Raw Data - Used for debugging only."""

        await self.ensure_authenticated()

        event_start = datetime.datetime.now() - datetime.timedelta(seconds=lookback)
        event_end = datetime.datetime.now() + datetime.timedelta(seconds=10)
        start_time = int(time.mktime(event_start.timetuple())) * 1000
        end_time = int(time.mktime(event_end.timetuple())) * 1000

        event_uri = f"{self._base_url}/{self.api_path}/events"
        params = {
            "end": str(end_time),
            "start": str(start_time),
        }
        async with self.req.get(
            event_uri,
            params=params,
            headers=self.headers,
            ssl=self._verify_ssl,
        ) as response:
            if response.status != 200:
                raise NvrError(
                    f"Fetching Eventlog failed: {response.status} - Reason: {response.reason}"
                )
            return await response.json()

    async def get_raw_device_info(self) -> None:
        """Return the RAW JSON data from this NVR.
        Used for debugging purposes only.
        """

        await self.ensure_authenticated()

        bootstrap_uri = f"{self._base_url}/{self.api_path}/bootstrap"
        async with self.req.get(
            bootstrap_uri,
            headers=self.headers,
            ssl=self._verify_ssl,
        ) as response:
            if response.status != 200:
                raise NvrError(
                    f"Fetching Raw Device Data failed: {response.status} - Reason: {response.reason}"
                )
            return await response.json()

    async def get_thumbnail(self, camera_id: str, width: int = 640) -> bytes:
        """Returns the last recorded Thumbnail, based on Camera ID."""

        await self.ensure_authenticated()
        await self._get_events(camera=camera_id)

        thumbnail_id = self._processed_data[camera_id]["event_thumbnail"]

        if thumbnail_id is None:
            return None
        height = float(width) / 16 * 9
        img_uri = f"{self._base_url}/{self.api_path}/thumbnails/{thumbnail_id}"
        params = {
            "accessKey": await self._get_api_access_key(),
            "h": str(height),
            "w": str(width),
        }
        async with self.req.get(
            img_uri,
            params=params,
            headers=self.headers,
            ssl=self._verify_ssl,
        ) as response:
            if response.status != 200:
                raise NvrError(
                    f"Thumbnail Request failed: {response.status} - Reason: {response.reason}"
                )
            return await response.read()

    async def get_heatmap(self, camera_id: str) -> bytes:
        """Returns the last recorded Heatmap, based on Camera ID."""

        await self.ensure_authenticated()
        await self._get_events(camera=camera_id)

        heatmap_id = self._processed_data[camera_id]["event_heatmap"]

        if heatmap_id is None:
            return None

        img_uri = f"{self._base_url}/{self.api_path}/heatmaps/{heatmap_id}"
        params = {
            "accessKey": await self._get_api_access_key(),
        }
        async with self.req.get(
            img_uri,
            params=params,
            headers=self.headers,
            ssl=self._verify_ssl,
        ) as response:
            if response.status != 200:
                raise NvrError(
                    f"Heatmap Request failed: {response.status} - Reason: {response.reason}"
                )
            return await response.read()

    async def get_snapshot_image(self, camera_id: str) -> bytes:
        """ Returns a Snapshot image of a recording event. """

        await self.ensure_authenticated()

        access_key = await self._get_api_access_key()
        time_since = int(time.mktime(datetime.datetime.now().timetuple())) * 1000
        model_type = self._processed_data[camera_id]["model"]
        if model_type.find("G4") != -1:
            image_width = "3840"
            image_height = "2160"
        else:
            image_width = "1920"
            image_height = "1080"

        img_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}/snapshot"
        params = {
            "accessKey": access_key,
            "h": image_height,
            "ts": str(time_since),
            "force": "true",
            "w": image_width,
        }
        async with self.req.get(
            img_uri, params=params, headers=self.headers, ssl=self._verify_ssl
        ) as response:
            if response.status == 200:
                return await response.read()
            _LOGGER.warning(
                "Error Code: %s - Error Status: %s", response.status, response.reason
            )
            return None

    async def get_snapshot_image_direct(self, camera_id: str) -> bytes:
        """Returns a Snapshot image of a recording event.
        This function will only work if Anonymous Snapshots
        are enabled on the Camera.
        """
        ip_address = self._processed_data[camera_id]["ip_address"]

        img_uri = f"http://{ip_address}/snap.jpeg"
        async with self.req.get(img_uri) as response:
            if response.status == 200:
                return await response.read()
            raise NvrError(
                f"Direct Snapshot failed: {response.status} - Reason: {response.reason}"
            )

    async def set_camera_recording(self, camera_id: str, mode: str) -> bool:
        """Sets the camera recoding mode to what is supplied with 'mode'.
        Valid inputs for mode: never, motion, always, smartDetect
        """
        if "smart" in mode:
            mode = "smartDetect"

        await self.ensure_authenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {
            "recordingSettings": {
                "mode": mode,
                "prePaddingSecs": 2,
                "postPaddingSecs": 2,
                "minMotionEventTrigger": 1000,
                "enablePirTimelapse": False,
            }
        }

        async with self.req.patch(
            cam_uri, headers=self.headers, ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self._processed_data[camera_id]["recording_mode"] = mode
                return True
            raise NvrError(
                f"Set Recording Mode failed: {response.status} - Reason: {response.reason}"
            )

    async def set_camera_ir(self, camera_id: str, mode: str) -> bool:
        """Sets the camera infrared settings to what is supplied with 'mode'.
        Valid inputs for mode: auto, on, autoFilterOnly
        """

        await self.ensure_authenticated()

        if mode == "led_off":
            mode = "autoFilterOnly"
        elif mode == "always_on":
            mode = "on"
        elif mode == "always_off":
            mode = "off"

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"ispSettings": {"irLedMode": mode, "irLedLevel": 255}}

        async with self.req.patch(
            cam_uri, headers=self.headers, ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self._processed_data[camera_id]["ir_mode"] = mode
                return True
            raise NvrError(
                "Set IR Mode failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_device_status_light(
        self, device_id: str, mode: bool, device_model: str
    ) -> bool:
        """Sets the device status light settings to what is supplied with 'mode'.
        Valid inputs for mode: False and True
        """

        await self.ensure_authenticated()

        if device_model == DEVICE_MODEL_LIGHT:
            uri = f"{self._base_url}/{self.api_path}/lights/{device_id}"
            data = {"lightDeviceSettings": {"isIndicatorEnabled": mode}}
        else:
            uri = f"{self._base_url}/{self.api_path}/cameras/{device_id}"
            data = {"ledSettings": {"isEnabled": mode, "blinkRate": 0}}

        async with self.req.patch(
            uri, headers=self.headers, ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self._processed_data[device_id]["status_light"] = mode
                return True
            raise NvrError(
                "Change Status Light failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_camera_hdr_mode(self, camera_id: str, mode: bool) -> bool:
        """Sets the camera HDR mode to what is supplied with 'mode'.
        Valid inputs for mode: False and True
        """

        await self.ensure_authenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"hdrMode": mode}

        async with self.req.patch(
            cam_uri, headers=self.headers, ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self._device_state_machine.update(camera_id, data)
                self._processed_data[camera_id]["hdr_mode"] = mode
                return True
            raise NvrError(
                "Change HDR mode failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_camera_video_mode_highfps(self, camera_id: str, mode: bool) -> bool:
        """Sets the camera High FPS video mode to what is supplied with 'mode'.
        Valid inputs for mode: False and True
        """

        highfps = "highFps" if mode is True else "default"

        await self.ensure_authenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"videoMode": highfps}

        async with self.req.patch(
            cam_uri, headers=self.headers, ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self._device_state_machine.update(camera_id, data)
                self._processed_data[camera_id]["video_mode"] = highfps
                return True
            raise NvrError(
                "Change Video mode failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_camera_zoom_position(self, camera_id: str, position: int) -> bool:
        """Sets the cameras optical zoom position.
        Valid inputs for position: Integer from 0 to 100
        """
        if position < 0:
            position = 0
        elif position > 100:
            position = 100

        await self.ensure_authenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"ispSettings": {"zoomPosition": position}}

        async with self.req.patch(
            cam_uri, headers=self.headers, ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self._processed_data[camera_id]["zoom_position"] = position
                return True
            raise NvrError(
                "Set Zoom Position failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_mic_volume(self, camera_id: str, level: int) -> bool:
        """Sets the camera microphone volume level.
        Valid inputs is an integer between 0 and 100.
        """

        if level < 0:
            level = 0
        elif level > 100:
            level = 100

        await self.ensure_authenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"micVolume": level}

        async with self.req.patch(
            cam_uri, headers=self.headers, ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self._device_state_machine.update(camera_id, data)
                self._processed_data[camera_id]["mic_volume"] = level
                return True
            raise NvrError(
                "Change Microphone Level failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_light_on_off(
        self, light_id: str, turn_on: bool, led_level=None
    ) -> bool:
        """Sets the light on or off.
        turn_on can be: true or false.
        led_level: must be between 1 and 6 or None
        """

        await self.ensure_authenticated()

        light_uri = f"{self._base_url}/{self.api_path}/lights/{light_id}"
        data = {"lightOnSettings": {"isLedForceOn": turn_on}}
        if led_level is not None:
            data["lightDeviceSettings"] = {"ledLevel": led_level}

        async with self.req.patch(
            light_uri, headers=self.headers, ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self._device_state_machine.update(light_id, data)
                processed_light = self._processed_data[light_id]
                processed_light["is_on"] = turn_on
                if led_level is not None:
                    processed_light["brightness"] = led_level
                return True
            raise NvrError(
                "Turn on/off light failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def light_settings(
        self, light_id: str, mode: str, enable_at=None, duration=None, sensitivity=None
    ) -> bool:
        """Sets PIR settings for a Light Device.
        mode can be: off, motion or always
        enableAt can be: dark, fulltime
        pirDuration: A number between 15000 and 900000 (ms)
        pirSensitivity: A number between 0 and 100
        """
        await self.ensure_authenticated()

        if mode not in LIGHT_MODES:
            mode = "motion"

        light_uri = f"{self._base_url}/{self.api_path}/lights/{light_id}"
        data = {"lightModeSettings": {"mode": mode}}
        if enable_at is not None:
            setting = data["lightModeSettings"]
            setting["enableAt"] = enable_at
        if duration is not None:
            if data.get("lightDeviceSettings"):
                setting = data["lightDeviceSettings"]
                setting["pirDuration"] = duration
            else:
                data["lightDeviceSettings"] = {"pirDuration": duration}
        if sensitivity is not None:
            if data.get("lightDeviceSettings"):
                setting = data["lightDeviceSettings"]
                setting["pirSensitivity"] = sensitivity
            else:
                data["lightDeviceSettings"] = {"pirSensitivity": sensitivity}

        async with self.req.patch(
            light_uri, headers=self.headers, ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                self._device_state_machine.update(light_id, data)
                processed_light = self._processed_data[light_id]
                processed_light["motion_mode"] = mode
                if enable_at is not None:
                    processed_light["motion_mode_enabled_at"] = enable_at
                if duration is not None:
                    processed_light["pir_duration"] = duration
                if sensitivity is not None:
                    processed_light["pir_sensitivity"] = sensitivity
                return True
            raise NvrError(
                "Changing light motion failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_privacy_mode(
        self, camera_id: str, mode: bool, mic_level=-1, recording_mode="notset"
    ) -> bool:
        """Sets the camera privacy mode.
        When True, creates a privacy zone that fills the camera
        When False, removes the Privacy Zone
        Valid inputs for mode: False and True
        """

        # Set Microphone Level if needed
        if mic_level >= 0:
            await self.set_mic_volume(camera_id, mic_level)

        # Set recording mode if needed
        if recording_mode != "notset":
            await self.set_camera_recording(camera_id, recording_mode)

        # Set Privacy Mask
        if mode:
            privacy_value = PRIVACY_ON
        else:
            privacy_value = PRIVACY_OFF

        # We need the current camera setup
        caminfo = await self._get_camera_detail(camera_id)
        privdata = caminfo["privacyZones"]
        zone_exist = False
        items = []

        # Update Zone Information
        for row in privdata:
            if row["name"] == ZONE_NAME:
                row["points"] = privacy_value
                zone_exist = True
            items.append(row)
        if len(items) == 0 or not zone_exist:
            items.append(
                {"name": "hass zone", "color": "#85BCEC", "points": privacy_value}
            )

        # Update the Privacy Mode
        await self.ensure_authenticated()

        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {"privacyZones": items}
        async with self.req.patch(
            cam_uri, headers=self.headers, ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                return True
            raise NvrError(
                "Change Privacy Zone failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def _get_camera_detail(self, camera_id: str) -> None:
        """Return the RAW JSON data for Camera.
        Used for debugging only.
        """

        await self.ensure_authenticated()

        bootstrap_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        async with self.req.get(
            bootstrap_uri,
            headers=self.headers,
            ssl=self._verify_ssl,
        ) as response:
            if response.status != 200:
                raise NvrError(
                    f"Fetching Camera Details failed: {response.status} - Reason: {response.reason}"
                )
            return await response.json()

    async def set_doorbell_custom_text(
        self, camera_id: str, custom_text: str, duration=None
    ) -> bool:
        """Sets a Custom Text string for the Doorbell LCD'."""

        await self.ensure_authenticated()

        message_type = "CUSTOM_MESSAGE"

        # Truncate text to max 30 characters, as this is what is supported
        custom_text = custom_text[:30]

        # Calculate ResetAt time
        if duration is not None:
            now = datetime.datetime.now()
            now_plus_duration = now + datetime.timedelta(minutes=int(duration))
            duration = int(now_plus_duration.timestamp() * 1000)

        # resetAt is Unix timestam in the future
        cam_uri = f"{self._base_url}/{self.api_path}/cameras/{camera_id}"
        data = {
            "lcdMessage": {
                "type": message_type,
                "text": custom_text,
                "resetAt": duration,
            }
        }

        async with self.req.patch(
            cam_uri, headers=self.headers, ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                return True
            raise NvrError(
                "Setting Doorbell Custom Text failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def set_doorbell_standard_text(self, custom_text: str) -> bool:
        """Sets a Standard Text string for the Doorbell LCD. *** DOES NOT WORK ***"""

        await self.ensure_authenticated()

        message_type = "LEAVE_PACKAGE_AT_DOOR"

        # resetAt is Unix timestam in the future
        cam_uri = f"{self._base_url}/{self.api_path}/nvr"
        data = {
            "doorbellSettings": {
                "allMessages": {"type": message_type, "text": custom_text}
            }
        }

        async with self.req.patch(
            cam_uri, headers=self.headers, ssl=self._verify_ssl, json=data
        ) as response:
            if response.status == 200:
                return True
            raise NvrError(
                "Setting Doorbell Custom Text failed: %s - Reason: %s"
                % (response.status, response.reason)
            )

    async def request(self, method, url, json=None, **kwargs):
        """Make a request to the API."""

        _LOGGER.debug("Request url: %s", url)

        try:
            async with self.req.request(
                method,
                url,
                ssl=self._verify_ssl,
                json=json,
                headers=self.headers,
                **kwargs,
            ) as res:
                _LOGGER.debug("%s %s %s", res.status, res.content_type, res)

                if res.status in (401, 403):
                    raise NotAuthorized(
                        f"Unifi Protect reported authorization failure on request: {url} received {res.status}"
                    )

                if res.status == 404:
                    raise NvrError(f"Call {url} received 404 Not Found")

                return res

        except client_exceptions.ClientError as err:
            raise NvrError(f"Error requesting data from {self._host}: {err}") from None

    async def _setup_websocket(self):
        await self.ensure_authenticated()
        ip_address = self._base_url.split("://")
        url = f"wss://{ip_address[1]}/{self.ws_path}/updates"
        if self.last_update_id:
            url += f"?lastUpdateId={self.last_update_id}"
        if not self.ws_session:
            self.ws_session = aiohttp.ClientSession()
        _LOGGER.debug("WS connecting to: %s", url)

        self.ws_connection = await self.ws_session.ws_connect(
            url, ssl=self._verify_ssl, headers=self.headers
        )
        try:
            async for msg in self.ws_connection:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    try:
                        self._process_ws_message(msg)
                    except Exception:  # pylint: disable=broad-except
                        _LOGGER.exception("Error processing websocket message")
                        return
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
        finally:
            _LOGGER.debug("websocket disconnected")
            self.ws_connection = None

    def subscribe_websocket(self, ws_callback):
        """Subscribe to websocket events.

        Returns a callback that will unsubscribe.
        """

        def _unsub_ws_callback():
            self._ws_subscriptions.remove(ws_callback)

        _LOGGER.debug("Adding subscription: %s", ws_callback)
        self._ws_subscriptions.append(ws_callback)
        return _unsub_ws_callback

    def _process_ws_message(self, msg):
        """Process websocket messages."""
        action_frame, action_frame_payload_format, position = decode_ws_frame(
            msg.data, 0
        )

        if action_frame_payload_format != ProtectWSPayloadFormat.JSON:
            return

        action_json = pjson.loads(action_frame)

        if action_json.get("action") not in (
            "add",
            "update",
        ):
            return

        model_key = action_json.get("modelKey")

        if model_key not in ("event", "camera", "light"):
            return

        _LOGGER.debug("Action Frame: %s", action_json)

        data_frame, data_frame_payload_format, _ = decode_ws_frame(msg.data, position)

        if data_frame_payload_format != ProtectWSPayloadFormat.JSON:
            return

        data_json = pjson.loads(data_frame)
        _LOGGER.debug("Data Frame: %s", data_json)

        if model_key == "event":
            self._process_event_ws_message(action_json, data_json)
            return

        if model_key == "camera":
            self._process_camera_ws_message(action_json, data_json)
            return

        if model_key == "light":
            self._process_light_ws_message(action_json, data_json)
            return
        raise ValueError(f"Unexpected model key: {model_key}")

    def _process_camera_ws_message(self, action_json, data_json):
        """Process a decoded camera websocket message."""
        camera_id, processed_camera = camera_update_from_ws_frames(
            self._device_state_machine, self._host, action_json, data_json
        )

        if camera_id is None:
            return
        _LOGGER.debug("Processed camera: %s", processed_camera)

        if processed_camera["recording_mode"] == TYPE_RECORD_NEVER:
            processed_event = camera_event_from_ws_frames(
                self._device_state_machine, action_json, data_json
            )
            if processed_event is not None:
                _LOGGER.debug("Processed camera event: %s", processed_event)
                processed_camera.update(processed_event)

        self.fire_event(camera_id, processed_camera)

    def _process_light_ws_message(self, action_json, data_json):
        """Process a decoded light websocket message."""
        light_id, processed_light = light_update_from_ws_frames(
            self._device_state_machine, action_json, data_json
        )

        if light_id is None:
            return
        _LOGGER.debug(
            "Processed light: %s %s", processed_light["motion_mode"], processed_light
        )

        # Lights behave differently than Cameras so no check for recording state
        processed_event = light_event_from_ws_frames(
            self._device_state_machine, action_json, data_json
        )
        if processed_event is not None:
            _LOGGER.debug("Processed light event: %s", processed_event)
            processed_light.update(processed_event)

        self.fire_event(light_id, processed_light)

    def _process_event_ws_message(self, action_json, data_json):
        """Process a decoded event websocket message."""
        device_id, processed_event = event_from_ws_frames(
            self._event_state_machine, self._minimum_score, action_json, data_json
        )

        if device_id is None:
            return

        _LOGGER.debug("Procesed event: %s", processed_event)

        self.fire_event(device_id, processed_event)

        if processed_event["event_ring_on"]:
            # The websocket will not send any more events since
            # doorbell rings do not have a length. We fire an
            # additional event to turn off the ring.
            processed_event["event_ring_on"] = False
            self.fire_event(device_id, processed_event)

    def fire_event(self, device_id, processed_event):
        """Callback and event to the subscribers and update data."""
        self._update_device(device_id, processed_event)

        for subscriber in self._ws_subscriptions:
            subscriber({device_id: self._processed_data[device_id]})

    def _update_device(self, device_id, processed_update):
        """Update internal state of a device."""
        self._processed_data.setdefault(device_id, {}).update(processed_update)
