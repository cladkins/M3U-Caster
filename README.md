# M3U Caster for Home Assistant

Cast live channels from any Xtream-compatible IPTV server (any provider exposing a `player_api.php` endpoint) to Roku, Apple TV, and Chromecast from a Home Assistant dashboard, with EPG now/next in the picker.

## Install

HACS > Integrations > three dots > Custom repositories > add this repo as Integration. Install, restart Home Assistant.

Settings > Devices & Services > Add Integration > M3U Caster. Enter the server URL, username, and password. On some panels the password field is actually a playlist ID. Add the integration once per playlist.

The dashboard card registers itself. Edit a dashboard > Add card > M3U Caster TV Card.

## Card options

TV: any media_player entity.
Cast type: Auto detect, Roku, Apple TV (AirPlay), Apple TV app (VLC), Chromecast, Generic.
App link template: for Apple TV app. `{url}` is replaced with the stream URL. Default launches VLC.
Auto confirm: presses Select on the tvOS "Open in app?" prompt.

## Notes

Recent tvOS versions refuse AirPlay URL playback from Home Assistant. Auto detect therefore uses the app path for Apple TVs. Install VLC on the Apple TV, or set another player's URL scheme in the template.
Roku casting talks to the device's ECP API directly (`http://<roku-ip>:8060/input`), reusing the IP Home Assistant's own Roku integration already has on file. Home Assistant's built-in `media_player.play_media` path for Roku throws on some firmware even though the device accepts the command, so we bypass it rather than route through it.

## Services

`m3u_caster.play_stream`, `m3u_caster.stop`, `m3u_caster.sync_playlist`, `m3u_caster.refresh`.
