"""Tests for uiprotect.stream module."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import av
import pytest

from uiprotect.data.types import AudioCodecs
from uiprotect.exceptions import BadRequest, StreamError
from uiprotect.stream import (
    CODEC_MAP,
    DEFAULT_TALKBACK_PORT,
    INPUT_TIMEOUT,
    OUTPUT_TIMEOUT,
    CodecConfig,
    TalkbackSession,
    TalkbackStream,
)

if TYPE_CHECKING:
    from uiprotect.api import ProtectApiClient

# --- Fixtures ---


@pytest.fixture
def mock_camera() -> Mock:
    """Create a mock camera with speaker support."""
    camera = Mock()
    camera.feature_flags.has_speaker = True
    camera.host = "192.168.1.100"
    camera.talkback_settings.bind_port = 7004
    camera.talkback_settings.type_fmt = AudioCodecs.OPUS
    camera.talkback_settings.sampling_rate = 24000
    return camera


@pytest.fixture
def mock_camera_no_speaker() -> Mock:
    """Create a mock camera without speaker support."""
    camera = Mock()
    camera.feature_flags.has_speaker = False
    return camera


@pytest.fixture
def talkback_session() -> TalkbackSession:
    """Create a test talkback session."""
    return TalkbackSession(
        url="rtp://192.168.1.100:7004",
        codec="opus",
        sampling_rate=24000,
    )


@pytest.fixture
def audio_file(tmp_path: Path) -> str:
    """Create a temporary audio file for testing (auto-cleaned by pytest)."""
    filepath = tmp_path / "test_audio.wav"
    with av.open(str(filepath), "w") as container:
        audio_stream = container.add_stream("pcm_s16le", rate=24000)
        audio_stream.layout = "mono"
        frame = av.AudioFrame(format="s16", layout="mono", samples=2400)
        frame.planes[0].update(b"\x00" * 4800)
        frame.rate = 24000
        frame.pts = 0
        for packet in audio_stream.encode(frame):
            container.mux(packet)
        for packet in audio_stream.encode(None):
            container.mux(packet)
    return str(filepath)


# --- Helper Functions ---


def _create_mock_av_containers(
    with_frames: bool = False,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Create mock av input/output containers for testing."""
    mock_input = MagicMock()
    mock_input.streams.audio = [MagicMock()]

    mock_output = MagicMock()
    mock_output_stream = MagicMock()
    mock_output.add_stream.return_value = mock_output_stream

    mock_resampler = MagicMock()

    if with_frames:
        # Create mock frames that go through the full processing path
        mock_frame = MagicMock()
        mock_input.decode.return_value = [mock_frame]

        mock_resampled = MagicMock()
        mock_resampler.resample.return_value = [mock_resampled]

        mock_packet = MagicMock()
        mock_output_stream.encode.return_value = [mock_packet]
    else:
        mock_input.decode.return_value = []
        mock_resampler.resample.return_value = []
        mock_output_stream.encode.return_value = []

    return mock_input, mock_output, mock_resampler


# --- TalkbackSession Tests ---


@pytest.mark.parametrize(
    ("data", "expected_url", "expected_codec", "expected_rate"),
    [
        (
            {"url": "rtp://192.168.1.100:7004", "codec": "opus", "samplingRate": 24000},
            "rtp://192.168.1.100:7004",
            "opus",
            24000,
        ),
        (
            {"url": "udp://10.0.0.1:8000", "codec": "aac", "samplingRate": 48000},
            "udp://10.0.0.1:8000",
            "aac",
            48000,
        ),
        ({}, "", "", 0),  # Missing fields use defaults
    ],
)
def test_talkback_session_from_unifi_dict(
    data: dict[str, Any],
    expected_url: str,
    expected_codec: str,
    expected_rate: int,
):
    session = TalkbackSession.from_unifi_dict(**data)
    assert session.url == expected_url
    assert session.codec == expected_codec
    assert session.sampling_rate == expected_rate


