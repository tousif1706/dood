import { initializeApp } from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import {
  getAuth,
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithPopup,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js";

const SCOPES = ["https://www.googleapis.com/auth/drive.readonly"];
const CODE_EXT_RE = /\.(py|pyw|cpp|cc|cxx|hpp|hh|hxx|h|java|js|mjs|cjs)$/i;

let firebaseAuth = null;
let googleProvider = null;
let isSigningIn = false;
let cachedAccessToken = null;
let currentUserEmail = "";
let driveFilesCache = [];
const selectedDriveIds = new Set();

function qs(id) {
  return document.getElementById(id);
}

function escapeText(value) {
  const div = document.createElement("div");
  div.textContent = String(value ?? "");
  return div.innerHTML;
}

function updateEditorGutterLive() {
  const textarea = qs("code-textarea");
  const gutter = qs("line-gutter");
  const meta = qs("editor-meta");
  const form = qs("workbench-form");
  if (!textarea || !gutter || !meta || !form) return;

  const code = textarea.value;
  const lines = code.replace(/\r\n/g, "\n").split("\n");
  const lang = form.elements.namedItem("language")?.value || "Python";
  meta.textContent = `${lang} · ${lines.length} ${lines.length === 1 ? "line" : "lines"} · ${code.length} chars`;

  const hl = Number(form.elements.namedItem("highlighted_line")?.value || 0);
  gutter.innerHTML = lines
    .map(
      (_, i) =>
        `<div class="${hl === i + 1 ? "gutter-line is-highlighted" : "gutter-line"}">${i + 1}</div>`
    )
    .join("");
}

function applyFragments(frag) {
  const form = qs("workbench-form");
  if (!form || !frag) return;

  const setHidden = (name, val) => {
    const el = form.elements.namedItem(name);
    if (el) el.value = val ?? "";
  };

  setHidden("session_id", frag.session_id);
  setHidden("language", frag.language);
  setHidden("active_tab", frag.active_tab);
  setHidden("expanded_bug", frag.expanded_bug);
  setHidden("highlighted_line", frag.highlighted_line);

  if (qs("hero-active-language")) {
    qs("hero-active-language").textContent = frag.language;
  }
  if (qs("language-selector") && frag.language_buttons !== undefined) {
    qs("language-selector").innerHTML = frag.language_buttons;
  }
  if (qs("editor-meta") && frag.editor_meta !== undefined) {
    qs("editor-meta").textContent = frag.editor_meta;
  }
  if (qs("line-gutter") && frag.line_gutter !== undefined) {
    qs("line-gutter").innerHTML = frag.line_gutter;
  }
  if (qs("code-textarea") && frag.code !== undefined) {
    qs("code-textarea").value = frag.code;
  }
  if (qs("attached-files-container") && frag.attached_files_html !== undefined) {
    qs("attached-files-container").innerHTML = frag.attached_files_html;
  }
  if (qs("clear-results-btn")) {
    qs("clear-results-btn").classList.toggle("hidden", frag.clear_hidden === "hidden");
  }
  if (qs("results-panel") && frag.results_html !== undefined) {
    qs("results-panel").innerHTML = frag.results_html;
  }
}

function applyHtmlDocument(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const nextForm = doc.getElementById("workbench-form");
  const curForm = qs("workbench-form");
  if (!nextForm || !curForm) return;

  const nextData = new FormData(nextForm);
  applyFragments({
    session_id: nextData.get("session_id"),
    language: nextData.get("language"),
    active_tab: nextData.get("active_tab"),
    expanded_bug: nextData.get("expanded_bug"),
    highlighted_line: nextData.get("highlighted_line"),
    language_buttons: doc.getElementById("language-selector")?.innerHTML,
    editor_meta: doc.getElementById("editor-meta")?.textContent,
    line_gutter: doc.getElementById("line-gutter")?.innerHTML,
    code: doc.getElementById("code-textarea")?.value,
    attached_files_html: doc.getElementById("attached-files-container")?.innerHTML,
    clear_hidden: doc.getElementById("clear-results-btn")?.classList.contains("hidden")
      ? "hidden"
      : "",
    results_html: doc.getElementById("results-panel")?.innerHTML,
  });

  const presetSelect = qs("preset-select");
  if (presetSelect) presetSelect.selectedIndex = 0;
}

async function loadImportedFiles(files) {
  const form = qs("workbench-form");
  const sessionId = form?.elements.namedItem("session_id")?.value || "";

  const res = await fetch("/api/analyze-files", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      append: true,
      auto_review: false,
      files,
    }),
  });

  const payload = await res.json();
  if (!res.ok) {
    throw new Error(payload.error || "Could not load selected files.");
  }

  applyFragments(payload);
}

