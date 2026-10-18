const HELPER_URL = globalThis.HELPER_URL || "http://127.0.0.1:47821";
const token = globalThis.HELPER_TOKEN;

const titleElement = document.querySelector("#video-title");
const urlInput = document.querySelector("#media-url");
const folderElements = {
  mp3: document.querySelector("#mp3-folder-path"),
  mp4: document.querySelector("#mp4-folder-path"),
  png: document.querySelector("#png-folder-path")
};
const folderButtons = [...document.querySelectorAll(".folder-button")];
const downloadButtons = [...document.querySelectorAll(".download-button")];
const progressWrap = document.querySelector("#progress-wrap");
const progressBar = document.querySelector("#progress-bar");
const progressText = document.querySelector("#progress-text");
const statusElement = document.querySelector("#status");
const settingsButton = document.querySelector("#settings-button");
const settingsPanel = document.querySelector("#settings-panel");
const helperStatus = document.querySelector("#helper-status");
const reconnectButton = document.querySelector("#reconnect-button");
const resetFoldersButton = document.querySelector("#reset-folders-button");
const openLogsButton = document.querySelector("#open-logs-button");
const extensionsButton = document.querySelector("#extensions-button");
const checkUpdateButton = document.querySelector("#check-update-button");
const restartUpdateButton = document.querySelector("#restart-update-button");
const repairSetupButton = document.querySelector("#repair-setup-button");
const updateStatus = document.querySelector("#update-status");
const cancelButton = document.querySelector("#cancel-button");
const firstRun = document.querySelector("#first-run");
const readmeConfirm = document.querySelector("#readme-confirm");
const continueButton = document.querySelector("#continue-button");

let currentUrl = "";
let currentTitle = "";
const destinations = { mp3: "", mp4: "", png: "" };
let pollTimer = null;
let helperConnected = false;
let activeJobId = null;

async function initializeFirstRun() {
  const { readmeAcknowledged } = await chrome.storage.local.get("readmeAcknowledged");
  firstRun.hidden = Boolean(readmeAcknowledged);
}

function showDestination(format, destination) {
  destinations[format] = destination || "";
  folderElements[format].textContent = destination || "No folder selected";
  folderElements[format].title = destination || "";
}

async function rememberDestination(format, destination) {
  await chrome.storage.local.set({ [`${format}Destination`]: destination });
}

function setStatus(message, kind = "") {
  statusElement.textContent = message;
  statusElement.className = `status ${kind}`;
}

function setHelperStatus(connected, message = "") {
  helperConnected = connected;
  helperStatus.textContent = message || (connected ? "Connected" : "Not connected");
  helperStatus.className = connected ? "connected" : "failed";
  reconnectButton.disabled = false;
}

function showUpdateStatus(update, version = "") {
  if (update?.version) {
    updateStatus.textContent = `Downloadable ${update.version} is ready. Restart the helper to apply it.`;
    updateStatus.className = "update-status ready";
    restartUpdateButton.hidden = false;
    return;
  }
  restartUpdateButton.hidden = true;
  updateStatus.textContent = version ? `Downloadable ${version} is up to date.` : "Update checks run automatically every hour.";
  updateStatus.className = "update-status";
}

function setBusy(busy) {
  folderButtons.forEach((button) => { button.disabled = busy; });
  const type = mediaType(currentUrl);
  downloadButtons.forEach((button) => {
    button.disabled = busy || !currentUrl || (type === "sound" && button.dataset.format === "mp4");
  });
}

function setPhotoMode(photo) {
  document.querySelectorAll(".photo-only").forEach((element) => {
    element.hidden = !photo;
  });
  document.querySelector(".mp4").hidden = photo;
}