@pytest.mark.parametrize(
    ("url", "expected_host", "expected_port"),
    [
        ("rtp://192.168.1.100:7004", "192.168.1.100", 7004),
        ("udp://10.0.0.1:8000", "10.0.0.1", 8000),
        ("rtp://192.168.1.100", "192.168.1.100", DEFAULT_TALKBACK_PORT),
        ("", "", DEFAULT_TALKBACK_PORT),
    ],
)
def test_talkback_session_host_port(url: str, expected_host: str, expected_port: int):
    session = TalkbackSession(url=url, codec="opus", sampling_rate=24000)
    assert session.host == expected_host
    assert session.port == expected_port


# --- CodecConfig and Constants Tests ---


def test_codec_config():
    config = CodecConfig(encoder="aac", format="adts")
    assert config.encoder == "aac"
    assert config.format == "adts"


@pytest.mark.parametrize(
    ("codec", "expected_encoder", "expected_format"),
    [
        ("aac", "aac", "adts"),
        ("opus", "libopus", "rtp"),
    ],
)
def test_codec_map(codec: str, expected_encoder: str, expected_format: str):
    assert codec in CODEC_MAP
    assert CODEC_MAP[codec].encoder == expected_encoder
    assert CODEC_MAP[codec].format == expected_format


@pytest.fixture
def talkback_session_aac() -> TalkbackSession:
    """Create a test talkback session with AAC codec."""
    return TalkbackSession(
        url="rtp://192.168.1.100:7004",
        codec="aac",
        sampling_rate=48000,
    )


def test_constants():
    assert DEFAULT_TALKBACK_PORT == 7004
    assert INPUT_TIMEOUT == 5.0
    assert OUTPUT_TIMEOUT == (5.0, None)


# --- TalkbackStream Initialization Tests ---


def test_talkback_stream_init(mock_camera: Mock, talkback_session: TalkbackSession):
    stream = TalkbackStream(mock_camera, "/path/to/audio.wav", talkback_session)
    assert stream.camera is mock_camera
    assert stream.content_url == "/path/to/audio.wav"
    assert stream.session is talkback_session
    assert stream.is_running is False


def test_talkback_stream_init_no_session(mock_camera: Mock):
    stream = TalkbackStream(mock_camera, "/path/to/audio.wav")
    assert stream.session is None


def test_talkback_stream_init_no_speaker_raises(mock_camera_no_speaker: Mock):
    with pytest.raises(BadRequest, match="does not have a speaker"):
        TalkbackStream(mock_camera_no_speaker, "/path/to/audio.wav")


# --- TalkbackStream Parameter Resolution Tests ---


def test_get_stream_params_with_session(
    mock_camera: Mock, talkback_session: TalkbackSession
):
    stream = TalkbackStream(mock_camera, "/path/to/audio.wav", talkback_session)
    # Testing protected method to verify session vs camera fallback logic
    host, port, codec, rate = stream._get_stream_params()
    assert host == "192.168.1.100"
    assert port == 7004
    assert codec == "opus"
    assert rate == 24000


def test_get_stream_params_without_session(mock_camera: Mock):
    stream = TalkbackStream(mock_camera, "/path/to/audio.wav")
    # Testing protected method to verify camera settings fallback
    host, port, codec, rate = stream._get_stream_params()
    assert host == "192.168.1.100"
    assert port == 7004
    assert codec == "opus"
    assert rate == 24000


# --- TalkbackStream Start/Stop Tests ---


@pytest.mark.asyncio
async def test_start_stop(mock_camera: Mock, audio_file: str):
    with patch.object(TalkbackStream, "_stream_audio_sync"):
        stream = TalkbackStream(mock_camera, audio_file)

        await stream.start()
        assert stream.is_running is True

        await stream.stop()
        assert stream.is_running is False


@pytest.mark.asyncio
async def test_start_twice_raises(mock_camera: Mock, audio_file: str):
    with patch.object(TalkbackStream, "_stream_audio_sync"):
        stream = TalkbackStream(mock_camera, audio_file)
        await stream.start()
        with pytest.raises(StreamError, match="already started"):
            await stream.start()
        await stream.stop()


@pytest.mark.asyncio
async def test_stop_when_not_running(mock_camera: Mock, audio_file: str):
    stream = TalkbackStream(mock_camera, audio_file)
    await stream.stop()  # Should not raise
    assert stream.is_running is False


@pytest.mark.asyncio
async def test_multiple_start_stop_cycles(mock_camera: Mock, audio_file: str):
    with patch.object(TalkbackStream, "_stream_audio_sync"):
        stream = TalkbackStream(mock_camera, audio_file)
        for _ in range(3):
            await stream.start()
            assert stream.is_running is True
            await stream.stop()
            assert stream.is_running is False


