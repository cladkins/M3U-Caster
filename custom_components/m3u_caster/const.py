"""Constants for M3U Caster."""
from typing import Final

DOMAIN: Final = "m3u_caster"

CONF_BASE_URL: Final = "base_url"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_API_TOKEN: Final = "api_token"
CONF_PLAYLIST: Final = "playlist"
CONF_PLAYLIST_NAME: Final = "playlist_name"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_EPG_LIMIT: Final = "epg_limit"

DEFAULT_BASE_URL: Final = ""
DEFAULT_USERNAME: Final = ""
DEFAULT_SCAN_INTERVAL: Final = 300
DEFAULT_EPG_LIMIT: Final = 2

CAST_TYPES: Final = ["auto", "roku", "apple_tv", "apple_tv_app", "cast", "generic", "home"]
DEFAULT_APP_LINK: Final = "vlc-x-callback://x-callback-url/stream?url={url}"
DATA_NOW_CASTING: Final = f"{DOMAIN}_now_casting"

SERVICE_PLAY_STREAM: Final = "play_stream"
SERVICE_STOP: Final = "stop"
SERVICE_SYNC_PLAYLIST: Final = "sync_playlist"
SERVICE_REFRESH: Final = "refresh"

ATTR_STREAM_ID: Final = "stream_id"
ATTR_MEDIA_PLAYER: Final = "media_player"
ATTR_CAST_TYPE: Final = "cast_type"
ATTR_APP_LINK: Final = "app_link"
ATTR_AUTO_CONFIRM: Final = "auto_confirm"
ATTR_PLAYLIST_UUID: Final = "playlist_uuid"
ATTR_STREAM_IDS: Final = "stream_ids"

CONF_QUADSTREAM_USERNAME: Final = "quadstream_username"
CONF_QUADSTREAM_SECRET: Final = "quadstream_secret"
QUADSTREAM_APP_NAME: Final = "QuadStream"
SERVICE_PLAY_MULTIVIEW: Final = "play_multiview"