async function helperRequest(path, options = {}) {
  if (!token) throw new Error("Helper is not configured. Run Downloadable.cmd, then reload the extension.");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  let response;
  try {
    response = await fetch(`${HELPER_URL}${path}`, {
      ...options,
      signal: controller.signal,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Helper-Token": token,
        ...(options.headers || {})
      }
    });
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The local helper did not respond. Open Settings and choose Reconnect.");
    throw new Error("Could not reach the local helper. Make sure Downloadable.cmd completed.");
  } finally {
    clearTimeout(timeout);
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Helper error (${response.status})`);
  return body;
}

async function connectHelper(showMessage = true) {
  helperStatus.textContent = "Checking…";
  helperStatus.className = "";
  try {
    const state = await helperRequest("/state");
    setHelperStatus(true);
    if (showMessage) setStatus("Local helper connected.", "success");
    return state;
  } catch (error) {
    setHelperStatus(false, error.message);
    if (showMessage) setStatus(error.message, "error");
    throw error;
  }
}

function mediaType(url, allowGeneric = true) {
  try {
    const parsed = new URL(url);
    const hostname = parsed.hostname.toLowerCase();
    const youtubeSite = hostname === "youtube.com" || hostname.endsWith(".youtube.com");
    const youtubeVideo = youtubeSite &&
      (parsed.pathname === "/watch" ||
        parsed.pathname.startsWith("/shorts/") ||
        parsed.pathname.startsWith("/live/") ||
        parsed.pathname.startsWith("/embed/"));
    const youtubeShortLink = hostname === "youtu.be" && parsed.pathname.length > 1;
    const tiktokSite = hostname === "tiktok.com" || hostname.endsWith(".tiktok.com");
    const tiktokMedia = tiktokSite &&
      (parsed.pathname.includes("/video/") ||
        parsed.pathname.includes("/photo/") ||
        ["vm.tiktok.com", "vt.tiktok.com"].includes(hostname) ||
        ((hostname === "tiktok.com" || hostname === "www.tiktok.com") &&
          (parsed.pathname.startsWith("/t/") || parsed.pathname.startsWith("/v/"))));
    const tiktokPhoto = tiktokSite && parsed.pathname.includes("/photo/");
    const tiktokSound = tiktokSite && parsed.pathname.includes("/music/");
    if (tiktokSound) return "sound";
    if (tiktokPhoto) return "photo";
    if (youtubeVideo || youtubeShortLink || tiktokMedia) return "video";
    if (allowGeneric && parsed.protocol === "https:" && parsed.hostname) return "video";
    return "";
  } catch {
    return "";
  }
}

function tabVideoTitle(tab) {
  const rawTitle = String(tab?.title || "").trim();
  if (!rawTitle) return "";
  let hostname = "";
  try {
    hostname = new URL(tab?.url || "").hostname.toLowerCase();
  } catch {
    // Keep the browser title as the best available fallback.
  }
  let title = rawTitle;
  if (hostname === "youtube.com" || hostname.endsWith(".youtube.com")) {
    title = title.replace(/\s+-\s+YouTube(?:\s+Music)?\s*$/i, "").trim();
  } else if (hostname === "tiktok.com" || hostname.endsWith(".tiktok.com")) {
    title = title.replace(/\s+(?:\||-|–)\s*TikTok\s*$/i, "").trim();
    if (/^TikTok(?:\s*-\s*Make Your Day)?$/i.test(title)) title = "";
  }
  return title;
}

function useUrl(value, announce = true) {
  const candidate = value.trim();
  const type = mediaType(candidate);
  currentUrl = type ? candidate : "";
  setPhotoMode(type === "photo");
  downloadButtons.forEach((button) => {
    button.disabled = !currentUrl || type === "sound";
  });
  if (!announce) return;
  if (type === "sound") {
    setStatus("Open a TikTok video using this sound, then choose MP3.", "error");
  } else if (type === "video" || type === "photo") {
    setStatus("Link ready.", "success");
  } else {
    setStatus("Paste a supported HTTPS media link.", "error");
  }
}

async function initialize() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentTitle = tabVideoTitle(tab) || "Current video";
  titleElement.textContent = currentTitle;
  const tabUrl = tab?.url || "";
  // yt-dlp supports far more than the two sites with special UI behavior.
  // Treat any normal HTTPS tab as a candidate and let yt-dlp be the final
  // authority when the download starts.
  if (mediaType(tabUrl)) {
    urlInput.value = tabUrl;
    useUrl(tabUrl, false);
  } else {
    useUrl("", false);
    let isTikTokFeed = false;
    try {
      const hostname = new URL(tabUrl).hostname.toLowerCase();
      isTikTokFeed = hostname === "tiktok.com" || hostname.endsWith(".tiktok.com");
    } catch {
      isTikTokFeed = false;
    }
    setStatus(isTikTokFeed
      ? "TikTok feed: open the video's comments, then reopen this popup—or paste its Share link."
      : "Paste a yt-dlp-supported HTTPS media link below.");
  }

  const cached = await chrome.storage.local.get(["mp3Destination", "mp4Destination", "pngDestination"]);
  for (const format of ["mp3", "mp4", "png"]) {
    showDestination(format, cached[`${format}Destination`] || "");
  }

  try {
    const state = await connectHelper(false);
    for (const format of ["mp3", "mp4", "png"]) {
      const savedDestination = state[`${format}_destination`] || destinations[format];
      if (savedDestination) {
        showDestination(format, savedDestination);
        await rememberDestination(format, savedDestination);
      }
    }
    if (state.active_job) trackJob(state.active_job);
    showUpdateStatus(state.update, state.version);
    if (state.update) setStatus(`Downloadable ${state.update.version} is ready. Restart the helper to apply it.`, "success");
  } catch (error) {
    setStatus(error.message || "Could not connect to the local helper.", "error");
  }
}

settingsButton.addEventListener("click", () => {
  const open = settingsPanel.hidden;
  settingsPanel.hidden = !open;
  settingsButton.setAttribute("aria-expanded", String(open));
});

reconnectButton.addEventListener("click", async () => {
  reconnectButton.disabled = true;
  try {
    const state = await connectHelper(true);
    if (state.active_job) trackJob(state.active_job);
  } catch (_) {
    // connectHelper already explains the failure in the popup.
  } finally {
    reconnectButton.disabled = false;
  }
});

resetFoldersButton.addEventListener("click", async () => {
  resetFoldersButton.disabled = true;
  try {
    await helperRequest("/reset-settings", { method: "POST", body: "{}" });
    for (const format of ["mp3", "mp4", "png"]) {
      showDestination(format, "");
      await rememberDestination(format, "");
    }
    setStatus("Saved folders cleared.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    resetFoldersButton.disabled = false;
  }
});

openLogsButton.addEventListener("click", async () => {
  openLogsButton.disabled = true;
  try {
    await helperRequest("/open-logs", { method: "POST", body: "{}" });
    setStatus("Error log folder opened.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    openLogsButton.disabled = false;
  }
});

checkUpdateButton.addEventListener("click", async () => {
  checkUpdateButton.disabled = true;
  updateStatus.textContent = "Checking for updates…";
  updateStatus.className = "update-status";
  try {
    const result = await helperRequest("/check-update", { method: "POST", body: "{}" });
    showUpdateStatus(result.status === "staged" ? result : null, result.current || "");
    setStatus(result.status === "staged" ? `Downloadable ${result.version} is ready. Restart the helper to apply it.` : "Downloadable is up to date.", "success");
  } catch (error) {
    updateStatus.textContent = "Update check failed.";
    updateStatus.className = "update-status failed";
    setStatus(error.message, "error");
  } finally {
    checkUpdateButton.disabled = false;
  }
});

restartUpdateButton.addEventListener("click", async () => {
  restartUpdateButton.disabled = true;
  setStatus("Restarting the helper and applying the update…");
  try {
    await helperRequest("/restart", { method: "POST", body: "{}" });
    updateStatus.textContent = "Update applied. Reconnecting…";
    updateStatus.className = "update-status ready";
    setTimeout(async () => {
      try {
        const state = await connectHelper(false);
        showUpdateStatus(state.update, state.version);
        setStatus("Downloadable is up to date.", "success");
      } catch (_) {
        // The helper may need another moment to come back after task restart.
      }
    }, 2200);
  } catch (error) {
    restartUpdateButton.disabled = false;
    setStatus(error.message, "error");
  }
});

repairSetupButton.addEventListener("click", async () => {
  repairSetupButton.disabled = true;
  try {
    await helperRequest("/repair-setup", { method: "POST", body: "{}" });
    setStatus("Setup opened. Follow its prompts to repair Downloadable.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    repairSetupButton.disabled = false;
  }
});

cancelButton.addEventListener("click", async () => {
  if (!activeJobId) return;
  cancelButton.disabled = true;
  try {
    await helperRequest(`/jobs/${activeJobId}/cancel`, { method: "POST", body: "{}" });
    setStatus("Cancel requested…");
  } catch (error) {
    cancelButton.disabled = false;
    setStatus(error.message, "error");
  }
});

extensionsButton.addEventListener("click", () => {
  chrome.tabs.create({ url: "chrome://extensions" });
});

urlInput.addEventListener("input", () => useUrl(urlInput.value));

folderButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    const format = button.dataset.format;
    setStatus(`Opening ${format.toUpperCase()} folder picker…`);
    try {
      const result = await helperRequest("/choose-folder", {
        method: "POST",
        body: JSON.stringify({ format })
      });
      showDestination(format, result.destination);
      await rememberDestination(format, result.destination);
      setStatus(`${format.toUpperCase()} folder selected.`, "success");
    } catch (error) {
      setStatus(error.message, "error");
    }
  });
});

downloadButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    const format = button.dataset.format;
    if (!currentUrl) {
      setStatus("Paste a supported HTTPS media link first.", "error");
      return;
    }
    if (mediaType(currentUrl) === "sound") {
      setStatus("Sound pages cannot be downloaded directly. Open a video using this sound, then choose MP3.", "error");
      return;
    }
    if (!destinations[format]) {
      setStatus(`Choose an ${format.toUpperCase()} destination folder first.`, "error");
      return;
    }

    setBusy(true);
    setStatus("Sending download to helper…");
    try {
      const result = await helperRequest("/download", {
        method: "POST",
        body: JSON.stringify({ url: currentUrl, format, destination: destinations[format], title: currentTitle })
      });
      trackJob(result.job_id);
    } catch (error) {
      setBusy(false);
      setStatus(error.message, "error");
    }
  });
});

function trackJob(jobId) {
  activeJobId = jobId;
  clearTimeout(pollTimer);
  setBusy(true);
  progressWrap.hidden = false;
  cancelButton.hidden = false;
  cancelButton.disabled = false;

  const poll = async () => {
    try {
      const job = await helperRequest(`/jobs/${jobId}`);
      const percent = Math.max(0, Math.min(100, Number(job.progress) || 0));
      progressBar.style.width = `${percent}%`;
      progressText.textContent = job.message || `${percent.toFixed(1)}%`;

      if (job.status === "complete") {
        activeJobId = null;
        cancelButton.hidden = true;
        setBusy(false);
        setStatus(`Saved: ${job.filename}`, "success");
        return;
      }
      if (job.status === "error") {
        activeJobId = null;
        cancelButton.hidden = true;
        setBusy(false);
        setStatus(job.error || "Download failed.", "error");
        return;
      }
      pollTimer = setTimeout(poll, 700);
    } catch (error) {
      setBusy(false);
      setStatus(error.message, "error");
    }
  };
  poll();
}

initialize();
initializeFirstRun();

readmeConfirm.addEventListener("change", () => {
  continueButton.disabled = !readmeConfirm.checked;
});

continueButton.addEventListener("click", async () => {
  if (!readmeConfirm.checked) return;
  await chrome.storage.local.set({ readmeAcknowledged: true });
  firstRun.hidden = true;
});