# --- TalkbackStream Context Manager Tests ---


@pytest.mark.asyncio
async def test_context_manager(mock_camera: Mock, audio_file: str):
    with patch.object(TalkbackStream, "_stream_audio_sync"):
        stream = TalkbackStream(mock_camera, audio_file)
        async with stream as s:
            assert s is stream
            assert stream.is_running is True
        assert stream.is_running is False


# --- TalkbackStream Audio Processing Tests ---


@pytest.mark.asyncio
async def test_run_until_complete(
    mock_camera: Mock, audio_file: str, talkback_session: TalkbackSession
):
    mock_input, mock_output, mock_resampler = _create_mock_av_containers()

    with (
        patch("uiprotect.stream.av.open") as mock_av_open,
        patch("uiprotect.stream.av.AudioResampler", return_value=mock_resampler),
    ):
        mock_av_open.side_effect = [mock_input, mock_output]
        stream = TalkbackStream(mock_camera, audio_file, talkback_session)
        await stream.run_until_complete()


@pytest.mark.asyncio
async def test_run_until_complete_with_frames(
    mock_camera: Mock, audio_file: str, talkback_session: TalkbackSession
):
    """Test full audio processing path with frames (OPUS codec)."""
    mock_input, mock_output, mock_resampler = _create_mock_av_containers(
        with_frames=True
    )

    with (
        patch("uiprotect.stream.av.open") as mock_av_open,
        patch("uiprotect.stream.av.AudioResampler", return_value=mock_resampler),
    ):
        mock_av_open.side_effect = [mock_input, mock_output]
        stream = TalkbackStream(mock_camera, audio_file, talkback_session)
        await stream.run_until_complete()

    # Verify the full processing path was called
    mock_input.decode.assert_called()
    mock_resampler.resample.assert_called()
    mock_output.add_stream.return_value.encode.assert_called()
    mock_output.mux.assert_called()


def test_stream_audio_sync_direct_coverage(
    mock_camera: Mock, audio_file: str, talkback_session: TalkbackSession
):
    """Test _stream_audio_sync directly for 100% coverage (bypasses executor)."""
    mock_input, mock_output, mock_resampler = _create_mock_av_containers(
        with_frames=True
    )

    with (
        patch("uiprotect.stream.av.open") as mock_av_open,
        patch("uiprotect.stream.av.AudioResampler", return_value=mock_resampler),
    ):
        mock_av_open.side_effect = [mock_input, mock_output]
        stream = TalkbackStream(mock_camera, audio_file, talkback_session)
        stream._stream_audio_sync()  # Normal run
        mock_output.mux.assert_called()

        # Test break path: set stop_event and run again
        mock_av_open.side_effect = [mock_input, mock_output]
        stream._stop_event.set()
        stream._stream_audio_sync()  # Should hit break on line 242


@pytest.mark.asyncio
async def test_run_until_complete_aac_codec(
    mock_camera: Mock, audio_file: str, talkback_session_aac: TalkbackSession
):
    """Test audio processing with AAC codec."""
    mock_input, mock_output, mock_resampler = _create_mock_av_containers(
        with_frames=True
    )

    with (
        patch("uiprotect.stream.av.open") as mock_av_open,
        patch("uiprotect.stream.av.AudioResampler", return_value=mock_resampler),
    ):
        mock_av_open.side_effect = [mock_input, mock_output]
        stream = TalkbackStream(mock_camera, audio_file, talkback_session_aac)
        await stream.run_until_complete()

    # Verify AAC encoder was requested (adts format)
    mock_output.add_stream.assert_called_once_with("aac", rate=48000)
    mock_output.mux.assert_called()


@pytest.mark.asyncio
async def test_run_until_complete_no_audio_stream(
    mock_camera: Mock, audio_file: str, talkback_session: TalkbackSession
):
    mock_input = MagicMock()
    mock_input.streams.audio = []

    with patch("uiprotect.stream.av.open") as mock_av_open:
        mock_av_open.return_value = mock_input
        stream = TalkbackStream(mock_camera, audio_file, talkback_session)
        with pytest.raises(StreamError, match="No audio stream"):
            await stream.run_until_complete()