async function handleLocalFileList(fileList) {
  const files = Array.from(fileList || []).slice(0, 20);
  if (!files.length) return;

  const prepared = [];
  for (const file of files) {
    if (file.size > 512 * 1024) {
      continue;
    }
    const text = await file.text();
    if (text.trim()) {
      prepared.push({
        name: file.name,
        source: "local",
        code: text,
      });
    }
  }

  if (!prepared.length) {
    const resultsPanel = qs("results-panel");
    if (resultsPanel) {
      resultsPanel.innerHTML =
        '<div class="results-error"><h2 class="error-title">No readable code files found</h2>' +
        '<p class="error-message">Please upload non-empty Python (.py), C++ (.cpp), Java (.java), or JavaScript (.js) files under 512 KB.</p></div>';
    }
    return;
  }

  try {
    await loadImportedFiles(prepared);
  } catch (err) {
    const resultsPanel = qs("results-panel");
    if (resultsPanel) {
      resultsPanel.innerHTML = `<div class="results-error"><h2 class="error-title">Unsupported language or file</h2><p class="error-message">${escapeText(err.message)}</p></div>`;
    }
  }
}

async function ensureFirebaseAuth() {
  if (firebaseAuth) return firebaseAuth;

  const res = await fetch("/firebase-config.json");
  if (!res.ok) {
    throw new Error("Google Drive integration is not configured yet.");
  }
  const config = await res.json();
  const app = initializeApp(config);
  firebaseAuth = getAuth(app);
  googleProvider = new GoogleAuthProvider();
  for (const scope of SCOPES) {
    googleProvider.addScope(scope);
  }

  onAuthStateChanged(firebaseAuth, (user) => {
    if (user && cachedAccessToken) {
      currentUserEmail = user.email || user.displayName || "Connected";
      syncDriveModalView();
    } else if (!isSigningIn) {
      cachedAccessToken = null;
      currentUserEmail = user ? user.email || "" : "";
      syncDriveModalView();
    }
  });

  return firebaseAuth;
}

function syncDriveModalView() {
  const authView = qs("drive-auth-view");
  const browserView = qs("drive-browser-view");
  const emailEl = qs("drive-user-email");
  if (!authView || !browserView) return;

  const hasToken = Boolean(cachedAccessToken);
  authView.classList.toggle("hidden", hasToken);
  browserView.classList.toggle("hidden", !hasToken);
  if (emailEl) {
    emailEl.textContent = currentUserEmail
      ? `Connected as ${currentUserEmail}`
      : "Connected to Google Drive";
  }
}

function showDriveStatus(message, isError = false) {
  const el = qs("drive-status-msg");
  if (!el) return;
  if (!message) {
    el.classList.add("hidden");
    el.textContent = "";
    el.classList.remove("drive-status-error");
    return;
  }
  el.textContent = message;
  el.classList.remove("hidden");
  el.classList.toggle("drive-status-error", isError);
}

function updateSelectedDriveCount() {
  const countEl = qs("drive-selected-count");
  const importBtn = qs("drive-import-btn");
  const count = selectedDriveIds.size;
  if (countEl) {
    countEl.textContent = `${count} file${count === 1 ? "" : "s"} selected`;
  }
  if (importBtn) {
    importBtn.disabled = count === 0;
  }
}

