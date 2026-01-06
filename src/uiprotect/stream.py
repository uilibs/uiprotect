"""Audio streaming utilities for UniFi Protect cameras using PyAV."""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple, cast
from urllib.parse import ParseResult, urlparse

import av
from av.audio import AudioStream

from .exceptions import BadRequest, StreamError
from .utils import format_host_for_url

if TYPE_CHECKING:
    from .data import Camera


def _convert_av_errors(
    func: Callable[[TalkbackStream], None],
) -> Callable[[TalkbackStream], None]:
    """Decorator to convert av.FFmpegError to StreamError on self._error."""

    @functools.wraps(func)
    def wrapper(self: TalkbackStream) -> None:
        try:
            func(self)
        except av.FFmpegError as e:
            self._error = StreamError(f"Audio streaming failed: {e}")

    return wrapper


_LOGGER = logging.getLogger(__name__)

#: Default UDP port for talkback streaming.
DEFAULT_TALKBACK_PORT = 7004

#: Input timeout (open, read) in seconds.
INPUT_TIMEOUT = 5.0

#: Output timeout (open) in seconds. None = no read timeout for UDP.
OUTPUT_TIMEOUT: tuple[float, float | None] = (5.0, None)


class CodecConfig(NamedTuple):
    """
    Audio codec configuration for talkback streaming.

    Attributes:
        encoder: PyAV/libav encoder name (e.g., "aac", "libopus").
        format: Output container format (e.g., "adts", "rtp").

    """

    encoder: str
    format: str


#: Supported audio codecs for talkback. Maps codec name to encoder/format config.
CODEC_MAP: dict[str, CodecConfig] = {
    "aac": CodecConfig("aac", "adts"),
    "opus": CodecConfig("libopus", "rtp"),
    "vorbis": CodecConfig("libvorbis", "ogg"),
}


