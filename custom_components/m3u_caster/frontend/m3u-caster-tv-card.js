/* m3u-caster-tv-card: pick a TV, a cast type, and a playlist in the card editor. */
const CAST_TYPES = [
  { value: "auto", label: "Auto detect" },
  { value: "roku", label: "Roku" },
  { value: "apple_tv", label: "Apple TV (AirPlay)" },
  { value: "apple_tv_app", label: "Apple TV app (VLC)" },
  { value: "cast", label: "Chromecast" },
  { value: "generic", label: "Generic" },
];
const castLabel = (v) => (CAST_TYPES.find((c) => c.value === v) || { label: v }).label;
const DEFAULT_APP_LINK = "vlc-x-callback://x-callback-url/stream?url={url}";
// Guide card timeline-grid layout: a fixed forward-looking window, not tied to how far the backend's
// programme data happens to reach, so the grid's width stays predictable across channels and groups.
const GRID_WINDOW_HOURS = 4;
const GRID_STEP_MIN = 30;
const GRID_PX_PER_MIN = 3;
const GRID_MIN_BLOCK_PX = 50;
const GRID_ROW_PX = 44;
const GRID_RULER_PX = 28;
// Channel names/labels come from the IPTV panel, not from us, so they're escaped everywhere they're
// interpolated into markup, attribute values and text content alike.
const ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC_MAP[c]);
const guideChannels = (hass, guide) => {
  const st = hass.states[guide];
  return st && Array.isArray(st.attributes.channels) ? st.attributes.channels : [];
};
// Channels with no group are shown as "Other"; they need a non-empty key so "" can mean "all groups".
const OTHER = "__other__";
const gkey = (g) => g || OTHER;
const gname = (g) => (g && g !== OTHER ? g : "Other");
const channelGroups = (channels) => [...new Set(channels.map((c) => gkey(c.group)))];
// `allowed` is the card's configured group list (empty = all); `current` is the in-card dropdown pick.
const filterChannels = (channels, allowed, current) => channels.filter((c) => {
  const g = gkey(c.group);
  return (!allowed || !allowed.length || allowed.includes(g)) && (!current || g === current);
});
const syncGroupPicker = (select, groups, current) => {
  const sig = groups.join("\n");
  if (select.dataset.sig !== sig) {
    select.innerHTML = [`<option value="">All groups</option>`]
      .concat(groups.map((g) => `<option value="${esc(g)}">${gname(g)}</option>`)).join("");
    select.dataset.sig = sig;
  }
  select.style.display = groups.length > 1 ? "" : "none";
  if (select.value !== (current || "")) select.value = current || "";
};
const groupSchema = (hass, guide) => ({
  name: "groups",
  selector: { select: { multiple: true, mode: "dropdown",
    options: channelGroups(guideChannels(hass, guide)).map((g) => ({ value: g, label: gname(g) })) } },
});
// What channel a target media_player is currently showing, if this integration is the one showing it.
// Shared by the TV card (via its own copy) and the guide card, which watches several targets at once.
const playingChannelFor = (hass, guideId, channels, targetId) => {
  const tv = hass.states[targetId];
  if (!tv || !["playing", "paused", "buffering"].includes(tv.state)) return null;
  const a = tv.attributes || {};
  const cid = a.media_content_id || "";
  const title = a.media_title || "";
  const matched = channels.find((c) => cid && (cid === c.url || cid === c.stream_id || cid.includes(c.url) || cid.includes(`/${c.stream_id}.m3u8`)))
    || channels.find((c) => title && title === c.name);
  if (matched) return matched;
  // Roku exposes no media id/title while Stream Tester plays; fall back to what we last cast there.
  const cast = ((hass.states[guideId] || {}).attributes?.now_casting || {})[targetId];
  if (!cast || (cast.app && cast.app !== a.app_name)) return null;
  return channels.find((c) => c.stream_id === cast.stream_id) || null;
};
// Rebuild a <select> only when the channel list itself changes: rewriting it on every state update closes an
// open menu and drops the pick. Selection is applied through .value, never baked into the HTML.
const syncPicker = (select, channels, selected, placeholder) => {
  const sig = placeholder + "\n" + channels.map((c) => `${c.stream_id}\t${c.group || ""}\t${c.label}`).join("\n");
  if (select.dataset.sig !== sig) {
    const opt = (c) => `<option value="${esc(c.stream_id)}">${esc(c.label)}</option>`;
    const groups = new Map();
    channels.forEach((c) => { const g = c.group || ""; if (!groups.has(g)) groups.set(g, []); groups.get(g).push(c); });
    select.innerHTML = [`<option value="">${placeholder}</option>`]
      .concat(groups.size > 1
        ? [...groups].map(([g, cs]) => `<optgroup label="${esc(g || "Other")}">${cs.map(opt).join("")}</optgroup>`)
        : channels.map(opt))
      .join("");
    select.dataset.sig = sig;
  }
  if (select.value !== (selected || "")) select.value = selected || "";
};

class M3uCasterTvCard extends HTMLElement {
  static getConfigElement() { return document.createElement("m3u-caster-tv-card-editor"); }
  static getStubConfig(hass) {
    const guide = Object.keys(hass.states).find((e) => e.startsWith("sensor.") && hass.states[e].attributes.channels);
    const tv = Object.keys(hass.states).find((e) => e.startsWith("media_player."));
    return { media_player: tv || "", guide: guide || "", cast_type: "auto", app_link: DEFAULT_APP_LINK, auto_confirm: true };
  }
  setConfig(config) {
    if (!config.media_player) throw new Error("media_player is required");
    if (!config.guide) throw new Error("guide sensor is required");
    this._config = { cast_type: "auto", show_logo: true, show_footer: true, app_link: DEFAULT_APP_LINK, auto_confirm: true, ...config };
    this._selected = this._selected || "";
    this._group = this._group || "";
  }
  set hass(hass) {
    this._hass = hass;
    this._render();
  }
  getCardSize() { return 4; }