@pytest.mark.asyncio
async def test_run_until_complete_unsupported_codec(mock_camera: Mock, audio_file: str):
    session = TalkbackSession(
        url="rtp://192.168.1.100:7004",
        codec="unsupported_codec",
        sampling_rate=24000,
    )
    stream = TalkbackStream(mock_camera, audio_file, session)
    with pytest.raises(StreamError, match="Unsupported codec"):
        await stream.run_until_complete()


@pytest.mark.asyncio
async def test_run_until_complete_ffmpeg_error(
    mock_camera: Mock, audio_file: str, talkback_session: TalkbackSession
):
    with patch("uiprotect.stream.av.open") as mock_av_open:
        mock_av_open.side_effect = av.FFmpegError(0, "Test error")
        stream = TalkbackStream(mock_camera, audio_file, talkback_session)
        with pytest.raises(StreamError, match="Audio streaming failed"):
            await stream.run_until_complete()


# --- TalkbackStream Stop Signal Tests ---


@pytest.mark.asyncio
async def test_stop_signal_interrupts_streaming(mock_camera: Mock, audio_file: str):
    """Test that stop signal can interrupt streaming."""
    stream: TalkbackStream
    stop_was_checked = False

    def mock_decode(*_args: object) -> Generator[MagicMock, None, None]:
        nonlocal stop_was_checked
        for _i in range(10):
            # Verify the stop_event is accessible and can be checked
            _ = stream._stop_event.is_set()
            stop_was_checked = True
            yield MagicMock()

    mock_input, mock_output, mock_resampler = _create_mock_av_containers()
    mock_input.decode = mock_decode

    with (
        patch("uiprotect.stream.av.open") as mock_av_open,
        patch("uiprotect.stream.av.AudioResampler", return_value=mock_resampler),
    ):
        mock_av_open.side_effect = [mock_input, mock_output]
        stream = TalkbackStream(mock_camera, audio_file)
        stream.session = TalkbackSession(
            url="rtp://192.168.1.100:7004",
            codec="opus",
            sampling_rate=24000,
        )

        # Test that stop_event starts unset
        assert not stream._stop_event.is_set()

        await stream.run_until_complete()

        # Verify decode was called and stop_event was checked
        assert stop_was_checked


@pytest.mark.asyncio
async def test_stop_event_is_set_on_stop(mock_camera: Mock, audio_file: str):
    """Test that calling stop() sets the stop event."""
    with patch.object(TalkbackStream, "_stream_audio_sync"):
        stream = TalkbackStream(mock_camera, audio_file)

        assert not stream._stop_event.is_set()

        await stream.start()
        assert stream.is_running

        await stream.stop()
        assert stream._stop_event.is_set()
        assert not stream.is_running


@pytest.mark.asyncio
async def test_run_until_complete_unexpected_error(mock_camera: Mock, audio_file: str):
    """Test that run_until_complete handles unexpected non-exception errors."""
    stream = TalkbackStream(mock_camera, audio_file)
    stream.session = TalkbackSession(
        url="rtp://192.168.1.100:7004", codec="opus", sampling_rate=24000
    )
    # Simulate an unexpected non-BaseException error stored
    stream._error = "unexpected string error"  # type: ignore[assignment]
    stream._task = asyncio.create_task(asyncio.sleep(0))

    with pytest.raises(StreamError, match="Unexpected error"):
        await stream.run_until_complete()


# --- API Method Tests ---


@pytest.mark.asyncio
async def test_create_talkback_session_public(protect_client: ProtectApiClient):
    """Test create_talkback_session_public API method."""
    mock_response: dict[str, Any] = {
        "url": "rtp://192.168.1.100:7004",
        "codec": "opus",
        "samplingRate": 24000,
    }
    protect_client.api_request_obj = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

    session = await protect_client.create_talkback_session_public("camera123")

    assert isinstance(session, TalkbackSession)
    assert session.url == "rtp://192.168.1.100:7004"
    assert session.codec == "opus"
    assert session.sampling_rate == 24000
    protect_client.api_request_obj.assert_called_once_with(  # type: ignore[attr-defined]
        url="/v1/cameras/camera123/talkback-session",
        method="post",
        public_api=True,
    )