function renderDriveFiles(files) {
  const listEl = qs("drive-file-list");
  if (!listEl) return;

  if (!files.length) {
    listEl.innerHTML =
      '<div class="drive-empty-state">No matching files found in your Google Drive.</div>';
    return;
  }

  listEl.innerHTML = files
    .map((file) => {
      const checked = selectedDriveIds.has(file.id) ? "checked" : "";
      const isDoc = file.mimeType === "application/vnd.google-apps.document";
      const sizeKb = file.size
        ? `${Math.max(1, Math.round(Number(file.size) / 1024))} KB`
        : isDoc
          ? "Google Doc"
          : "";
      const mod = file.modifiedTime
        ? new Date(file.modifiedTime).toLocaleDateString()
        : "";
      const meta = [sizeKb, mod].filter(Boolean).join(" · ");

      return (
        `<label class="drive-file-row">` +
        `<span class="drive-file-left">` +
        `<input type="checkbox" class="drive-file-checkbox" data-file-id="${escapeText(file.id)}" ${checked} />` +
        `<span class="drive-file-name">${escapeText(file.name)}</span>` +
        `</span>` +
        `<span class="drive-file-meta tabular-nums">${escapeText(meta)}</span>` +
        `</label>`
      );
    })
    .join("");
}

async function fetchDriveFiles() {
  if (!cachedAccessToken) {
    syncDriveModalView();
    return;
  }

  const queryText = (qs("drive-search-input")?.value || "").trim();
  const codeOnly = Boolean(qs("drive-code-only")?.checked);
  const clauses = ["trashed = false", "mimeType != 'application/vnd.google-apps.folder'"];

  if (queryText) {
    const escaped = queryText.replace(/'/g, "\\'");
    clauses.push(`name contains '${escaped}'`);
  }

  showDriveStatus("Loading files from Google Drive...");
  try {
    const url = new URL("https://www.googleapis.com/drive/v3/files");
    url.searchParams.set("pageSize", "50");
    url.searchParams.set("fields", "files(id,name,mimeType,modifiedTime,size)");
    url.searchParams.set("orderBy", "modifiedTime desc");
    url.searchParams.set("q", clauses.join(" and "));

    const res = await fetch(url.toString(), {
      headers: { Authorization: `Bearer ${cachedAccessToken}` },
    });

    if (res.status === 401) {
      cachedAccessToken = null;
      syncDriveModalView();
      showDriveStatus("Your Google Drive session expired. Please sign in again.", true);
      return;
    }

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error?.message || "Failed to list Google Drive files.");
    }

    let files = data.files || [];
    if (codeOnly) {
      files = files.filter(
        (f) =>
          CODE_EXT_RE.test(f.name || "") ||
          f.mimeType === "application/vnd.google-apps.document"
      );
    }

    driveFilesCache = files;
    selectedDriveIds.clear();
    updateSelectedDriveCount();
    renderDriveFiles(files);
    showDriveStatus("");
  } catch (err) {
    showDriveStatus(err.message || "Error loading Google Drive files.", true);
  }
}

async function importSelectedDriveFiles() {
  if (!cachedAccessToken || selectedDriveIds.size === 0) return;

  const importBtn = qs("drive-import-btn");
  if (importBtn) {
    importBtn.disabled = true;
    importBtn.textContent = "Loading...";
  }
  showDriveStatus("Downloading selected files from Google Drive...");

  try {
    const chosen = driveFilesCache.filter((f) => selectedDriveIds.has(f.id));
    const prepared = [];

    for (const file of chosen) {
      const isGoogleDoc = file.mimeType === "application/vnd.google-apps.document";
      const downloadUrl = isGoogleDoc
        ? `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(file.id)}/export?mimeType=text/plain`
        : `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(file.id)}?alt=media`;

      const res = await fetch(downloadUrl, {
        headers: { Authorization: `Bearer ${cachedAccessToken}` },
      });
      if (!res.ok) {
        throw new Error(`Could not read "${file.name}" from Google Drive.`);
      }
      const text = await res.text();
      if (text.trim()) {
        prepared.push({
          name: isGoogleDoc && !CODE_EXT_RE.test(file.name) ? `${file.name}.txt` : file.name,
          source: "drive",
          code: text,
        });
      }
    }

    if (!prepared.length) {
      showDriveStatus("Selected Drive files were empty.", true);
      return;
    }

    await loadImportedFiles(prepared);
    closeDriveModal();
  } catch (err) {
    showDriveStatus(err.message || "Failed to import Drive files.", true);
  } finally {
    if (importBtn) {
      importBtn.textContent = "Import to Editor";
      updateSelectedDriveCount();
    }
  }
}

