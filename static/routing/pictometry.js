(function (global) {
  "use strict";

  const DEFAULT_HOST = "http://geocorvm1.skagit.local";
  const DEFAULT_ENDPOINT = "https://pol.pictometry.com/ipa/v1/load.php";
  const ORIENTATIONS = new Set(["N", "E", "S", "W"]);
  const YEARS = new Set([2019, 2025]);

  function safeError(error) {
    return String(error && error.message ? error.message : error || "Unknown error")
      .replace(/(?:key|token|secret|password)=([^&\s]+)/gi, "$1=[redacted]");
  }

  class PictometryAdapter {
    constructor(options) {
      this.options = options || {};
      this.mount = this.options.mount || null;
      this.countyHost = String(this.options.countyHost || DEFAULT_HOST).replace(/\/$/, "");
      this.viewerPath = this.options.viewerPath || "/Html5ViewerProd/Resources/3rdPartyMaps/Pictometry.aspx";
      this.endpoint = this.options.endpoint || DEFAULT_ENDPOINT;
      this.status = {
        state: "idle",
        origin: global.location ? global.location.origin : "unknown",
        hostAvailable: false,
        sessionAvailable: null,
        parcelId: "",
        latitude: null,
        longitude: null,
        orientation: "N",
        year: 2025,
        message: "Not initialized",
      };
      this.host = null;
    }

    _update(patch) {
      this.status = { ...this.status, ...patch };
      if (typeof this.options.onStatus === "function") this.options.onStatus(this.getStatus());
    }

    _call(methods, ...args) {
      if (!this.host) return false;
      for (const method of methods) {
        if (typeof this.host[method] === "function") {
          this.host[method](...args);
          return true;
        }
      }
      return false;
    }

    initialize() {
      this.status.hostAvailable = typeof global.PictometryHost === "function";
      if (!this.status.hostAvailable) {
        this._update({
          state: "unavailable",
          message: "The supported PictometryHost embed is not available on this origin.",
        });
        return this.getStatus();
      }

      try {
        const mountId = this.mount && this.mount.id;
        if (!mountId) throw new Error("Pictometry mount is missing an id.");
        this.host = new global.PictometryHost(mountId, this.endpoint);
        this._call(["setPreferences"], { enableSynchronization: true, imageDownload: false });
        this._update({ state: "ready", sessionAvailable: true, message: "Pictometry adapter initialized" });
      } catch (error) {
        this._update({ state: "error", sessionAvailable: false, message: safeError(error) });
      }
      return this.getStatus();
    }

    setParcel(latitude, longitude, parcelId) {
      const lat = Number(latitude);
      const lon = Number(longitude);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
        this._update({ state: "error", message: "A valid EPSG:4326 latitude/longitude pair is required." });
        return false;
      }
      this._update({ parcelId: parcelId || "", latitude: lat, longitude: lon });
      if (!this.host) return false;
      const ok = this._call(["setLocation"], lat, lon, 18);
      if (!ok) this._update({ state: "error", message: "The supported host does not expose setLocation." });
      return ok;
    }

    setOrientation(orientation) {
      const value = String(orientation || "").toUpperCase();
      if (!ORIENTATIONS.has(value)) return false;
      this._update({ orientation: value });
      if (!this.host) return false;
      const degrees = { N: 0, E: 90, S: 180, W: 270 }[value];
      const ok = this._call(["setOrientation", "setHeading"], value) || this._call(["setPreferences"], { orientation: value, heading: degrees });
      if (!ok) this._update({ message: "The host is initialized, but orientation control is unavailable." });
      return ok;
    }

    setYear(year) {
      const value = Number(year);
      if (!YEARS.has(value)) return false;
      this._update({ year: value });
      if (!this.host) return false;
      const ok = this._call(["setYear", "setCollection", "selectYear"], value) || this._call(["setPreferences"], { year: value, collection: `WASKAG${String(value).slice(-2)}` });
      if (!ok) this._update({ message: "The host is initialized, but explicit year selection is unavailable." });
      return ok;
    }

    isAvailable() {
      return this.status.state === "ready";
    }

    openGeoSkagit() {
      global.open(this.countyHost + this.viewerPath, "_blank", "noopener,noreferrer");
    }

    getStatus() {
      return { ...this.status };
    }

    destroy() {
      try { this._call(["destroy", "close"]); } catch (error) { /* provider cleanup is best effort */ }
      this.host = null;
      this._update({ state: "idle", message: "Destroyed" });
    }
  }

  function probeCountyPage(options) {
    const settings = options || {};
    const host = String(settings.countyHost || DEFAULT_HOST).replace(/\/$/, "");
    const path = settings.path || "/Html5ViewerProd/Resources/3rdPartyMaps/Pictometry.aspx";
    const timeoutMs = Number(settings.timeoutMs || 10000);
    return new Promise(resolve => {
      const frame = document.createElement("iframe");
      frame.title = "Pictometry integration probe";
      frame.hidden = true;
      frame.src = host + path;
      let finished = false;
      const finish = result => {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        frame.remove();
        resolve({ ...result, host, path, origin: global.location.origin });
      };
      const timer = setTimeout(() => finish({ state: "timeout", message: "County Pictometry page did not load within the probe window." }), timeoutMs);
      frame.addEventListener("load", () => finish({ state: "loaded", message: "County Pictometry page loaded; cross-origin viewer controls remain intentionally inaccessible." }), { once: true });
      frame.addEventListener("error", () => finish({ state: "error", message: "County Pictometry page failed to load." }), { once: true });
      document.body.appendChild(frame);
    });
  }

  global.PictometryAdapter = PictometryAdapter;
  global.probePictometryCountyPage = probeCountyPage;
})(window);