@dataclass(slots=True)
class TalkbackSession:
    """
    Talkback session configuration from the UniFi Protect public API.

    Attributes:
        url: Streaming URL (UDP or RTP, e.g., "rtp://192.168.1.1:7004").
        codec: Audio codec name ("aac", "opus", or "vorbis").
        sampling_rate: Audio sampling rate in Hz.

    """

    url: str
    codec: str
    sampling_rate: int
    bits_per_sample: int = 16
    _parsed_url: ParseResult = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Parse URL on initialization."""
        self._parsed_url = urlparse(self.url)

    @classmethod
    def from_unifi_dict(cls, **data: object) -> TalkbackSession:
        """
        Create from UniFi API response.

        Args:
            **data: Raw API response fields (url, codec, samplingRate).

        Returns:
            Configured TalkbackSession instance.

        """
        return cls(
            url=str(data.get("url", "")),
            codec=str(data.get("codec", "")),
            sampling_rate=int(cast(Any, data.get("samplingRate", 0))),
            bits_per_sample=int(cast(Any, data.get("bitsPerSample", 16))),
        )

    @property
    def host(self) -> str:
        """Get hostname from talkback URL."""
        return self._parsed_url.hostname or ""

    @property
    def port(self) -> int:
        """Get port from talkback URL, defaults to 7004."""
        return self._parsed_url.port or DEFAULT_TALKBACK_PORT


class TalkbackStream:
    """
    Stream audio to a UniFi Protect camera's speaker using PyAV.

    This class handles audio transcoding and UDP streaming to camera speakers.
    It runs the actual streaming in a separate thread to avoid blocking the event loop.

    Example:
        ```python
        stream = TalkbackStream(camera, "/path/to/audio.wav", session)
        await stream.run_until_complete()
        ```

    """

    __slots__ = (
        "_error",
        "_lock",
        "_stop_event",
        "_thread",
        "camera",
        "content_url",
        "session",
    )

    def __init__(
        self,
        camera: Camera,
        content_url: str,
        session: TalkbackSession | None = None,
    ) -> None:
        """
        Initialize talkback stream.

        Args:
            camera: Camera device to stream audio to.
            content_url: URL or file path of audio source.
            session: Optional talkback session from public API.

        Raises:
            BadRequest: If camera does not have a speaker.

        """
        if not camera.feature_flags.has_speaker:
            raise BadRequest("Camera does not have a speaker for talkback")

        self.camera = camera
        self.content_url = content_url
        self.session = session
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = asyncio.Lock()
        self._error: BaseException | None = None

    async def __aenter__(self) -> TalkbackStream:
        """Start streaming when entering async context."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Stop streaming when exiting async context."""
        await self.stop()

    @property
    def is_running(self) -> bool:
        """Check if the stream is currently running."""
        return self._thread is not None and self._thread.is_alive()

    @_convert_av_errors
    def _stream_audio_sync(self) -> None:
        """Stream audio to the camera (runs in executor thread)."""
        if self.session:
            output_url = self.session.url
            codec = self.session.codec
            sample_rate = self.session.sampling_rate
            bits_per_sample = self.session.bits_per_sample
        else:
            ts = self.camera.talkback_settings
            host = format_host_for_url(str(self.camera.host))
            output_url = f"udp://{host}:{ts.bind_port}"
            codec = ts.type_fmt.value
            sample_rate = ts.sampling_rate
            bits_per_sample = ts.bits_per_sample

        config = CODEC_MAP.get(codec)
        if not config:
            self._error = StreamError(f"Unsupported codec: {codec}")
            return

        _LOGGER.debug(
            "Talkback: %s codec=%s rate=%d bits=%d",
            output_url,
            codec,
            sample_rate,
            bits_per_sample,
        )

        with av.open(
            self.content_url,
            timeout=(INPUT_TIMEOUT, INPUT_TIMEOUT),
        ) as input_container:
            if not input_container.streams.audio:
                self._error = StreamError("No audio stream found in input")
                return

            input_stream = input_container.streams.audio[0]

            with av.open(
                output_url,
                "w",
                format=config.format,
                timeout=OUTPUT_TIMEOUT,
            ) as output_container:
                output_stream = cast(
                    AudioStream,
                    output_container.add_stream(config.encoder, rate=sample_rate),
                )
                output_stream.layout = "mono"

                # Map bits_per_sample to av format (8->u8, 16->s16, 32->s32)
                audio_format = {8: "u8", 16: "s16", 32: "s32"}.get(
                    bits_per_sample, "s16"
                )
                resampler = av.AudioResampler(
                    format=audio_format, layout="mono", rate=sample_rate
                )

                # Real-time pacing implementation:
                #
                # Unlike FFmpeg subprocess which handles timing internally, PyAV
                # returns encoded packets as fast as the CPU can process them.
                # Without pacing, we'd flood the camera's UDP buffer causing
                # garbled audio or dropped packets (UDP has no flow control).
                #
                # We use absolute time reference (start_time + samples/rate) rather
                # than relative delays to prevent cumulative drift from processing
                # overhead. The stop_event.wait(timeout) provides both the delay
                # and immediate cancellation when stop() is called.
                start_time = time.monotonic()
                samples_sent = 0

                for frame in input_container.decode(input_stream):
                    if self._stop_event.is_set():
                        break
                    for resampled in resampler.resample(frame):
                        for packet in output_stream.encode(resampled):
                            output_container.mux(packet)

                        # Calculate how long we should have taken vs actual elapsed
                        samples_sent += resampled.samples
                        target_time = start_time + (samples_sent / sample_rate)
                        sleep_time = target_time - time.monotonic()
                        if sleep_time > 0 and self._stop_event.wait(sleep_time):
                            break  # Stop requested during pacing delay

                # Flush encoder only if completed normally
                if not self._stop_event.is_set():
                    for packet in output_stream.encode(None):
                        output_container.mux(packet)

    def _start_thread_if_needed(self, *, raise_if_running: bool) -> None:
        """Start streaming thread if not already running. Must hold lock."""
        if self._thread is not None and self._thread.is_alive():
            if raise_if_running:
                raise StreamError("Stream already started")
            return
        self._stop_event.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._stream_audio_sync,
            name="TalkbackStream",
            daemon=True,
        )
        self._thread.start()

    async def _wait_for_thread(self) -> None:
        """Wait for the thread to complete without blocking the event loop."""
        if self._thread is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._thread.join)

    async def start(self) -> None:
        """Start the audio stream."""
        async with self._lock:
            self._start_thread_if_needed(raise_if_running=True)

    async def stop(self) -> None:
        """Stop the audio stream gracefully and wait for completion."""
        async with self._lock:
            self._stop_event.set()
            if self._thread is not None:
                await self._wait_for_thread()
                self._thread = None

    async def run_until_complete(self) -> None:
        """Run the stream until it completes naturally."""
        async with self._lock:
            self._start_thread_if_needed(raise_if_running=False)
            await self._wait_for_thread()

            if self._error is not None:
                error = self._error
                self._error = None
                if isinstance(error, BaseException):
                    raise error
                raise StreamError(f"Unexpected error: {error}")
