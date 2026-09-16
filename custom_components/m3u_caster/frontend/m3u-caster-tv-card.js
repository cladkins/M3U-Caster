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
const esc = (s) => String(s).replace(/"/g, "&quot;");
const guideChannels = (hass, guide) => {
  const st = hass.states[guide];
  return st && Array.isArray(st.attributes.channels) ? st.attributes.channels : [];
};
// Rebuild a <select> only when the channel list itself changes: rewriting it on every state update closes an
// open menu and drops the pick. Selection is applied through .value, never baked into the HTML.
const syncPicker = (select, channels, selected, placeholder) => {
  const sig = placeholder + "\n" + channels.map((c) => `${c.stream_id}\t${c.group || ""}\t${c.label}`).join("\n");
  if (select.dataset.sig !== sig) {
    const opt = (c) => `<option value="${c.stream_id}">${c.label}</option>`;
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
    this._config = { cast_type: "auto", show_logo: true, app_link: DEFAULT_APP_LINK, auto_confirm: true, ...config };
    this._selected = this._selected || "";
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
  _channels() {
    const st = this._hass.states[this._config.guide];
    return st && Array.isArray(st.attributes.channels) ? st.attributes.channels : [];
  }
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
    const channels = this._channels();
    const playlist = (this._hass.states[this._config.guide] || {}).attributes?.playlist || "";
    const tvState = tv ? tv.state : "unavailable";
    const active = ["playing", "paused", "buffering"].includes(tvState);
    const onTv = active ? this._playingChannel(tv, channels) : null;
    if (onTv && !this._selected) this._selected = onTv.stream_id;
    const sel = channels.find((c) => c.stream_id === this._selected) || null;
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
          <select></select>
          <div class="now"><img/><div><div class="t"></div><div class="s"></div></div></div>
          <div class="btns"><button class="play">Cast</button><button class="stop">Stop</button></div>
          <div class="pl"></div>
        </ha-card>`;
      this._root.querySelector("select").addEventListener("change", (e) => { this._selected = e.target.value; this._render(); });
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
    syncPicker(r.querySelector("select"), channels, this._selected, "Choose a game or channel");
    const img = r.querySelector(".now img");
    img.style.display = this._config.show_logo && sel && sel.logo ? "" : "none";
    if (sel && sel.logo) img.src = sel.logo;
    r.querySelector(".now .t").textContent = sel ? (sel.now || sel.name) : "";
    r.querySelector(".now .s").textContent = sel
      ? [sel.name, sel.now_start ? `${this._fmt(sel.now_start)}–${this._fmt(sel.now_end)}` : "", sel.next ? `Next: ${sel.next} ${this._fmt(sel.next_start)}` : ""].filter(Boolean).join("  ·  ")
      : "";
    r.querySelector("button.play").disabled = !this._selected || tvState === "unavailable";
    r.querySelector("button.stop").disabled = tvState === "unavailable";
    r.querySelector(".pl").textContent = playlist ? `Playlist: ${playlist}  ·  Cast: ${castLabel(this._config.cast_type)}` : "";
  }
}

class M3uCasterTvCardEditor extends HTMLElement {
  setConfig(config) { this._config = { cast_type: "auto", show_logo: true, ...config }; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }
  _render() {
    if (!this._hass) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => ({
        media_player: "TV / media player", cast_type: "Cast type", guide: "M3U Caster playlist (guide sensor)",
        title: "Card title (optional)", show_logo: "Show channel logo",
        app_link: "App link template (apple_tv_app only, {url} = stream)", auto_confirm: "Auto press Select on the Open prompt",
      }[s.name] || s.name);
      this._form.addEventListener("value-changed", (e) => {
        this._config = e.detail.value;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    const guides = Object.keys(this._hass.states).filter((e) => e.startsWith("sensor.") && this._hass.states[e].attributes.channels);
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = [
      { name: "media_player", required: true, selector: { entity: { domain: "media_player" } } },
      { name: "cast_type", selector: { select: { mode: "dropdown", options: CAST_TYPES } } },
      { name: "app_link", selector: { text: {} } },
      { name: "auto_confirm", selector: { boolean: {} } },
      { name: "guide", required: true, selector: { select: { mode: "dropdown", options: guides.map((e) => ({ value: e, label: `${this._hass.states[e].attributes.playlist || e}` })) } } },
      { name: "title", selector: { text: {} } },
      { name: "show_logo", selector: { boolean: {} } },
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
  }
  set hass(hass) { this._hass = hass; this._render(); }
  getCardSize() { return 5; }
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
    const channels = guideChannels(this._hass, this._config.guide);
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
            ${[1, 2, 3, 4].map((n) => `<div class="slot"><span class="l">Stream ${n}</span><select data-slot="${n - 1}"></select></div>`).join("")}
          </div>
          <div class="btns"><button class="play">Cast to QuadStream</button><button class="stop">Stop</button></div>
          <div class="pl"></div>
        </ha-card>`;
      this._root.querySelectorAll("select").forEach((s) => s.addEventListener("change", (e) => {
        this._sel[Number(e.target.dataset.slot)] = e.target.value; this._render();
      }));
      this._root.querySelector("button.play").addEventListener("click", () => this._cast());
      this._root.querySelector("button.stop").addEventListener("click", () => this._stop());
    }
    const r = this._root;
    r.querySelector(".name").textContent = tvName;
    r.querySelector(".state").textContent = tvState;
    r.querySelectorAll("select").forEach((s, i) => syncPicker(s, channels, this._sel[i], `Stream ${i + 1}: none`));
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
        media_player: "Apple TV (media player)", guide: "M3U Caster playlist (guide sensor)", title: "Card title (optional)",
      }[s.name] || s.name);
      this._form.addEventListener("value-changed", (e) => {
        this._config = e.detail.value;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    const guides = Object.keys(this._hass.states).filter((e) => e.startsWith("sensor.") && this._hass.states[e].attributes.channels);
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = [
      { name: "media_player", required: true, selector: { entity: { domain: "media_player" } } },
      { name: "guide", required: true, selector: { select: { mode: "dropdown", options: guides.map((e) => ({ value: e, label: `${this._hass.states[e].attributes.playlist || e}` })) } } },
      { name: "title", selector: { text: {} } },
    ];
  }
}

customElements.define("m3u-caster-tv-card", M3uCasterTvCard);
customElements.define("m3u-caster-tv-card-editor", M3uCasterTvCardEditor);
customElements.define("m3u-caster-quad-card", M3uCasterQuadCard);
customElements.define("m3u-caster-quad-card-editor", M3uCasterQuadCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "m3u-caster-tv-card", name: "M3U Caster TV Card", description: "Pick a game from the EPG and cast to a TV", preview: true });
window.customCards.push({ type: "m3u-caster-quad-card", name: "M3U Caster QuadStream Card", description: "Pick up to four channels and send them to QuadStream on an Apple TV", preview: true });
