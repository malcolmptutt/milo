const authArea = document.getElementById("auth-area");
const errorBanner = document.getElementById("error-banner");
const signedOutNote = document.getElementById("signed-out-note");
const calendarPanel = document.getElementById("calendar-panel");
const tasksPanel = document.getElementById("tasks-panel");
const eventsList = document.getElementById("events-list");
const tasksList = document.getElementById("tasks-list");
const addTaskForm = document.getElementById("add-task-form");
const newTaskInput = document.getElementById("new-task-input");
const micBtn = document.getElementById("mic-btn");
const micHint = document.getElementById("mic-hint");

let currentUser = null;

function showError(message) {
  errorBanner.innerHTML = `<div class="error-banner">${message}</div>`;
}

function clearError() {
  errorBanner.innerHTML = "";
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (res.status === 401) {
    currentUser = null;
    renderAuthArea();
    throw new Error("Not signed in");
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `Request failed: ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

function renderAuthArea() {
  if (currentUser) {
    authArea.innerHTML = `
      <div class="user-chip">
        ${currentUser.picture ? `<img src="${currentUser.picture}" alt="" />` : ""}
        <span>${currentUser.name || currentUser.email}</span>
        <button class="btn secondary" id="logout-btn">Disconnect</button>
      </div>`;
    document.getElementById("logout-btn").addEventListener("click", logout);
    signedOutNote.style.display = "none";
    calendarPanel.style.display = "block";
    tasksPanel.style.display = "block";
  } else {
    authArea.innerHTML = `<button id="connect-btn">Connect Google</button>`;
    document.getElementById("connect-btn").addEventListener("click", () => {
      window.location.href = "/api/auth/google/login";
    });
    signedOutNote.style.display = "block";
    calendarPanel.style.display = "none";
    tasksPanel.style.display = "none";
  }
}

async function logout() {
  await api("/api/auth/logout", { method: "POST" });
  currentUser = null;
  renderAuthArea();
}

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso; // all-day events come back as a plain date
  return d.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
}

async function loadEvents() {
  try {
    const data = await api("/api/calendar/events");
    if (!data.events.length) {
      eventsList.innerHTML = `<div class="empty">Nothing on the calendar this week.</div>`;
      return;
    }
    eventsList.innerHTML = data.events
      .map(
        (e) => `
        <div class="card">
          <span class="title">${e.title}</span>
          <span class="meta">${formatTime(e.start)}</span>
        </div>`
      )
      .join("");
  } catch (err) {
    eventsList.innerHTML = `<div class="empty">Couldn't load calendar events.</div>`;
  }
}

async function loadTasks() {
  try {
    const data = await api("/api/tasks");
    if (!data.tasks.length) {
      tasksList.innerHTML = `<div class="empty">No tasks yet.</div>`;
      return;
    }
    tasksList.innerHTML = data.tasks
      .map(
        (t) => `
        <div class="card" data-id="${t.id}">
          <label class="task-row">
            <input type="checkbox" ${t.completed ? "checked" : ""} class="task-check" />
            <span class="title ${t.completed ? "done" : ""}">${t.title}</span>
          </label>
          <span class="tag">${t.category}</span>
        </div>`
      )
      .join("");

    tasksList.querySelectorAll(".task-check").forEach((box) => {
      box.addEventListener("change", async (e) => {
        const card = e.target.closest(".card");
        const id = card.dataset.id;
        await api(`/api/tasks/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ completed: e.target.checked }),
        });
        loadTasks();
      });
    });
  } catch (err) {
    tasksList.innerHTML = `<div class="empty">Couldn't load tasks.</div>`;
  }
}

addTaskForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = newTaskInput.value.trim();
  if (!title) return;
  await addTask(title);
  newTaskInput.value = "";
});

async function addTask(title) {
  try {
    await api("/api/tasks", { method: "POST", body: JSON.stringify({ title }) });
    loadTasks();
  } catch (err) {
    showError("Couldn't add that task. Try again.");
  }
}

// --- Voice capture -------------------------------------------------
// PoC behaviour: whatever you say becomes a new task. Swapping this for
// real intent parsing (reschedule, query, etc.) is the natural next step.

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;

if (SpeechRecognition) {
  recognizer = new SpeechRecognition();
  recognizer.lang = "en-US";
  recognizer.interimResults = false;

  recognizer.addEventListener("start", () => {
    micBtn.classList.add("listening");
    micHint.textContent = "Listening...";
  });

  recognizer.addEventListener("end", () => {
    micBtn.classList.remove("listening");
    micHint.textContent = "Tap and talk, or add a task below";
  });

  recognizer.addEventListener("result", async (event) => {
    const transcript = event.results[0][0].transcript;
    micHint.textContent = `Added: "${transcript}"`;
    if (currentUser) {
      await addTask(transcript);
    } else {
      showError("Connect Google before adding tasks by voice.");
    }
  });

  recognizer.addEventListener("error", () => {
    micHint.textContent = "Didn't catch that, try again";
  });

  micBtn.addEventListener("click", () => recognizer.start());
} else {
  micBtn.disabled = true;
  micHint.textContent = "Voice input isn't supported in this browser";
}

// --- Boot ------------------------------------------------------------

async function boot() {
  clearError();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  const params = new URLSearchParams(window.location.search);
  if (params.get("auth_error")) {
    showError("Google sign-in didn't complete. Please try again.");
  }

  try {
    const data = await api("/api/auth/me");
    if (data.authenticated) {
      currentUser = data.user;
      renderAuthArea();
      loadEvents();
      loadTasks();
      return;
    }
  } catch (err) {
    // treated as signed out below
  }
  currentUser = null;
  renderAuthArea();
}

boot();
