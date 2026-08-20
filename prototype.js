document.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }

  document.querySelectorAll("[data-segment-group]").forEach((group) => {
    group.addEventListener("click", (event) => {
      const button = event.target.closest(".segment");
      if (!button) return;
      group.querySelectorAll(".segment").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
    });
  });

  document.querySelectorAll("[data-suggestion]").forEach((button) => {
    button.addEventListener("click", () => {
      const phone = button.closest(".phone");
      const input = phone?.querySelector(".topic-input");
      if (input) {
        input.value = button.dataset.suggestion || button.textContent.trim();
        input.focus();
      }
    });
  });

  document.querySelectorAll("[data-generate-quiz]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.disabled) return;
      button.disabled = true;
      button.classList.add("button-loading");
      button.innerHTML = '<span class="spinner" aria-hidden="true"></span>正在生成题组…';
      const helper = button.parentElement?.querySelector("[data-generate-helper]");
      if (helper) helper.textContent = "正在组织题目与讲解，完成后自动进入第 1 题";
    });
  });

  document.querySelectorAll("[data-option-group]").forEach((group) => {
    group.addEventListener("click", (event) => {
      const option = event.target.closest(".option");
      if (!option) return;
      group.querySelectorAll(".option").forEach((item) => item.classList.remove("selected"));
      option.classList.add("selected");
      updateSubmitState(group.closest(".phone"));
    });
  });

  document.querySelectorAll("[data-accordion]").forEach((button) => {
    button.addEventListener("click", () => {
      const panel = document.getElementById(button.getAttribute("aria-controls"));
      if (!panel) return;
      const expanded = button.getAttribute("aria-expanded") === "true";
      button.setAttribute("aria-expanded", String(!expanded));
      panel.hidden = expanded;
      const label = button.querySelector("span");
      if (label) label.textContent = expanded ? "展开详细讲解" : "收起详细讲解";
      if (window.lucide) window.lucide.createIcons();
    });
  });

  document.querySelectorAll("[data-toast-message]").forEach((button) => {
    button.addEventListener("click", () => showToast(button.closest(".phone"), button.dataset.toastMessage));
  });
});

function updateSubmitState(phone) {
  if (!phone) return;
  const hasAnswer = Boolean(phone.querySelector(".option.selected"));
  const submit = phone.querySelector("[data-submit-answer]");
  if (submit) submit.disabled = !hasAnswer;
}

function showToast(phone, message) {
  if (!phone || !message) return;
  const toast = phone.querySelector(".toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("visible");
  window.setTimeout(() => toast.classList.remove("visible"), 1800);
}
