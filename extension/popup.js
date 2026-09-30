const HELPER_URL = "http://127.0.0.1:47821";
const token = globalThis.HELPER_TOKEN;

const titleElement = document.querySelector("#video-title");
const urlInput = document.querySelector("#media-url");
const folderElements = {
  mp3: document.querySelector("#mp3-folder-path"),
  mp4: document.querySelector("#mp4-folder-path")
};
const folderButtons = [...document.querySelectorAll(".folder-button")];
const downloadButtons = [...document.querySelectorAll(".download-button")];
const progressWrap = document.querySelector("#progress-wrap");
const progressBar = document.querySelector("#progress-bar");
const progressText = document.querySelector("#progress-text");
const statusElement = document.querySelector("#status");

let currentUrl = "";
const destinations = { mp3: "", mp4: "" };
let pollTimer = null;

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

function setBusy(busy) {
  folderButtons.forEach((button) => { button.disabled = busy; });
  const type = mediaType(currentUrl);
  downloadButtons.forEach((button) => {
    button.disabled = busy || !currentUrl || (type === "sound" && button.dataset.format === "mp4");
  });
}

async function helperRequest(path, options = {}) {
  const response = await fetch(`${HELPER_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Helper-Token": token,
      ...(options.headers || {})
    }
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Helper error (${response.status})`);
  return body;
}

function mediaType(url) {
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
        ["vm.tiktok.com", "vt.tiktok.com"].includes(hostname));
    const tiktokSound = tiktokSite && parsed.pathname.includes("/music/");
    if (tiktokSound) return "sound";
    if (youtubeVideo || youtubeShortLink || tiktokMedia) return "video";
    return "";
  } catch {
    return "";
  }
}

function useUrl(value, announce = true) {
  const candidate = value.trim();
  const type = mediaType(candidate);
  currentUrl = type ? candidate : "";
  downloadButtons.forEach((button) => {
    button.disabled = !currentUrl || (type === "sound" && button.dataset.format === "mp4");
  });
  if (!announce) return;
  if (type === "sound") {
    setStatus("TikTok sound link ready — choose MP3.", "success");
  } else if (type === "video") {
    setStatus("Link ready.", "success");
  } else {
    setStatus("Paste a YouTube or TikTok video or sound link.", "error");
  }
}

async function initialize() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  titleElement.textContent = tab?.title?.replace(/ - YouTube$/, "") || "Current video";
  const tabUrl = tab?.url || "";
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
      : "Paste a YouTube or TikTok link below.");
  }

  const cached = await chrome.storage.local.get(["mp3Destination", "mp4Destination"]);
  for (const format of ["mp3", "mp4"]) {
    showDestination(format, cached[`${format}Destination`] || "");
  }

  try {
    const state = await helperRequest("/state");
    for (const format of ["mp3", "mp4"]) {
      const savedDestination = state[`${format}_destination`] || destinations[format];
      if (savedDestination) {
        showDestination(format, savedDestination);
        await rememberDestination(format, savedDestination);
      }
    }
    if (state.active_job) trackJob(state.active_job);
    if (state.update) {
      setStatus(`Downloadable ${state.update.version} is ready. Restart the helper to apply it.`, "success");
    }
  } catch (error) {
    setStatus(error.message || "Could not connect to the local helper.", "error");
  }
}

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
      setStatus("Paste a supported link first.", "error");
      return;
    }
    if (mediaType(currentUrl) === "sound" && format === "mp4") {
      setStatus("TikTok sound links are audio-only; choose MP3.", "error");
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
        body: JSON.stringify({ url: currentUrl, format, destination: destinations[format] })
      });
      trackJob(result.job_id);
    } catch (error) {
      setBusy(false);
      setStatus(error.message, "error");
    }
  });
});

function trackJob(jobId) {
  clearTimeout(pollTimer);
  setBusy(true);
  progressWrap.hidden = false;

  const poll = async () => {
    try {
      const job = await helperRequest(`/jobs/${jobId}`);
      const percent = Math.max(0, Math.min(100, Number(job.progress) || 0));
      progressBar.style.width = `${percent}%`;
      progressText.textContent = job.message || `${percent.toFixed(1)}%`;

      if (job.status === "complete") {
        setBusy(false);
        setStatus(`Saved: ${job.filename}`, "success");
        return;
      }
      if (job.status === "error") {
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