  _fmt(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  _channels() { return guideChannels(this._hass, this._config.guide); }
  _visible() { return filterChannels(this._channels(), this._config.groups, this._group); }
  async _play() {
    if (!this._selected) return;
    const data = { stream_id: this._selected, media_player: this._config.media_player, cast_type: this._config.cast_type };
    if (this._config.cast_type === "apple_tv_app") {
      data.app_link = this._config.app_link || DEFAULT_APP_LINK;
      data.auto_confirm = this._config.auto_confirm !== false;
    }
    await this._hass.callService("m3u_caster", "play_stream", data);
  }
  async _stop() {
    await this._hass.callService("m3u_caster", "stop", { media_player: this._config.media_player, cast_type: this._config.cast_type });
  }
  _playingChannel(tv, channels) {
    if (!tv) return null;
    const a = tv.attributes || {};
    const cid = a.media_content_id || "";
    const title = a.media_title || "";
    const matched = channels.find((c) => cid && (cid === c.url || cid.includes(c.url) || cid.includes(`/${c.stream_id}.m3u8`)))
      || channels.find((c) => title && title === c.name);
    if (matched) return matched;
    // Roku exposes no media id/title while Stream Tester plays; fall back to what we last cast there.
    const cast = ((this._hass.states[this._config.guide] || {}).attributes?.now_casting || {})[this._config.media_player];
    if (!cast || (cast.app && cast.app !== a.app_name)) return null;
    return channels.find((c) => c.stream_id === cast.stream_id) || null;
  }
  _render() {
    if (!this._hass || !this._config) return;
    const tv = this._hass.states[this._config.media_player];
    const tvName = this._config.title || (tv ? tv.attributes.friendly_name : this._config.media_player);
    const all = this._channels();
    const groups = channelGroups(filterChannels(all, this._config.groups));
    const channels = this._visible();
    const playlist = (this._hass.states[this._config.guide] || {}).attributes?.playlist || "";
    const tvState = tv ? tv.state : "unavailable";
    const active = ["playing", "paused", "buffering"].includes(tvState);
    const onTv = active ? this._playingChannel(tv, all) : null;
    if (onTv && !this._selected && channels.includes(onTv)) this._selected = onTv.stream_id;
    const sel = all.find((c) => c.stream_id === this._selected) || null;
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.innerHTML = `
        <style>
          ha-card { padding: 12px 16px 16px; }
          .hdr { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }
          .hdr .name { font-size:1.1em; font-weight:500; }
          .hdr .state { font-size:.85em; opacity:.7; text-transform:capitalize; }
          .tv { font-size:.9em; margin-bottom:10px; padding:8px 10px; border-radius:8px; background:var(--secondary-background-color); }
          .tv.live { border-left:3px solid var(--primary-color); }
          .tv .l { font-size:.75em; opacity:.6; text-transform:uppercase; letter-spacing:.04em; }
          select { width:100%; padding:8px; border-radius:6px; border:1px solid var(--divider-color);
                   background:var(--card-background-color); color:var(--primary-text-color); font-size:.95em; }
          select.grp { margin-bottom:8px; font-size:.85em; }
          .now { display:flex; gap:12px; margin:10px 0; min-height:48px; align-items:center; }
          .now img { width:48px; height:48px; object-fit:contain; border-radius:6px; background:var(--secondary-background-color); }
          .now .t { font-weight:500; }
          .now .s { font-size:.85em; opacity:.75; }
          .btns { display:flex; gap:8px; }
          button { flex:1; padding:10px; border:0; border-radius:8px; font-size:.95em; cursor:pointer;
                   background:var(--primary-color); color:var(--text-primary-color); }
          button.stop { background:var(--secondary-background-color); color:var(--primary-text-color); }
          button:disabled { opacity:.4; cursor:default; }
          .pl { font-size:.75em; opacity:.6; margin-top:8px; }
        </style>
        <ha-card>
          <div class="hdr"><span class="name"></span><span class="state"></span></div>
          <div class="tv"><div class="l">On TV</div><div class="v"></div></div>
          <select class="grp"></select>
          <select class="ch"></select>
          <div class="now"><img/><div><div class="t"></div><div class="s"></div></div></div>
          <div class="btns"><button class="play">Cast</button><button class="stop">Stop</button></div>
          <div class="pl"></div>
        </ha-card>`;
      this._root.querySelector("select.grp").addEventListener("change", (e) => {
        this._group = e.target.value;
        if (!this._visible().some((c) => c.stream_id === this._selected)) this._selected = "";
        this._render();
      });
      this._root.querySelector("select.ch").addEventListener("change", (e) => { this._selected = e.target.value; this._render(); });
      this._root.querySelector("button.play").addEventListener("click", () => this._play());
      this._root.querySelector("button.stop").addEventListener("click", () => this._stop());
    }
    const r = this._root;
    r.querySelector(".name").textContent = tvName;
    r.querySelector(".state").textContent = tvState;
    const tvBox = r.querySelector(".tv");
    const a = (tv && tv.attributes) || {};
    const parts = [a.app_name, onTv ? onTv.name : a.media_title, a.media_artist].filter(Boolean);
    tvBox.classList.toggle("live", active);
    r.querySelector(".tv .v").textContent = active ? (parts.join("  ·  ") || tvState) : (tvState === "unavailable" ? "Not connected" : "Nothing playing");
    syncGroupPicker(r.querySelector("select.grp"), groups, this._group);
    syncPicker(r.querySelector("select.ch"), channels, this._selected, "Choose a game or channel");
    const img = r.querySelector(".now img");
    // visibility, not display: the image's box stays reserved either way, so toggling the logo
    // setting (or just not having one for this channel) never reflows the row next to it.
    img.style.visibility = this._config.show_logo && sel && sel.logo ? "visible" : "hidden";
    if (sel && sel.logo) img.src = sel.logo;
    r.querySelector(".now .t").textContent = sel ? (sel.now || sel.name) : "";
    r.querySelector(".now .s").textContent = sel
      ? [sel.name, sel.now_start ? `${this._fmt(sel.now_start)}–${this._fmt(sel.now_end)}` : "", sel.next ? `Next: ${sel.next} ${this._fmt(sel.next_start)}` : ""].filter(Boolean).join("  ·  ")
      : "";
    r.querySelector("button.play").disabled = !this._selected || tvState === "unavailable";
    r.querySelector("button.stop").disabled = tvState === "unavailable";
    r.querySelector(".pl").textContent = this._config.show_footer !== false && playlist
      ? `Playlist: ${playlist}  ·  Cast: ${castLabel(this._config.cast_type)}` : "";
  }
}

