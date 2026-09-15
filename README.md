# M3U Editor for Home Assistant

Cast live channels from an Xtream-compatible IPTV server (m3u editor, or any provider with `player_api.php`) to Roku, Apple TV, and Chromecast from a Home Assistant dashboard, with EPG now/next in the picker.

## Install

HACS > Integrations > three dots > Custom repositories > add this repo as Integration. Install, restart Home Assistant.

Settings > Devices & Services > Add Integration > M3U Editor. Enter the server URL, username, and password. In m3u editor the password is the playlist UUID. Add the integration once per playlist.

The dashboard card registers itself. Edit a dashboard > Add card > M3U Editor TV Card.

## Card options

TV: any media_player entity.
Cast type: Auto detect, Roku, Apple TV (AirPlay), Apple TV app (VLC), Chromecast, Generic.
App link template: for Apple TV app. `{url}` is replaced with the stream URL. Default launches VLC.
Auto confirm: presses Select on the tvOS "Open in app?" prompt.

## Notes

Recent tvOS versions refuse AirPlay URL playback from Home Assistant. Auto detect therefore uses the app path for Apple TVs. Install VLC on the Apple TV, or set another player's URL scheme in the template.
Roku uses the built-in Roku Media Player channel.

## Services

`m3u_editor.play_stream`, `m3u_editor.stop`, `m3u_editor.sync_playlist`, `m3u_editor.refresh`.
