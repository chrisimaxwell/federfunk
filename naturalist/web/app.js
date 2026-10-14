"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const booleans = ["show_names", "show_scientific", "show_counts", "show_title", "show_qr", "show_all"];
  const numberFormat = new Intl.NumberFormat();
  const defaultSchedule = {
    enabled: true, timezone: "America/Denver", latitude: 40.7372, longitude: -111.8581,
    start: { mode: "sunrise", offset_minutes: 0, time: "07:00" },
    end: { mode: "sunset", offset_minutes: 60, time: "20:00" },
  };
  const defaults = {
    show_names: false, show_scientific: false, show_counts: false,
    show_title: true, show_qr: true, show_all: true, scale: "log", max_birds: 8,
    style: "collage", classic_media: "photos", orientation: "portrait", dashboard_url: "", variants: {},
  };
  let currentState = null;
  let draft = { ...defaults, variants: {}, schedule: scheduleSettings() };
  let csrfToken = "";
  let dirty = false;
  let saving = false;
  let refreshing = false;
  let ready = false;
  let imageMode = "art";
  let displayedMode = null;
  let imageKey = "";
  let imageRequest = 0;

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function count(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? Math.round(parsed) : 0;
  }

  function dateValue(value) {
    if (value === null || value === undefined || value === "") return null;
    const numeric = typeof value === "number" ? (value < 1e12 ? value * 1000 : value) : value;
    const date = new Date(numeric);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function timeLabel(value) {
    if (typeof value === "string" && /^\d{2}:\d{2}(:\d{2})?$/.test(value)) return value.slice(0, 5);
    const date = dateValue(value);
    return date ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : null;
  }

  function scheduleSettings(settings = {}) {
    return {
      ...defaultSchedule, ...settings,
      start: { ...defaultSchedule.start, ...settings.start },
      end: { ...defaultSchedule.end, ...settings.end },
    };
  }

  function scheduledTime(value, timezone, includeDay = false) {
    const date = dateValue(value);
    if (!date) return null;
    const options = { timeZone: timezone || "America/Denver", hour: "numeric", minute: "2-digit" };
    if (includeDay) options.weekday = "short";
    try { return date.toLocaleString([], options); }
    catch { return date.toISOString(); }
  }

  function renderSchedule(state) {
    const schedule = state.schedule;
    const settings = state.settings?.schedule;
    byId("frame-schedule-status").hidden = !schedule;
    byId("sun-times").hidden = !schedule;
    if (!schedule) return;
    const timezone = settings?.timezone || "America/Denver";
    const sunrise = scheduledTime(schedule.sunrise, timezone);
    const sunset = scheduledTime(schedule.sunset, timezone);
    byId("sun-times").textContent = sunrise || sunset
      ? `Today · Sunrise ${sunrise || "unavailable"} · Sunset ${sunset || "unavailable"}`
      : "Sun times are unavailable here. The saved fallback clock times will be used.";
    byId("sun-times").title = `For the saved location, in ${timezone}`;
    const until = scheduledTime(schedule.next_change, timezone, true);
    const resume = scheduledTime(schedule.resume_at || schedule.next_change, timezone, true);
    byId("frame-schedule-status").classList.toggle("resting", schedule.active === false);
    if (settings?.enabled === false) {
      byId("frame-schedule-label").textContent = "Updates throughout the day";
      byId("frame-schedule-detail").textContent = "Overnight rest is turned off.";
    } else if (schedule.active === false) {
      byId("frame-schedule-label").textContent = resume ? `Resting until ${resume}` : "The frame is resting";
      byId("frame-schedule-detail").textContent = `Holding the last picture. Times are in ${timezone}.`;
    } else {
      byId("frame-schedule-label").textContent = until ? `Update window open until ${until}` : "Update window is open";
      byId("frame-schedule-detail").textContent = `The frame updates on its scheduled wakes. Times are in ${timezone}.`;
    }
  }

  function safeUrl(value) {
    try {
      const url = new URL(value);
      return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }

  function renderDevice(state) {
    const device = state.device || {};
    const percentage = device.battery_percent;
    const voltage = device.battery_voltage;
    const validPercent = Number.isInteger(percentage) && percentage >= 0 && percentage <= 100;
    const validVoltage = typeof voltage === "number" && Number.isFinite(voltage) && voltage >= 2.5 && voltage <= 4.5;
    const reported = dateValue(device.reported_at);
    const seen = dateValue(device.last_seen);
    const resting = device.resting === true;
    const stale = device.stale === true;
    const zone = state.settings?.schedule?.timezone || "America/Denver";
    const stamp = (value) => {
      try { return value.toLocaleString([], { timeZone: zone, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }); }
      catch { return value.toLocaleString(); }
    };
    byId("device-percent").textContent = validPercent ? `${percentage}%` : "—";
    byId("device-charging").textContent = device.charging === "charging" ? "Charging at last report"
      : device.charging === "not_charging" ? "Not charging at last report" : "Charging status unavailable";
    byId("device-voltage").hidden = !validVoltage;
    byId("device-voltage").textContent = validVoltage ? `${voltage.toFixed(2)} V` : "";
    byId("device-status").textContent = !reported ? "No battery reading" : resting ? "Overnight rest" : stale ? "Reading may be out of date" : "Last reported";
    byId("device-heading").closest("section").classList.toggle("stale", stale && !resting);
    byId("device-reported").textContent = reported ? `Battery last reported ${stamp(reported)} · ${zone}.`
      : "No battery reading has been received yet.";
    byId("device-seen").hidden = !seen || (reported && seen.getTime() === reported.getTime());
    byId("device-seen").textContent = seen ? `Frame last checked in ${stamp(seen)} · ${zone}.` : "";
  }

  async function request(url, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(url, { cache: "no-store", credentials: "same-origin", signal: controller.signal, ...options });
      let payload;
      try { payload = await response.json(); }
      catch { throw new Error("The picture service returned an unreadable response."); }
      if (!response.ok) throw new Error(payload.error || `The picture service returned ${response.status}.`);
      return payload;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("The picture service took too long to respond. Try again.");
      throw error;
    } finally { window.clearTimeout(timeout); }
  }

  function showServiceMessage(message) {
    byId("service-message").hidden = !message;
    byId("service-message-text").textContent = message || "";
  }

  function saveStatus(message, error = false) {
    byId("save-status").textContent = message;
    byId("save-status").classList.toggle("error", error);
  }

  function updateFormHelp() {
    const presentations = {
      collage: "An open arrangement of historical drawings, with room to breathe.",
      classic: "A featured bird and a summary of the day’s detections.",
      field_guide: "Historical drawings in a field-guide arrangement, with optional labels.",
    };
    byId("style-help").textContent = presentations[draft.style] || presentations.collage;
    const classic = draft.style === "classic";
    byId("classic-media-field").hidden = !classic;
    byId("classic_media").disabled = !classic;
    byId("scale").disabled = classic;
    byId("scale").closest(".field").hidden = classic;
    byId("variant-section").hidden = classic || !byId("variant-fields").children.length;
    for (const select of byId("variant-fields").querySelectorAll("select")) select.disabled = classic;
    byId("qr-settings").hidden = !draft.show_qr;
    byId("dashboard_url").required = draft.show_qr;
    byId("max-birds-value").value = draft.max_birds;
    byId("bird-limit-field").hidden = draft.show_all;
    byId("max_birds").disabled = draft.show_all;
    const explanation = {
      log: "More frequently heard birds get more space; a gentle scale keeps quieter visitors visible.",
      linear: "Illustration area is proportional to detection count. Frequent visitors can dominate the picture.",
      equal: "Every species gets the same amount of space, regardless of how often it was heard.",
    };
    byId("scale-help").textContent = explanation[draft.scale] || explanation.log;
    byId("schedule-controls").disabled = !draft.schedule.enabled;
    for (const boundary of ["start", "end"]) {
      const fixed = draft.schedule[boundary].mode === "fixed";
      byId(`schedule_${boundary}_offset_field`).hidden = fixed;
      byId(`schedule_${boundary}_offset`).disabled = fixed;
      byId(`schedule_${boundary}_time_field`).hidden = !fixed;
      byId(`schedule_${boundary}_time`).disabled = !fixed;
    }
    const defaultLocation = Math.abs(draft.schedule.latitude - defaultSchedule.latitude) < .0001 && Math.abs(draft.schedule.longitude - defaultSchedule.longitude) < .0001;
    byId("schedule-location-note").textContent = defaultLocation
      ? "Approximate location for ZIP 84105, Salt Lake City. Sun times adjust with the seasons."
      : "Sun times use these coordinates and adjust with the seasons. A precise street address is not needed.";
  }

  function readForm() {
    for (const name of booleans) draft[name] = byId(name).checked;
    draft.style = byId("style").value;
    draft.classic_media = byId("classic_media").value;
    draft.scale = byId("scale").value;
    draft.orientation = byId("orientation").value;
    draft.max_birds = Number(byId("max_birds").value);
    draft.dashboard_url = byId("dashboard_url").value.trim();
    draft.schedule.enabled = byId("schedule_enabled").checked;
    draft.schedule.timezone = byId("schedule_timezone").value.trim();
    draft.schedule.latitude = Number(byId("schedule_latitude").value);
    draft.schedule.longitude = Number(byId("schedule_longitude").value);
    for (const boundary of ["start", "end"]) {
      draft.schedule[boundary] = {
        mode: byId(`schedule_${boundary}_mode`).value,
        offset_minutes: Number(byId(`schedule_${boundary}_offset`).value),
        time: byId(`schedule_${boundary}_time`).value,
      };
    }
    for (const select of byId("variant-fields").querySelectorAll("select")) {
      if (select.value) draft.variants[select.dataset.species] = select.value;
      else delete draft.variants[select.dataset.species];
    }
    updateFormHelp();
  }

  function fillForm(settings) {
    draft = { ...defaults, ...settings, variants: { ...(settings?.variants || {}) }, schedule: scheduleSettings(settings?.schedule) };
    for (const name of booleans) byId(name).checked = Boolean(draft[name]);
    for (const name of ["style", "classic_media", "scale", "orientation", "max_birds", "dashboard_url"]) byId(name).value = draft[name];
    byId("schedule_enabled").checked = Boolean(draft.schedule.enabled);
    for (const field of ["timezone", "latitude", "longitude"]) byId(`schedule_${field}`).value = draft.schedule[field];
    for (const boundary of ["start", "end"]) {
      byId(`schedule_${boundary}_mode`).value = draft.schedule[boundary].mode;
      byId(`schedule_${boundary}_offset`).value = draft.schedule[boundary].offset_minutes;
      byId(`schedule_${boundary}_time`).value = draft.schedule[boundary].time;
    }
    updateFormHelp();
  }

  function catalogue(state) {
    return Array.isArray(state.artworks) ? state.artworks : (state.artworks?.assets || []);
  }

  function artworkId(artwork) { return String(artwork.id || artwork.artwork_id || ""); }
  function artworkSpecies(artwork) { return artwork.scientific_name || artwork.species || ""; }
  function artworkTitle(artwork) {
    return artwork.title || artwork.label || [artwork.common_name || artwork.scientific_name, artwork.creator, artwork.date].filter(Boolean).join(" · ") || artworkId(artwork);
  }

  function displaySettings(state) { return state.display_settings || state.settings || {}; }
  function displayStyle(state) { return displaySettings(state).style || "collage"; }

  function renderVariants(state) {
    const container = byId("variant-fields");
    container.replaceChildren();
    const assets = catalogue(state);
    for (const species of state.stats?.species || []) {
      const choices = assets.filter((artwork) => artworkSpecies(artwork) === species.scientific_name && artworkId(artwork));
      if (choices.length < 2) continue;
      const field = node("div", "field");
      const id = `artwork-variant-${container.children.length}`;
      const label = node("label", "", species.common_name || species.scientific_name);
      label.htmlFor = id;
      const select = node("select");
      select.id = id;
      select.dataset.species = species.scientific_name;
      const automatic = node("option", "", "Automatic selection");
      automatic.value = "";
      select.append(automatic);
      for (const artwork of choices) {
        const option = node("option", "", artworkTitle(artwork));
        option.value = artworkId(artwork);
        select.append(option);
      }
      select.value = draft.variants[species.scientific_name] || "";
      select.disabled = draft.style === "classic";
      field.append(label, select);
      container.append(field);
    }
    byId("variant-section").hidden = draft.style === "classic" || !container.children.length;
  }

  function hourlyValues(species) {
    const total = new Array(24).fill(0);
    let present = false;
    for (const bird of species) {
      const hours = bird.hourly_counts;
      if (!hours || typeof hours !== "object" || !Object.keys(hours).length) continue;
      present = true;
      if (Array.isArray(hours)) {
        hours.forEach((value, index) => {
          const hour = typeof value === "object" && value !== null ? Number(value.hour) : index;
          const detections = typeof value === "object" && value !== null ? value.count : value;
          if (Number.isInteger(hour) && hour >= 0 && hour < 24) total[hour] += count(detections);
        });
      } else {
        for (const [key, value] of Object.entries(hours)) {
          const hour = Number(key);
          if (Number.isInteger(hour) && hour >= 0 && hour < 24) total[hour] += count(value);
        }
      }
    }
    return present ? total : null;
  }

  function renderHourly(species) {
    const values = hourlyValues(species);
    byId("hourly-section").hidden = !values;
    if (!values) return;
    const chart = byId("hourly-chart");
    chart.replaceChildren();
    const maximum = Math.max(...values, 1);
    const accessible = [];
    values.forEach((value, hour) => {
      const track = node("div", "hour-track");
      track.title = `${String(hour).padStart(2, "0")}:00 · ${numberFormat.format(value)} detections`;
      const bar = node("span", "hour-bar");
      bar.style.height = `${100 * value / maximum}%`;
      track.append(bar);
      chart.append(track);
      if (value) accessible.push(`${hour}:00, ${value}`);
    });
    chart.setAttribute("aria-label", `Hourly detections: ${accessible.length ? accessible.join("; ") : "none"}.`);
  }

  function renderSpecies(species, state) {
    const container = byId("species-list");
    const expanded = new Set(Array.from(container.querySelectorAll("details[open]"), (item) => item.dataset.species));
    container.replaceChildren();
    byId("species-empty").hidden = species.length > 0;
    byId("species-details").hidden = species.length === 0;
    byId("species-list-count").textContent = `${species.length} in the collection`;
    const largest = Math.max(...species.map((bird) => count(bird.count)), 1);
    for (const bird of species) {
      const row = node("details", "species-row");
      row.dataset.species = bird.scientific_name;
      row.open = expanded.has(bird.scientific_name);
      const summary = node("summary");
      const identity = node("span", "species-identity");
      identity.append(node("span", "species-name", bird.common_name || bird.scientific_name));
      if (bird.scientific_name) identity.append(node("span", "species-latin", bird.scientific_name));
      const detections = node("span", "species-count", numberFormat.format(count(bird.count)));
      detections.setAttribute("aria-label", `${count(bird.count)} detections`);
      summary.append(identity, detections);
      const meta = node("div", "species-meta");
      const latest = timeLabel(bird.latest_heard);
      if (latest) meta.append(node("span", "", `Last heard ${latest}`));
      if (bird.max_confidence !== null && bird.max_confidence !== undefined) {
        const confidence = Number(bird.max_confidence);
        if (Number.isFinite(confidence)) meta.append(node("span", "", `Best confidence ${Math.round(confidence <= 1 ? confidence * 100 : confidence)}%`));
      }
      if (displayStyle(state) !== "classic") {
        if (bird.artwork_available === false) meta.append(node("span", "missing-art", "No illustration in the library yet."));
        else if (bird.illustrated === false) meta.append(node("span", "", "Not included in the current picture."));
      } else if (displaySettings(state).classic_media === "drawings" && bird.displayed === true && bird.artwork_available === false) {
        meta.append(node("span", "missing-art", "No illustration for the featured bird in the library yet."));
      }
      const bar = node("div", "species-frequency");
      bar.setAttribute("aria-hidden", "true");
      const fill = node("span");
      fill.style.width = `${count(bird.count) / largest * 100}%`;
      bar.append(fill);
      row.append(summary, meta, bar);
      container.append(row);
    }
  }

  function renderCredits(state) {
    const container = byId("artwork-credits");
    container.replaceChildren();
    const used = new Set((state.stats?.species || []).map((bird) => bird.artwork_id).filter(Boolean));
    const classic = displayStyle(state) === "classic";
    const photos = classic && displaySettings(state).classic_media !== "drawings";
    const credits = classic ? (Array.isArray(state.photo_credits) ? state.photo_credits : [])
      : catalogue(state).filter((item) => used.has(artworkId(item)));
    byId("sources-heading").textContent = photos ? "Behind the photograph" : "From the naturalist’s library";
    byId("sources-heading").append(node("span", "muted", photos ? "Photo credits & sources" : "Illustration credits & sources"));
    byId("credits-description").textContent = photos
      ? "Sources, attribution and image changes for the photograph shown on the frame."
      : "Historical illustrations, collected with their original sources. Credits apply to the drawings in this collection.";
    for (const artwork of credits) {
      const item = node("li");
      const source = safeUrl(artwork.source_url || artwork.source || artwork.url);
      const name = artwork.common_name || artwork.scientific_name || (photos ? "Bird photograph" : "Bird illustration");
      const title = node(source ? "a" : "span", "credit-title", `${name} · ${artworkTitle(artwork)}`);
      if (source) { title.href = source; title.target = "_blank"; title.rel = "noopener noreferrer"; }
      const details = [artwork.artist || artwork.creator, artwork.year || artwork.date, artwork.license || artwork.rights,
        photos ? artwork.source_provider : null].filter(Boolean).join(" · ");
      item.append(title);
      if (details) item.append(node("span", "credit-note", details));
      if (typeof artwork.attribution === "string" && artwork.attribution) item.append(node("span", "credit-note", artwork.attribution));
      if (typeof artwork.changes === "string" && artwork.changes) item.append(node("span", "credit-note", `Image changes: ${artwork.changes}`));
      const links = node("div", "credit-links");
      const included = new Set();
      for (const [label, value] of [["Source record", source], ["Archive", artwork.archive_url],
        ["Photographer", photos ? artwork.author_url : null],
        [photos ? "Original photo" : "Original scan", artwork.original_image_url || artwork.image_url], ["Rights & license", artwork.rights_url || artwork.license_url]]) {
        const href = safeUrl(value);
        if (!href || included.has(href)) continue;
        included.add(href);
        const link = node("a", "", label);
        link.href = href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.setAttribute("aria-label", `${label} for ${name}`);
        links.append(link);
      }
      if (links.children.length) item.append(links);
      container.append(item);
    }
    byId("sources-section").hidden = !container.children.length;
  }

  function renderImage(state) {
    const revision = state.revision ?? state.last_success ?? "current";
    const key = `${imageMode}-${revision}`;
    byId("art-mode").setAttribute("aria-pressed", String(imageMode === "art"));
    byId("paper-mode").setAttribute("aria-pressed", String(imageMode === "paper"));
    const classic = displayStyle(state) === "classic";
    const photos = classic && displaySettings(state).classic_media !== "drawings";
    byId("art-mode").textContent = photos ? "Photo" : "Artwork";
    byId("picture").alt = classic ? `A featured bird ${photos ? "photograph" : "drawing"} and the day’s detection summary`
      : displayStyle(state) === "field_guide" ? "Today’s birds arranged as a field-guide plate"
      : "Today’s birds, arranged as a natural history illustration";
    const source = `${imageMode === "paper" ? "/preview.png" : "/art.png"}?v=${encodeURIComponent(revision)}`;
    byId("download-image").href = source;
    byId("download-image").download = imageMode === "paper" ? "heard-today-epaper.png" : "heard-today.png";
    byId("picture-paper").classList.toggle("landscape", (state.display_settings || state.settings)?.orientation === "landscape");
    byId("preview-note").textContent = imageMode === "paper"
      ? "The frame’s six-color pixel preview. The physical e-paper display will look different from this screen."
      : "The composition sent to your frame. Screen colors and the physical e-paper display will differ.";
    if (key === imageKey) return;
    imageKey = key;
    const requestId = ++imageRequest;
    const image = new Image();
    image.onload = () => {
      if (requestId !== imageRequest) return;
      displayedMode = imageMode;
      byId("picture").src = source;
      byId("picture").hidden = false;
      byId("picture-placeholder").hidden = true;
    };
    image.onerror = () => {
      if (requestId !== imageRequest) return;
      imageKey = "";
      if (!byId("picture").hidden) {
        imageMode = displayedMode;
        byId("art-mode").setAttribute("aria-pressed", String(imageMode === "art"));
        byId("paper-mode").setAttribute("aria-pressed", String(imageMode === "paper"));
        byId("download-image").href = byId("picture").src;
        byId("download-image").download = imageMode === "paper" ? "heard-today-epaper.png" : "heard-today.png";
        byId("preview-note").textContent = "The new preview could not be loaded. The previous preview is still shown.";
        return;
      }
      byId("picture-placeholder").classList.add("error");
      byId("picture-placeholder-text").textContent = "The picture is not available yet. It will appear when the service has rendered it.";
    };
    image.src = source;
  }

  function renderState(state, replaceDraft = false) {
    currentState = state;
    const stats = state.stats || {};
    const species = Array.isArray(stats.species) ? stats.species : [];
    byId("demo-badge").hidden = !state.demo;
    byId("collection-kind").textContent = state.demo ? "Sample detections" : "Today's collection";
    byId("species-total").textContent = stats.species_count === undefined ? "—" : numberFormat.format(count(stats.species_count));
    byId("detection-total").textContent = stats.total_detections === undefined ? "—" : numberFormat.format(count(stats.total_detections));
    const threshold = Number(stats.confidence_threshold);
    byId("confidence-note").hidden = stats.confidence_threshold === undefined || !Number.isFinite(threshold);
    byId("confidence-note").textContent = `Confidence threshold: ${Math.round(threshold * 100)}%.`;
    const day = dateValue(/^\d{4}-\d{2}-\d{2}$/.test(stats.date || "") ? `${stats.date}T12:00:00` : stats.date);
    byId("collection-date").textContent = day ? day.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" }) : "Today's collection";
    const updated = dateValue(state.last_success);
    byId("updated-at").textContent = updated ? `Updated ${updated.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}` : "";
    const scale = displaySettings(state).scale;
    byId("picture-caption").textContent = displayStyle(state) === "classic" ? "A featured bird and the day’s detection summary."
      : displayStyle(state) === "field_guide" ? "The day’s birds, arranged as an ordered field-guide plate."
      : scale === "equal" ? "Each species, an equal place on the page." : scale === "linear" ? "More often heard, more space on the page." : "The day’s frequent visitors, gently given more space.";
    if (replaceDraft || !dirty) fillForm(state.settings || {});
    renderSpecies(species, state);
    if (!state.stats) byId("species-empty").textContent = "Waiting for the first collection of detections.";
    else byId("species-empty").textContent = "No birds recorded in this collection yet. The picture will grow as detections arrive.";
    renderHourly(species);
    renderVariants(state);
    renderCredits(state);
    renderImage(state);
    renderSchedule(state);
    renderDevice(state);
    showServiceMessage(state.error ? `The collection could not be updated: ${state.error}. Showing the last available picture and detections.` : "");
  }

  async function refresh() {
    if (refreshing || saving) return;
    refreshing = true;
    try {
      if (!ready) {
        const [state, configuration] = await Promise.all([request("/api/state"), request("/api/settings")]);
        csrfToken = configuration.csrf_token || "";
        if (!csrfToken) throw new Error("The service did not provide a settings token. Reload the page to try again.");
        renderState({ ...state, settings: state.settings || configuration.settings }, true);
        ready = true;
        byId("settings-fields").disabled = false;
        saveStatus("Picture settings are up to date.");
      } else {
        renderState(await request("/api/state"));
      }
    } catch (error) {
      showServiceMessage(currentState ? `The service is unavailable. Showing the last loaded collection. ${error.message}` : `Could not load your collection. ${error.message}`);
      if (!ready) {
        saveStatus("Settings are unavailable until the service reconnects.", true);
        byId("collection-date").textContent = "Collection unavailable";
        byId("picture-placeholder").classList.add("error");
        byId("picture-placeholder-text").textContent = "Your picture will appear when the service reconnects.";
      }
    } finally { refreshing = false; }
  }

  byId("settings-form").addEventListener("input", () => {
    readForm();
    dirty = true;
    byId("apply-button").disabled = !ready || saving;
    saveStatus("You have unapplied changes.");
  });

  byId("settings-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!ready || saving || !dirty) return;
    readForm();
    if (draft.show_qr && !safeUrl(draft.dashboard_url)) {
      saveStatus("Enter a complete http:// or https:// dashboard address for the QR link.", true);
      byId("dashboard_url").focus();
      return;
    }
    if (draft.schedule.enabled) {
      try { new Intl.DateTimeFormat("en-US", { timeZone: draft.schedule.timezone }).format(); }
      catch {
        saveStatus("Enter a valid IANA time zone, such as America/Denver.", true);
        byId("schedule_timezone").closest("details").open = true;
        byId("schedule_timezone").focus();
        return;
      }
    }
    saving = true;
    byId("settings-fields").disabled = true;
    byId("apply-button").disabled = true;
    saveStatus("Preparing your picture…");
    try {
      const state = await request("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
        body: JSON.stringify(draft),
      });
      dirty = false;
      renderState(state, true);
      saveStatus(state.schedule?.active === false
        ? "Settings saved. Your frame will receive changes when scheduled updates resume."
        : "Settings saved. Your frame will receive changes on its next scheduled wake.");
    } catch (error) {
      saveStatus(`Could not apply changes: ${error.message}`, true);
    } finally {
      saving = false;
      byId("settings-fields").disabled = false;
      byId("apply-button").disabled = !dirty;
    }
  });

  for (const [id, mode] of [["art-mode", "art"], ["paper-mode", "paper"]]) {
    byId(id).addEventListener("click", () => {
      imageMode = mode;
      if (currentState) renderImage(currentState);
    });
  }
  byId("retry-button").addEventListener("click", refresh);
  let libraryReport = null;
  let libraryLoading = false;
  function renderLibrary() {
    if (!libraryReport) return;
    const query = byId("library-search").value.toLowerCase().trim();
    const container = byId("library-list");
    container.replaceChildren();
    for (const row of libraryReport.rows) {
      if (query && !`${row.common_name} ${row.scientific_name}`.toLowerCase().includes(query)) continue;
      const item = node("div", "library-row");
      if (row.artwork_ids.length) {
        const artworkLink = node("a");
        const thumbnail = node("img", "library-bird");
        thumbnail.src = `/artwork/${encodeURIComponent(row.artwork_ids[0])}.png`;
        thumbnail.alt = row.common_name;
        thumbnail.loading = "lazy";
        artworkLink.href = thumbnail.src;
        artworkLink.target = "_blank";
        artworkLink.rel = "noopener";
        artworkLink.title = `Open the ${row.common_name} illustration`;
        artworkLink.append(thumbnail);
        item.append(artworkLink);
      } else item.append(node("span", "library-bird missing-art", "—"));
      const description = node("div");
      description.append(node("strong", "", row.common_name), node("div", "muted small", row.scientific_name));
      const status = !row.covered ? "Artwork needed" : row.artwork_reviewed ? "Reviewed illustration" : "Illustration awaiting review";
      description.append(node("div", "small", status + (row.max_confidence < .8 ? " · Low-confidence identification" : "")));
      description.append(node("div", "small muted", `${numberFormat.format(row.count)} recorded detections`));
      item.append(description);
      container.append(item);
    }
  }
  byId("library-search").addEventListener("input", renderLibrary);
  byId("library-details").addEventListener("toggle", async () => {
    if (!byId("library-details").open || libraryReport || libraryLoading) return;
    libraryLoading = true;
    byId("library-summary").textContent = "Checking your species history…";
    try {
      libraryReport = await request("/api/library");
      byId("library-summary").textContent = `${libraryReport.covered_species} of ${libraryReport.species_count} reported species labels have illustrations, covering ${Number(libraryReport.detection_coverage_percent).toFixed(1)}% of recorded detections.`;
      renderLibrary();
    } catch (error) {
      byId("library-summary").textContent = `${error.message}. Close and reopen this section to retry.`;
    } finally { libraryLoading = false; }
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  window.setInterval(() => { if (!document.hidden) refresh(); }, 30000);
  refresh();
})();