class M3uCasterTvCardEditor extends HTMLElement {
  setConfig(config) { this._config = { cast_type: "auto", show_logo: true, show_footer: true, ...config }; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  _render() {
    if (!this._hass) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => ({
        media_player: "TV / media player", cast_type: "Cast type", guide: "M3U Caster playlist (guide sensor)",
        groups: "Channel groups (empty = all)", title: "Card title (optional)", show_logo: "Show channel logo",
        show_footer: "Show playlist & cast info at the bottom",
        app_link: "App link template (apple_tv_app only, {url} = stream)", auto_confirm: "Auto press Select on the Open prompt",
      }[s.name] || s.name);
      this._form.addEventListener("value-changed", (e) => {
        this._config = e.detail.value;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    // hass can arrive before setConfig, so never assume the config is there yet.
    const cfg = this._config || {};
    const guides = Object.keys(this._hass.states).filter((e) => e.startsWith("sensor.") && this._hass.states[e].attributes.channels);
    this._form.hass = this._hass;
    this._form.data = cfg;
    this._form.schema = [
      { name: "media_player", required: true, selector: { entity: { domain: "media_player" } } },
      { name: "cast_type", selector: { select: { mode: "dropdown", options: CAST_TYPES } } },
      { name: "app_link", selector: { text: {} } },
      { name: "auto_confirm", selector: { boolean: {} } },
      { name: "guide", required: true, selector: { select: { mode: "dropdown", options: guides.map((e) => ({ value: e, label: `${this._hass.states[e].attributes.playlist || e}` })) } } },
      groupSchema(this._hass, cfg.guide),
      { name: "title", selector: { text: {} } },
      { name: "show_logo", selector: { boolean: {} } },
      { name: "show_footer", selector: { boolean: {} } },
    ];
  }
}

class M3uCasterQuadCard extends HTMLElement {
  static getConfigElement() { return document.createElement("m3u-caster-quad-card-editor"); }
  static getStubConfig(hass) {
    const guide = Object.keys(hass.states).find((e) => e.startsWith("sensor.") && hass.states[e].attributes.channels);
    const tv = Object.keys(hass.states).find((e) => e.startsWith("media_player."));
    return { media_player: tv || "", guide: guide || "" };
  }
  setConfig(config) {
    if (!config.media_player) throw new Error("media_player is required");
    if (!config.guide) throw new Error("guide sensor is required");
    this._config = { ...config };
    this._sel = this._sel || ["", "", "", ""];
    // One group pick per slot: a multiview is usually four games from four different groups.
    this._grp = this._grp || ["", "", "", ""];
  }
  set hass(hass) { this._hass = hass; this._render(); }
  getCardSize() { return 5; }
  _visible(i) { return filterChannels(guideChannels(this._hass, this._config.guide), this._config.groups, this._grp[i]); }
  async _cast() {
    if (!this._sel.some(Boolean)) return;
    // Positional: an empty entry keeps that quadrant's slot index, so slot 3 stays slot 3.
    const ids = this._sel.map((v) => v || "");
    await this._hass.callService("m3u_caster", "play_multiview", { stream_ids: ids, media_player: this._config.media_player });
  }
  async _stop() {
    await this._hass.callService("m3u_caster", "stop", { media_player: this._config.media_player, cast_type: "home" });
  }
  _render() {
    if (!this._hass || !this._config) return;
    const tv = this._hass.states[this._config.media_player];
    const tvName = this._config.title || (tv ? tv.attributes.friendly_name : this._config.media_player);
    const tvState = tv ? tv.state : "unavailable";
    const groups = channelGroups(filterChannels(guideChannels(this._hass, this._config.guide), this._config.groups));
    const playlist = (this._hass.states[this._config.guide] || {}).attributes?.playlist || "";
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.innerHTML = `
        <style>
          ha-card { padding: 12px 16px 16px; }
          .hdr { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
          .hdr .name { font-size:1.1em; font-weight:500; }
          .hdr .state { font-size:.85em; opacity:.7; text-transform:capitalize; }
          .grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }
          .slot { display:flex; flex-direction:column; gap:4px; min-width:0; }
          .slot .l { font-size:.7em; opacity:.6; text-transform:uppercase; letter-spacing:.04em; }
          select { width:100%; min-width:0; max-width:100%; padding:8px; border-radius:6px; border:1px solid var(--divider-color);
                   background:var(--card-background-color); color:var(--primary-text-color); font-size:.9em; }
          select.grp { font-size:.8em; padding:6px 8px; opacity:.85; }
          .btns { display:flex; gap:8px; }
          button { flex:1; padding:10px; border:0; border-radius:8px; font-size:.95em; cursor:pointer;
                   background:var(--primary-color); color:var(--text-primary-color); }
          button.stop { background:var(--secondary-background-color); color:var(--primary-text-color); }
          button:disabled { opacity:.4; cursor:default; }
          .pl { font-size:.75em; opacity:.6; margin-top:8px; }
        </style>
        <ha-card>
          <div class="hdr"><span class="name"></span><span class="state"></span></div>
          <div class="grid">
            ${[1, 2, 3, 4].map((n) => `<div class="slot"><span class="l">Stream ${n}</span>
              <select class="grp" data-grp="${n - 1}"></select><select data-slot="${n - 1}"></select></div>`).join("")}
          </div>
          <div class="btns"><button class="play">Cast to QuadStream</button><button class="stop">Stop</button></div>
          <div class="pl"></div>
        </ha-card>`;
      this._root.querySelectorAll("select[data-grp]").forEach((s) => s.addEventListener("change", (e) => {
        const i = Number(e.target.dataset.grp);
        this._grp[i] = e.target.value;
        if (!this._visible(i).some((c) => c.stream_id === this._sel[i])) this._sel[i] = "";
        this._render();
      }));
      this._root.querySelectorAll("select[data-slot]").forEach((s) => s.addEventListener("change", (e) => {
        this._sel[Number(e.target.dataset.slot)] = e.target.value; this._render();
      }));
      this._root.querySelector("button.play").addEventListener("click", () => this._cast());
      this._root.querySelector("button.stop").addEventListener("click", () => this._stop());
    }
    const r = this._root;
    r.querySelector(".name").textContent = tvName;
    r.querySelector(".state").textContent = tvState;
    r.querySelectorAll("select[data-grp]").forEach((s, i) => syncGroupPicker(s, groups, this._grp[i]));
    r.querySelectorAll("select[data-slot]").forEach((s, i) => syncPicker(s, this._visible(i), this._sel[i], `Stream ${i + 1}: none`));
    r.querySelector("button.play").disabled = !this._sel.some(Boolean) || tvState === "unavailable";
    r.querySelector("button.stop").disabled = tvState === "unavailable";
    r.querySelector(".pl").textContent = playlist ? `Playlist: ${playlist}  ·  QuadStream` : "";
  }
}

class M3uCasterQuadCardEditor extends HTMLElement {
  setConfig(config) { this._config = { ...config }; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  _render() {
    if (!this._hass) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => ({
        media_player: "Apple TV (media player)", guide: "M3U Caster playlist (guide sensor)",
        groups: "Channel groups (empty = all)", title: "Card title (optional)",
      }[s.name] || s.name);
      this._form.addEventListener("value-changed", (e) => {
        this._config = e.detail.value;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    const cfg = this._config || {};
    const guides = Object.keys(this._hass.states).filter((e) => e.startsWith("sensor.") && this._hass.states[e].attributes.channels);
    this._form.hass = this._hass;
    this._form.data = cfg;
    this._form.schema = [
      { name: "media_player", required: true, selector: { entity: { domain: "media_player" } } },
      { name: "guide", required: true, selector: { select: { mode: "dropdown", options: guides.map((e) => ({ value: e, label: `${this._hass.states[e].attributes.playlist || e}` })) } } },
      groupSchema(this._hass, cfg.guide),
      { name: "title", selector: { text: {} } },
    ];
  }
}

class M3uCasterGuideCard extends HTMLElement {
  static getConfigElement() { return document.createElement("m3u-caster-guide-card-editor"); }
  static getStubConfig(hass) {
    const guide = Object.keys(hass.states).find((e) => e.startsWith("sensor.") && hass.states[e].attributes.channels);
    const tv = Object.keys(hass.states).find((e) => e.startsWith("media_player.") && !hass.states[e].attributes.target);
    return { guide: guide || "", targets: tv ? [tv] : [], title: "", layout: "list", app_link: DEFAULT_APP_LINK, auto_confirm: true, target_cast_types: {} };
  }
  setConfig(config) {
    if (!config.guide) throw new Error("guide sensor is required");
    this._config = { targets: [], target_cast_types: {}, layout: "list", app_link: DEFAULT_APP_LINK, auto_confirm: true, ...config };
    this._group = this._group || "";
    this._picker = this._picker || null; // the channel the picker sheet is open for, or null when closed
  }
  // Each configured TV can pin its own cast type in the editor; "auto" (the default) detects it same as elsewhere.
  _castTypeFor(targetId) { return (this._config.target_cast_types || {})[targetId] || "auto"; }
  set hass(hass) { this._hass = hass; this._render(); }
  getCardSize() { return 8; }

  _channels() { return guideChannels(this._hass, this._config.guide); }
  _visible() { return filterChannels(this._channels(), this._config.groups, this._group); }
  _targets() { return (this._config.targets || []).filter(Boolean); }
  _targetName(id) {
    const st = this._hass.states[id];
    return (st && st.attributes.friendly_name) || id;
  }
  // stream_id -> names of configured TVs currently showing that channel, for the row badges.
  _targetsNowPlaying() {
    const channels = this._channels();
    const map = {};
    for (const id of this._targets()) {
      const ch = playingChannelFor(this._hass, this._config.guide, channels, id);
      if (ch) (map[ch.stream_id] = map[ch.stream_id] || []).push(this._targetName(id));
    }
    return map;
  }
  _openPicker(channel) { this._picker = channel; this._render(); }
  _closePicker() { this._picker = null; this._render(); }
  async _pick(targetId) {
    const ch = this._picker;
    if (!ch) return;
    const castType = this._castTypeFor(targetId);
    const playing = playingChannelFor(this._hass, this._config.guide, this._channels(), targetId);
    if (playing && playing.stream_id === ch.stream_id) {
      await this._hass.callService("m3u_caster", "stop", { media_player: targetId, cast_type: castType });
    } else {
      const data = { stream_id: ch.stream_id, media_player: targetId, cast_type: castType };
      if (castType === "apple_tv_app") {
        data.app_link = this._config.app_link || DEFAULT_APP_LINK;
        data.auto_confirm = this._config.auto_confirm !== false;
      }
      await this._hass.callService("m3u_caster", "play_stream", data);
    }
    this._closePicker();
  }

  _rowsHtml(channels, nowMap) {
    return channels.map((c) => {
      const logo = c.logo
        ? `<img src="${esc(c.logo)}" loading="lazy" alt=""/>`
        : `<span class="mono">${esc((c.name || "?").trim().charAt(0).toUpperCase())}</span>`;
      const num = c.number ? `${esc(String(c.number))} · ` : "";
      const badges = (nowMap[c.stream_id] || []).map((n) => `<span class="badge">${esc(n)}</span>`).join("");
      return `<div class="row" data-stream-id="${esc(c.stream_id)}" role="button" tabindex="0">
        <div class="logo">${logo}</div>
        <div class="info"><div class="name">${num}${esc(c.name)}</div><div class="now">${esc(c.now || "")}</div></div>
        <div class="badges" style="${badges ? "" : "display:none"}">${badges}</div>
      </div>`;
    }).join("");
  }
  _patchRows(list, channels, nowMap) {
    const byId = {};
    channels.forEach((c) => { byId[c.stream_id] = c; });
    list.querySelectorAll(".row").forEach((row) => {
      const c = byId[row.dataset.streamId];
      if (!c) return;
      const nowEl = row.querySelector(".now");
      if (nowEl) nowEl.textContent = c.now || "";
      const badgesEl = row.querySelector(".badges");
      if (badgesEl) {
        const names = nowMap[c.stream_id] || [];
        badgesEl.style.display = names.length ? "" : "none";
        badgesEl.innerHTML = names.map((n) => `<span class="badge">${esc(n)}</span>`).join("");
      }
    });
  }
  _renderPicker() {
    const overlay = this._root.querySelector(".picker-overlay");
    if (!this._picker) {
      overlay.style.display = "none";
      overlay.querySelector(".sheet").innerHTML = "";
      return;
    }
    overlay.style.display = "flex";
    const ch = this._picker;
    const targets = this._targets();
    const rows = targets.map((id) => {
      const st = this._hass.states[id];
      const playing = playingChannelFor(this._hass, this._config.guide, this._channels(), id);
      const isThis = playing && playing.stream_id === ch.stream_id;
      let status = "Idle";
      if (!st) status = "Unavailable";
      else if (isThis) status = "Now playing · tap to stop";
      else if (["off", "standby"].includes(st.state)) status = "Off";
      else if (playing) status = `Playing ${playing.name}`;
      return `<button class="target${isThis ? " live" : ""}" data-target="${esc(id)}">
        <span class="tname">${esc(this._targetName(id))}</span><span class="tstatus">${esc(status)}</span></button>`;
    }).join("") || `<div class="empty">No TVs configured. Add TVs in the card editor.</div>`;
    overlay.querySelector(".sheet").innerHTML = `<div class="sheet-hdr">${esc(ch.name)}</div>${rows}<button class="cancel">Cancel</button>`;
    overlay.querySelectorAll(".target").forEach((b) => b.addEventListener("click", () => this._pick(b.dataset.target)));
    overlay.querySelector(".cancel").addEventListener("click", () => this._closePicker());
  }
  // --- Timeline grid layout ---
  _fmtTime(d) { return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }
  _gridWindow() {
    const now = new Date();
    const start = new Date(now); start.setSeconds(0, 0);
    start.setMinutes(start.getMinutes() - (start.getMinutes() % GRID_STEP_MIN)); // floor to the grid step
    return { now, start, minutes: GRID_WINDOW_HOURS * 60 };
  }
  _chanRowsHtml(channels, nowMap) {
    return channels.map((c) => {
      const logo = c.logo
        ? `<img src="${esc(c.logo)}" loading="lazy" alt=""/>`
        : `<span class="mono">${esc((c.name || "?").trim().charAt(0).toUpperCase())}</span>`;
      const num = c.number ? `${esc(String(c.number))} · ` : "";
      const badges = (nowMap[c.stream_id] || []).map((n) => `<span class="badge">${esc(n)}</span>`).join("");
      return `<div class="chan-row" data-stream-id="${esc(c.stream_id)}" role="button" tabindex="0">
        <div class="logo">${logo}</div>
        <div class="name">${num}${esc(c.name)}</div>
        <div class="badges" style="${badges ? "" : "display:none"}">${badges}</div>
      </div>`;
    }).join("");
  }
  _rulerHtml(win) {
    const marks = [];
    for (let m = 0; m <= win.minutes; m += 30) {
      const t = new Date(win.start.getTime() + m * 60000);
      marks.push(`<div class="mark" style="left:${m * GRID_PX_PER_MIN}px">${esc(this._fmtTime(t))}</div>`);
    }
    return marks.join("");
  }
  // One absolutely-positioned block per upcoming programme, clipped to the visible window.
  _tracksHtml(channels, win) {
    const widthPx = win.minutes * GRID_PX_PER_MIN;
    return channels.map((c) => {
      const blocks = (c.programmes || []).map((p) => {
        const s = new Date(p.start);
        const e = p.end ? new Date(p.end) : new Date(win.start.getTime() + win.minutes * 60000);
        let left = Math.max(0, (s - win.start) / 60000 * GRID_PX_PER_MIN);
        let right = Math.min(widthPx, (e - win.start) / 60000 * GRID_PX_PER_MIN);
        if (right <= 0 || left >= widthPx) return "";
        const width = Math.max(GRID_MIN_BLOCK_PX, right - left);
        const current = s <= win.now && win.now <= e;
        return `<div class="block${current ? " current" : ""}" style="left:${left}px;width:${width}px" title="${esc(p.title)}">${esc(p.title)}</div>`;
      }).join("");
      return `<div class="track" data-stream-id="${esc(c.stream_id)}" role="button" tabindex="0">${blocks}</div>`;
    }).join("");
  }
  _syncGridScroll(a, b) {
    let syncing = false;
    const mirror = (from, to) => { if (syncing) return; syncing = true; to.scrollTop = from.scrollTop; syncing = false; };
    a.addEventListener("scroll", () => mirror(a, b));
    b.addEventListener("scroll", () => mirror(b, a));
  }
  _renderGrid(channels, nowMap) {
    const r = this._root;
    const win = this._gridWindow();
    const chanCol = r.querySelector(".chan-col");
    const tracks = r.querySelector(".tracks");
    const sig = channels.map((c) => c.stream_id).join(",");
    if (chanCol.dataset.sig !== sig) {
      chanCol.innerHTML = `<div class="chan-spacer"></div>${this._chanRowsHtml(channels, nowMap)}`;
      chanCol.dataset.sig = sig;
    } else {
      chanCol.querySelectorAll(".chan-row").forEach((row) => {
        const names = nowMap[row.dataset.streamId] || [];
        const badgesEl = row.querySelector(".badges");
        if (badgesEl) { badgesEl.style.display = names.length ? "" : "none"; badgesEl.innerHTML = names.map((n) => `<span class="badge">${esc(n)}</span>`).join(""); }
      });
    }
    r.querySelector(".ruler").innerHTML = this._rulerHtml(win);
    r.querySelector(".timeline-inner").style.width = `${win.minutes * GRID_PX_PER_MIN}px`;
    tracks.innerHTML = this._tracksHtml(channels, win);
    const nowLine = r.querySelector(".now-line");
    const nowLeft = (win.now - win.start) / 60000 * GRID_PX_PER_MIN;
    nowLine.style.left = `${nowLeft}px`;
    nowLine.style.display = nowLeft >= 0 && nowLeft <= win.minutes * GRID_PX_PER_MIN ? "" : "none";
    nowLine.style.height = `${GRID_RULER_PX + channels.length * GRID_ROW_PX}px`;
  }
  _render() {
    if (!this._hass || !this._config) return;
    const channels = this._visible();
    const groups = channelGroups(filterChannels(this._channels(), this._config.groups));
    const playlist = (this._hass.states[this._config.guide] || {}).attributes?.playlist || "";
    const isGrid = this._config.layout === "grid";
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.innerHTML = `
        <style>
          ha-card { padding: 12px 16px 16px; }
          .hdr { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; gap:8px; }
          .hdr .name { font-size:1.1em; font-weight:500; }
          select.grp { max-width:220px; font-size:.85em; padding:6px 8px; border-radius:6px; border:1px solid var(--divider-color);
                       background:var(--card-background-color); color:var(--primary-text-color); }
          .list { overflow-y:auto; max-height:60vh; border-top:1px solid var(--divider-color); }
          .row { display:flex; align-items:center; gap:10px; padding:8px 4px; border-bottom:1px solid var(--divider-color); cursor:pointer; }
          .row:hover, .row:active { background:var(--secondary-background-color); }
          .logo { width:32px; height:32px; border-radius:6px; background:var(--secondary-background-color);
                  display:flex; align-items:center; justify-content:center; overflow:hidden; flex:0 0 auto; }
          .logo img { width:100%; height:100%; object-fit:contain; }
          .logo .mono { font-size:.85em; font-weight:600; opacity:.7; }
          .info { flex:1; min-width:0; }
          .info .name { font-size:.92em; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
          .info .now { font-size:.78em; opacity:.7; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
          .badges { display:flex; gap:4px; flex:0 0 auto; }
          .badge { font-size:.68em; padding:2px 6px; border-radius:10px; background:var(--primary-color); color:var(--text-primary-color); white-space:nowrap; }
          .pl { font-size:.75em; opacity:.6; margin-top:8px; }
          .picker-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.5); align-items:center; justify-content:center; z-index:1000; }
          .sheet { background:var(--card-background-color); color:var(--primary-text-color); border-radius:12px; padding:12px;
                   width:min(90vw, 380px); max-height:80vh; overflow-y:auto; box-shadow:0 8px 24px rgba(0,0,0,.4); }
          .sheet-hdr { font-weight:600; margin-bottom:8px; padding:0 4px; }
          button.target { display:flex; justify-content:space-between; align-items:center; width:100%; text-align:left;
                          padding:10px 8px; border:0; border-radius:8px; background:none; color:var(--primary-text-color); font-size:.92em; cursor:pointer; }
          button.target:hover, button.target.live { background:var(--secondary-background-color); }
          button.target .tstatus { font-size:.78em; opacity:.65; margin-left:8px; }
          button.cancel { width:100%; margin-top:6px; padding:10px; border:0; border-radius:8px;
                          background:var(--secondary-background-color); color:var(--primary-text-color); cursor:pointer; }
          .empty { padding:12px 4px; opacity:.7; font-size:.9em; }
          .grid { display:flex; border-top:1px solid var(--divider-color); }
          .chan-col { flex:0 0 130px; overflow-y:auto; overflow-x:hidden; max-height:60vh; scrollbar-width:none; }
          .chan-col::-webkit-scrollbar { display:none; }
          .chan-spacer { height:${GRID_RULER_PX}px; }
          .chan-row { display:flex; align-items:center; gap:6px; height:${GRID_ROW_PX}px; padding:0 6px;
                      border-bottom:1px solid var(--divider-color); border-right:1px solid var(--divider-color); cursor:pointer; box-sizing:border-box; }
          .chan-row:hover, .chan-row:active { background:var(--secondary-background-color); }
          .chan-row .logo { width:22px; height:22px; }
          .chan-row .name { flex:1; min-width:0; font-size:.78em; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
          .chan-row .badges { flex:0 0 auto; }
          .timeline-scroll { flex:1; overflow:auto; max-height:60vh; position:relative; }
          .timeline-inner { position:relative; }
          .ruler { height:${GRID_RULER_PX}px; box-sizing:border-box; position:sticky; top:0; background:var(--card-background-color); z-index:1; border-bottom:1px solid var(--divider-color); }
          .ruler .mark { position:absolute; top:0; height:100%; font-size:.7em; opacity:.65; padding-left:4px;
                         border-left:1px solid var(--divider-color); display:flex; align-items:center; white-space:nowrap; }
          .track { position:relative; height:${GRID_ROW_PX}px; box-sizing:border-box; border-bottom:1px solid var(--divider-color); }
          .block { position:absolute; top:3px; bottom:3px; border-radius:6px; background:var(--secondary-background-color);
                   overflow:hidden; padding:0 6px; display:flex; align-items:center; font-size:.72em; white-space:nowrap;
                   text-overflow:ellipsis; cursor:pointer; }
          .block.current { background:var(--primary-color); color:var(--text-primary-color); }
          .now-line { position:absolute; top:0; width:2px; background:var(--error-color, red); z-index:2; pointer-events:none; }
        </style>
        <ha-card>
          <div class="hdr"><span class="name"></span><select class="grp"></select></div>
          <div class="list"></div>
          <div class="grid">
            <div class="chan-col"></div>
            <div class="timeline-scroll"><div class="timeline-inner">
              <div class="ruler"></div>
              <div class="tracks"></div>
              <div class="now-line"></div>
            </div></div>
          </div>
          <div class="pl"></div>
        </ha-card>
        <div class="picker-overlay"><div class="sheet"></div></div>`;
      this._root.querySelector("select.grp").addEventListener("change", (e) => { this._group = e.target.value; this._render(); });
      const list = this._root.querySelector(".list");
      const rowClick = (e) => {
        const row = e.target.closest && e.target.closest(".row, .chan-row, .track");
        if (!row) return;
        const c = this._visible().find((c) => c.stream_id === row.dataset.streamId);
        if (c) this._openPicker(c);
      };
      list.addEventListener("click", rowClick);
      list.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); rowClick(e); } });
      const chanCol = this._root.querySelector(".chan-col");
      const timelineScroll = this._root.querySelector(".timeline-scroll");
      chanCol.addEventListener("click", rowClick);
      timelineScroll.addEventListener("click", rowClick);
      this._syncGridScroll(chanCol, timelineScroll);
      const overlay = this._root.querySelector(".picker-overlay");
      overlay.addEventListener("click", (e) => { if (e.target === overlay) this._closePicker(); });
    }
    const r = this._root;
    r.querySelector(".name").textContent = this._config.title || playlist || "Guide";
    syncGroupPicker(r.querySelector("select.grp"), groups, this._group);
    const nowMap = this._targetsNowPlaying();
    r.querySelector(".list").style.display = isGrid ? "none" : "";
    r.querySelector(".grid").style.display = isGrid ? "flex" : "none";
    if (isGrid) {
      this._renderGrid(channels, nowMap);
    } else {
      const list = r.querySelector(".list");
      const sig = channels.map((c) => c.stream_id).join(",");
      if (list.dataset.sig !== sig) {
        list.innerHTML = this._rowsHtml(channels, nowMap);
        list.dataset.sig = sig;
      } else {
        this._patchRows(list, channels, nowMap);
      }
    }
    r.querySelector(".pl").textContent = playlist ? `Playlist: ${playlist}` : "";
    this._renderPicker();
  }
}

