# M3U Caster for Home Assistant

Cast live channels from any Xtream-compatible IPTV server (any provider exposing a `player_api.php` endpoint) to Roku, Apple TV, and Chromecast from a Home Assistant dashboard, with EPG now/next in the picker. A per-TV channel player entity brings the same channels to remote-first cards such as RosCard on the Astrion remote.

## Install

HACS > Integrations > three dots > Custom repositories > add this repo as Integration. Install, restart Home Assistant. Updates are published as GitHub releases and appear in Settings > Updates like any other integration.

Settings > Devices & Services > Add Integration > M3U Caster. Enter the server URL, username, and password. On some panels the password field is actually a playlist ID. Add the integration once per playlist.

The dashboard card registers itself. Edit a dashboard > Add card > M3U Caster TV Card. After an update that changes the card, hard refresh the browser once.

Upgrading from the pre-HACS install (domain `m3u_editor`): remove that integration entry, delete `/config/custom_components/m3u_editor`, and remove its `/local/m3u_editor/...` dashboard resource before installing this one. The domain changed, so the old entry does not carry over.

## Card options

TV: any media_player entity.
Cast type: Auto detect, Roku, Apple TV (AirPlay), Apple TV app (VLC), Chromecast, Generic. Auto detect picks Roku for Roku players, the app path for Apple TVs, Chromecast for cast players, and Generic otherwise.
App link template: for Apple TV app. `{url}` is replaced with the stream URL. Default launches VLC.
Auto confirm: presses Select on the tvOS "Open in app?" prompt.
Card title and channel logo toggle.

The picker lists each channel with its current programme and start time, and groups channels by category when a playlist has more than one. The On TV strip shows what the player is doing. On Roku it names the channel the integration last cast there, since the Roku integration exposes no title while Stream Tester plays.

## Device notes

Apple TV: recent tvOS versions refuse AirPlay URL playback from Home Assistant, so Auto detect uses the app path. Install VLC on the Apple TV, or set another player's URL scheme in the template. Stop presses Select then Home. Home alone leaves VLC playing in the background.

Roku: casting deep-links the stream into the Roku Stream Tester channel over the device's ECP API (`http://<roku-ip>:8060/launch/<app_id>`), reusing the IP Home Assistant's Roku integration already has on file. Stream Tester must be installed on the Roku (free, Channel Store). Home Assistant's built-in `media_player.play_media` path for Roku throws on current firmware even though the device accepts commands, so the integration bypasses it. Stop presses Home.

Connections: most IPTV accounts allow one stream at a time. Casting to a second TV from the same playlist usually ends the first.

## QuadStream multiview (Apple TV)

QuadStream plays four streams in a grid on an Apple TV and reads its sources from a stream set on quadstream.tv. One-time setup: create a private stream set at https://quadstream.tv/stream/ (username and secret). Its page lists four addresses, https://quadstream.tv/stream/<set id>/1 through /4. In the QuadStream app on the Apple TV, set each quadrant's source to its own address: quadrant 1 to /1, quadrant 2 to /2, and so on. A quadrant pointed anywhere else ignores the set, so only quadrants set this way follow your casts. Then open the integration's options in Home Assistant and enter the QuadStream username and secret.

Add card > M3U Caster QuadStream Card: pick the Apple TV and playlist, choose up to four channels, press Cast to QuadStream. The integration writes the four stream URLs into the set, presses Home, and relaunches QuadStream so it loads the new sources. Stop presses Home. Slots you leave empty are sent blank; in testing the dashboard kept their previous URL, so clear a slot on quadstream.tv if you need it gone. The same action is available as `m3u_caster.play_multiview` with `stream_ids` (one to four) and an optional `media_player`.

Two things to know. QuadStream's own dashboard states that private sets are readable by anyone who knows the set id and that the secret only restricts editing; the Apple TV fetches the set without logging in, and the stream URLs include the playlist credentials, exactly as they do when you fill in the dashboard by hand. And four streams from one playlist means four sessions on that account, which must allow that many.

## Channel player and the Astrion remote

The Astrion remote renders only the ROS card types from RosCard, and those cards drive plain Home Assistant entities: the TV(ROS) and Media Player(ROS) cards show a media player's source list and pick from it. So instead of a card of its own, the integration gives each TV you choose a media_player entity whose sources are the playlist's channels.

Setup: Settings > Devices & Services > M3U Caster > Configure. Under "TVs to add a channel player for", pick the TV's media_player (the Apple TV or Roku entity you already cast to). Optionally limit "Channel groups" so a long playlist stays short on the remote's screen. Save, and a `media_player.m3u_caster_<playlist>_<tv>` entity appears on the playlist's device.

On the Astrion dashboard, add one Media Player(ROS) card and give it that entity, or set your existing TV(ROS) card's `source` to it. The remote then lists the channels as sources. Picking one casts it to the TV over the same path as the dashboard card. Stop ends the stream the same way the card's Stop does. Power off puts the TV to sleep. Play, pause, and volume pass through to the TV when it supports them.

State mirrors the TV: off or standby when the TV is, playing while a cast is showing, idle otherwise. While a cast is showing, the media title is the current programme and the channel logo is the artwork, so the Media Player(ROS) card's metadata line shows what is on. Attributes: `target`, `playlist`, and while playing `stream_id`, `group`, `now_start`, `now_end`, `next`, `next_start`.

Source names are channel names. Two channels with the same name get their stream id appended, `CNN [1234]`, so each source stays unique. `media_player.select_source` accepts the exact source or, when unambiguous, the bare channel name.

## Services

`m3u_caster.play_stream`: `stream_id`, `media_player`, optional `cast_type`, `app_link`, `auto_confirm`.
`m3u_caster.play_multiview`: `stream_ids` (one to four, in quadrant order, empty entries skip a slot), optional `media_player` to relaunch QuadStream on.
`m3u_caster.stop`: `media_player`, optional `cast_type`. `cast_type: home` presses Home only, which is what the QuadStream card uses.
`m3u_caster.sync_playlist`: re-sync a playlist on the panel, optional `playlist_uuid`. Requires an API token.
`m3u_caster.refresh`: re-poll channels and EPG now.

## Guide sensor

One `sensor.m3u_caster_<playlist>_guide` per playlist. State is the channel count. Attributes: `playlist`, `channels` (stream_id, name, group, logo, label, now, now_start, now_end, next, next_start), and `now_casting` (media_player entity id to the stream_id last cast there). Useful for automations. Casts made through a channel player show up here too, and casts made from the cards show up on the channel player.
