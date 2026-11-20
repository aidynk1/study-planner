const taskForm = document.querySelector("#task-form");
const taskList = document.querySelector("#task-list");
const statusFilter = document.querySelector("#status-filter");
const taskCount = document.querySelector("#task-count");
const formError = document.querySelector("#form-error");
const pageError = document.querySelector("#page-error");
const studyFocus = document.querySelector("#study-focus");
const refreshFocus = document.querySelector("#refresh-focus");

const statusLabels = {
  planned: "Запланирована",
  in_progress: "В работе",
  done: "Готово",
};

function showError(element, message = "") {
  element.textContent = message;
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const error = new Error(payload.detail || "Не удалось выполнить запрос.");
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

function renderStudyFocus(focus) {
  const card = document.createElement("article");
  card.className = "focus-card";

  const title = document.createElement("h3");
  title.className = "task-title";
  title.textContent = focus.task.title;

  const details = document.createElement("p");
  details.className = "task-date";
  const dueDate = focus.task.due_date
    ? `Дедлайн: ${new Date(`${focus.task.due_date}T00:00:00`).toLocaleDateString("ru-RU")}`
    : "Без дедлайна";
  details.textContent = `${statusLabels[focus.task.status]} · ${dueDate}`;

  const reason = document.createElement("p");
  reason.className = "focus-reason";
  reason.textContent = focus.reason;

  card.append(title, details, reason);
  studyFocus.replaceChildren(card);
}

async function loadStudyFocus() {
  studyFocus.replaceChildren();
  try {
    const focus = await request("/api/tasks/focus");
    renderStudyFocus(focus);
  } catch (error) {
    const message = error.status === 404
      ? "Пока нет активных задач. Добавь задачу, и здесь появится следующий шаг."
      : error.message;
    const empty = document.createElement("p");
    empty.className = error.status === 404 ? "empty-state" : "error";
    empty.textContent = message;
    studyFocus.replaceChildren(empty);
  }
}

function makeButton(label, className, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `button ${className}`;
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function createEditForm(task, card) {
  const form = document.createElement("form");
  form.className = "edit-form";
  const title = document.createElement("input");
  title.name = "title";
  title.maxLength = 200;
  title.required = true;
  title.value = task.title;
  title.setAttribute("aria-label", "Название задачи");

  const description = document.createElement("textarea");
  description.name = "description";
  description.maxLength = 2000;
  description.rows = 2;
  description.value = task.description;
  description.setAttribute("aria-label", "Описание задачи");

  const dueDate = document.createElement("input");
  dueDate.name = "due_date";
  dueDate.type = "date";
  dueDate.value = task.due_date || "";
  dueDate.setAttribute("aria-label", "Дедлайн");

  const actions = document.createElement("div");
  actions.className = "task-actions";
  actions.append(
    makeButton("Сохранить", "button-primary", () => form.requestSubmit()),
    makeButton("Отмена", "button-secondary", () => card.replaceChildren(...card.originalNodes)),
  );

  form.append(title, description, dueDate, actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const data = new FormData(form);
      await request(`/api/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title: data.get("title"),
          description: data.get("description"),
          due_date: data.get("due_date") || null,
        }),
      });
      await loadTasks();
    } catch (error) {
      showError(pageError, error.message);
    }
  });
  return form;
}

function renderTask(task) {
  const card = document.createElement("article");
  card.className = "task-card";

  const top = document.createElement("div");
  top.className = "task-top";
  const title = document.createElement("h3");
  title.className = "task-title";
  title.textContent = task.title;
  const statusText = document.createElement("span");
  statusText.className = "eyebrow";
  statusText.textContent = statusLabels[task.status];
  top.append(title, statusText);
  card.append(top);

  if (task.description) {
    const description = document.createElement("p");
    description.className = "task-description";
    description.textContent = task.description;
    card.append(description);
  }

  if (task.due_date) {
    const dueDate = document.createElement("p");
    dueDate.className = "task-date";
    dueDate.textContent = `Дедлайн: ${new Date(`${task.due_date}T00:00:00`).toLocaleDateString("ru-RU")}`;
    card.append(dueDate);
  }

  const actions = document.createElement("div");
  actions.className = "task-actions";
  const status = document.createElement("select");
  status.setAttribute("aria-label", `Статус задачи «${task.title}»`);
  Object.entries(statusLabels).forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = value === task.status;
    status.append(option);
  });
  status.addEventListener("change", async () => {
    try {
      await request(`/api/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: status.value }),
      });
      await loadTasks();
    } catch (error) {
      showError(pageError, error.message);
    }
  });
  actions.append(
    status,
    makeButton("Изменить", "button-secondary", () => {
      card.originalNodes = Array.from(card.childNodes);
      card.replaceChildren(createEditForm(task, card));
    }),
    makeButton("Удалить", "button-danger", async () => {
      if (!window.confirm(`Удалить задачу «${task.title}»?`)) return;
      try {
        await request(`/api/tasks/${task.id}`, { method: "DELETE" });
        await loadTasks();
      } catch (error) {
        showError(pageError, error.message);
      }
    }),
  );
  card.append(actions);
  return card;
}

async function loadTasks() {
  showError(pageError);
  const status = statusFilter.value;
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  try {
    const tasks = await request(`/api/tasks${query}`);
    await loadStudyFocus();
    taskList.replaceChildren();
    taskCount.textContent = `${tasks.length} ${tasks.length === 1 ? "задача" : "задач"}`;
    if (tasks.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "Пока задач нет. Добавь первую выше.";
      taskList.append(empty);
      return;
    }
    tasks.forEach((task) => taskList.append(renderTask(task)));
  } catch (error) {
    showError(pageError, error.message);
  }
}

taskForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  showError(formError);
  const data = new FormData(taskForm);
  try {
    await request("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        title: data.get("title"),
        description: data.get("description"),
        due_date: data.get("due_date") || null,
      }),
    });
    taskForm.reset();
    await loadTasks();
  } catch (error) {
    showError(formError, error.message);
  }
});

statusFilter.addEventListener("change", loadTasks);
refreshFocus.addEventListener("click", loadStudyFocus);
loadTasks();