class M3uCasterGuideCardEditor extends HTMLElement {
  setConfig(config) { this._config = { targets: [], target_cast_types: {}, layout: "list", ...config }; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  _render() {
    if (!this._hass) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => ({
        guide: "M3U Caster playlist (guide sensor)", targets: "TVs to offer when a channel is tapped",
        groups: "Channel groups (empty = all)", title: "Card title (optional)", layout: "Layout",
        app_link: "App link template (used when a TV's cast type is Apple TV app, {url} = stream)",
        auto_confirm: "Auto press Select on the Open prompt (Apple TV app)",
      }[s.name] || s.name);
      // Keep the per-TV cast type map across a plain form edit: ha-form's value only carries its own schema fields.
      this._form.addEventListener("value-changed", (e) => {
        this._config = { ...this._config, ...e.detail.value };
        this._emit();
      });
      this._types = document.createElement("div");
      this._types.className = "target-types";
      const style = document.createElement("style");
      style.textContent = `
        .target-types { margin-top: 16px; }
        .target-types .hdr { font-size: .85em; opacity: .7; margin-bottom: 6px; }
        .target-types .row { display: flex; align-items: center; justify-content: space-between; gap: 8px;
                              padding: 6px 0; border-bottom: 1px solid var(--divider-color); }
        .target-types select { padding: 4px 6px; border-radius: 4px; border: 1px solid var(--divider-color);
                                background: var(--card-background-color); color: var(--primary-text-color); }
        .target-types .empty { font-size: .85em; opacity: .6; }`;
      this.appendChild(style);
      this.appendChild(this._form);
      this.appendChild(this._types);
    }
    const cfg = this._config || {};
    const guides = Object.keys(this._hass.states).filter((e) => e.startsWith("sensor.") && this._hass.states[e].attributes.channels);
    // This integration's own channel-player entities don't support play_stream as a cast target; keep them out of the picker.
    const ownPlayers = Object.keys(this._hass.states).filter((e) => e.startsWith("media_player.") && this._hass.states[e].attributes.target);
    this._form.hass = this._hass;
    this._form.data = cfg;
    this._form.schema = [
      { name: "guide", required: true, selector: { select: { mode: "dropdown", options: guides.map((e) => ({ value: e, label: `${this._hass.states[e].attributes.playlist || e}` })) } } },
      { name: "targets", required: true, selector: { entity: { domain: "media_player", multiple: true, exclude_entities: ownPlayers } } },
      groupSchema(this._hass, cfg.guide),
      { name: "layout", selector: { select: { mode: "dropdown", options: [
        { value: "list", label: "List (channel + current programme)" },
        { value: "grid", label: "Timeline grid (cable-box style)" },
      ] } } },
      { name: "app_link", selector: { text: {} } },
      { name: "auto_confirm", selector: { boolean: {} } },
      { name: "title", selector: { text: {} } },
    ];
    this._renderTargetTypes(cfg);
  }
  _renderTargetTypes(cfg) {
    const targets = (cfg.targets || []).filter(Boolean);
    const sig = targets.join(",");
    if (this._types.dataset.sig === sig) {
      this._types.querySelectorAll("select[data-target]").forEach((s) => {
        s.value = (cfg.target_cast_types || {})[s.dataset.target] || "auto";
      });
      return;
    }
    this._types.dataset.sig = sig;
    if (!targets.length) {
      this._types.innerHTML = `<div class="empty">Pick TVs above to set each one's cast type.</div>`;
      return;
    }
    const opts = CAST_TYPES.map((c) => `<option value="${esc(c.value)}">${esc(c.label)}</option>`).join("");
    this._types.innerHTML = `<div class="hdr">Cast type per TV</div>` + targets.map((id) => {
      const name = (this._hass.states[id] && this._hass.states[id].attributes.friendly_name) || id;
      return `<div class="row"><span>${esc(name)}</span><select data-target="${esc(id)}">${opts}</select></div>`;
    }).join("");
    this._types.querySelectorAll("select[data-target]").forEach((s) => {
      s.value = (cfg.target_cast_types || {})[s.dataset.target] || "auto";
      s.addEventListener("change", (e) => {
        const types = { ...(this._config.target_cast_types || {}), [e.target.dataset.target]: e.target.value };
        this._config = { ...this._config, target_cast_types: types };
        this._emit();
      });
    });
  }
  _emit() {
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
  }
}

customElements.define("m3u-caster-tv-card", M3uCasterTvCard);
customElements.define("m3u-caster-tv-card-editor", M3uCasterTvCardEditor);
customElements.define("m3u-caster-quad-card", M3uCasterQuadCard);
customElements.define("m3u-caster-quad-card-editor", M3uCasterQuadCardEditor);
customElements.define("m3u-caster-guide-card", M3uCasterGuideCard);
customElements.define("m3u-caster-guide-card-editor", M3uCasterGuideCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "m3u-caster-tv-card", name: "M3U Caster TV Card", description: "Pick a game from the EPG and cast to a TV", preview: true });
window.customCards.push({ type: "m3u-caster-quad-card", name: "M3U Caster QuadStream Card", description: "Pick up to four channels and send them to QuadStream on an Apple TV", preview: true });
window.customCards.push({ type: "m3u-caster-guide-card", name: "M3U Caster Guide Card", description: "Tablet channel guide: tap a channel, pick a TV to cast to", preview: true });