async function openDriveModal() {
  const modal = qs("drive-modal");
  if (!modal) return;
  modal.classList.remove("hidden");
  qs("drive-auth-error")?.classList.add("hidden");
  showDriveStatus("");

  try {
    await ensureFirebaseAuth();
    syncDriveModalView();
    if (cachedAccessToken) {
      await fetchDriveFiles();
    }
  } catch (err) {
    const errEl = qs("drive-auth-error");
    if (errEl) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    }
  }
}

function closeDriveModal() {
  qs("drive-modal")?.classList.add("hidden");
}

function closeOptionsPopover() {
  const popover = qs("options-popover");
  const btn = qs("options-menu-btn");
  if (popover) popover.classList.add("hidden");
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function setupEvents() {
  const optionsBtn = qs("options-menu-btn");
  const optionsPopover = qs("options-popover");
  const uploadOption = qs("opt-upload-library");
  const driveOption = qs("opt-google-drive");
  const sampleOption = qs("opt-sample-preset");
  const libraryInput = qs("library-file-input");
  const editorBody = document.querySelector(".editor-body");
  const textarea = qs("code-textarea");
  const form = qs("workbench-form");

  // Options menu toggle
  optionsBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    const isHidden = optionsPopover?.classList.contains("hidden");
    if (isHidden) {
      optionsPopover.classList.remove("hidden");
      optionsBtn.setAttribute("aria-expanded", "true");
    } else {
      closeOptionsPopover();
    }
  });

  document.addEventListener("click", (e) => {
    if (
      optionsPopover &&
      !optionsPopover.classList.contains("hidden") &&
      !optionsPopover.contains(e.target) &&
      !optionsBtn?.contains(e.target)
    ) {
      closeOptionsPopover();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeOptionsPopover();
      closeDriveModal();
    }
  });

  // Upload from local Library / Device
  uploadOption?.addEventListener("click", () => {
    closeOptionsPopover();
    libraryInput?.click();
  });

  libraryInput?.addEventListener("change", async (e) => {
    const input = e.target;
    await handleLocalFileList(input.files);
    input.value = "";
  });

  // Drag & drop files directly onto editor
  if (editorBody) {
    editorBody.addEventListener("dragover", (e) => {
      if (e.dataTransfer?.types?.includes("Files")) {
        e.preventDefault();
        editorBody.classList.add("is-drag-over");
      }
    });
    editorBody.addEventListener("dragleave", () => {
      editorBody.classList.remove("is-drag-over");
    });
    editorBody.addEventListener("drop", async (e) => {
      if (e.dataTransfer?.files?.length) {
        e.preventDefault();
        editorBody.classList.remove("is-drag-over");
        await handleLocalFileList(e.dataTransfer.files);
      }
    });
  }

  sampleOption?.addEventListener("click", () => {
    closeOptionsPopover();
  });

  // Import from Google Drive
  driveOption?.addEventListener("click", () => {
    closeOptionsPopover();
    openDriveModal();
  });

  qs("drive-modal-close")?.addEventListener("click", closeDriveModal);
  qs("drive-cancel-btn")?.addEventListener("click", closeDriveModal);
  qs("drive-modal")?.addEventListener("click", (e) => {
    if (e.target === qs("drive-modal")) closeDriveModal();
  });

  qs("google-signin-btn")?.addEventListener("click", async () => {
    const errEl = qs("drive-auth-error");
    errEl?.classList.add("hidden");
    try {
      const auth = await ensureFirebaseAuth();
      isSigningIn = true;
      const result = await signInWithPopup(auth, googleProvider);
      const credential = GoogleAuthProvider.credentialFromResult(result);
      if (!credential?.accessToken) {
        throw new Error("Could not retrieve Google Drive access token.");
      }
      cachedAccessToken = credential.accessToken;
      currentUserEmail = result.user?.email || result.user?.displayName || "";
      syncDriveModalView();
      await fetchDriveFiles();
    } catch (err) {
      if (errEl) {
        errEl.textContent = err.message || "Google sign-in failed.";
        errEl.classList.remove("hidden");
      }
    } finally {
      isSigningIn = false;
    }
  });

  qs("drive-signout-btn")?.addEventListener("click", async () => {
    if (firebaseAuth) {
      await firebaseAuth.signOut();
    }
    cachedAccessToken = null;
    currentUserEmail = "";
    driveFilesCache = [];
    selectedDriveIds.clear();
    updateSelectedDriveCount();
    syncDriveModalView();
  });

  qs("drive-search-btn")?.addEventListener("click", fetchDriveFiles);
  qs("drive-code-only")?.addEventListener("change", fetchDriveFiles);
  qs("drive-search-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      fetchDriveFiles();
    }
  });

  qs("drive-file-list")?.addEventListener("change", (e) => {
    const target = e.target;
    if (!target.classList?.contains("drive-file-checkbox")) return;
    const id = target.getAttribute("data-file-id");
    if (!id) return;
    if (target.checked) selectedDriveIds.add(id);
    else selectedDriveIds.delete(id);
    updateSelectedDriveCount();
  });

  qs("drive-import-btn")?.addEventListener("click", importSelectedDriveFiles);

  // Live line gutter update while typing
  textarea?.addEventListener("input", updateEditorGutterLive);

  // Progressive enhancement on form submission so in-memory Drive token is preserved across tabs/actions
  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formData = new FormData(form);
    const submitter = e.submitter;
    if (submitter && submitter.name) {
      formData.set(submitter.name, submitter.value);
    }

    const actionVal = String(formData.get("action") || "");
    if (actionVal === "tab:diff" || actionVal === "ai_improve") {
      const tabContent = document.querySelector(".tab-content");
      if (tabContent) {
        tabContent.innerHTML =
          '<div class="results-loading" style="padding:8px 0">' +
          '<div class="skeleton" style="height:24px;width:50%"></div>' +
          '<div class="skeleton" style="height:140px;width:100%"></div>' +
          '<div class="skeleton" style="height:140px;width:100%"></div>' +
          "</div>";
      }
    }

    const body = new URLSearchParams();
    for (const [key, val] of formData.entries()) {
      body.append(key, String(val));
    }

    try {
      const res = await fetch("/", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
        body: body.toString(),
      });
      if (res.ok) {
        const html = await res.text();
        applyHtmlDocument(html);
      }
    } catch {
      form.submit();
    }
  });
}

function initThemeSwitcher() {
  const buttons = Array.from(document.querySelectorAll("[data-theme-choice]"));
  if (!buttons.length) return;

  const applyTheme = (theme) => {
    const resolved = theme === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", resolved);
    try {
      localStorage.setItem("code_reviewer_theme", resolved);
    } catch {
      // ignore storage errors
    }
    for (const btn of buttons) {
      const isSelected = btn.getAttribute("data-theme-choice") === resolved;
      btn.classList.toggle("is-active", isSelected);
      btn.setAttribute("aria-pressed", String(isSelected));
    }
  };

  let initial = "light";
  try {
    const stored = localStorage.getItem("code_reviewer_theme");
    if (stored === "dark" || stored === "light") initial = stored;
  } catch {
    initial = "light";
  }
  applyTheme(initial);

  for (const btn of buttons) {
    btn.addEventListener("click", () => {
      applyTheme(btn.getAttribute("data-theme-choice"));
    });
  }
}

initThemeSwitcher();
setupEvents();

