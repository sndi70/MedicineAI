const state = {
  members: [],
  activeMemberId: null,
  medicinesByMember: new Map(),
  imageLookupBarcodes: new Set(),
  toastTimer: null,
  lookupTimer: null,
  lookupRequestId: 0,
  lastLookedUpBarcode: null,
  lookupPromise: null,
  lookupPromiseBarcode: null,
  webSearchTimer: null,
  webSearchRequestId: 0,
  webSearchResult: null
};
const icons = {
  medicine: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.5 4.5a5.66 5.66 0 0 0-4 9.66l5.34 5.34a5.66 5.66 0 0 0 8-8L12.5 6.16a5.64 5.64 0 0 0-4-1.66Z"/><path d="m7 15 8-8"/></svg>'
};

const familyList = document.querySelector("#family-list");
const medicineGrid = document.querySelector("#medicine-grid");
const memberDialog = document.querySelector("#member-dialog");
const medicineDialog = document.querySelector("#medicine-dialog");
const memberForm = document.querySelector("#member-form");
const medicineForm = document.querySelector("#medicine-form");
const toast = document.querySelector("#toast");

async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers }
  });
  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Възникна неочаквана грешка.");
  return data;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[character]);
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => toast.classList.remove("visible"), 3000);
}

function initials(name) {
  return name.trim().charAt(0).toLocaleUpperCase("bg-BG") || "?";
}

function renderMembers() {
  familyList.innerHTML = state.members.map(member => `
    <div class="family-option-wrap">
      <button class="family-option ${member.id === state.activeMemberId ? "active" : ""}" type="button" data-member-id="${member.id}" aria-pressed="${member.id === state.activeMemberId}">
        <span class="picker-avatar">${escapeHtml(initials(member.name))}</span>
        <span class="picker-name">${escapeHtml(member.name)}</span>
        <span class="picker-count">${member.medicine_count} ${member.medicine_count === 1 ? "лекарство" : "лекарства"}</span>
      </button>
      <button class="remove-member-button" type="button" data-delete-member-id="${member.id}" aria-label="Премахни ${escapeHtml(member.name)}" title="Премахни профила">×</button>
    </div>
  `).join("") + `
    <button class="family-option add-family-option" type="button" data-add-member>
      <span class="picker-avatar add-avatar" aria-hidden="true">+</span>
      <span class="picker-name">Добави</span>
      <span class="picker-count">нов човек</span>
    </button>
  `;
  document.querySelector("#total-members").textContent =
    state.members.length ? `${state.members.length} ${state.members.length === 1 ? "профил" : "профила"}` : "";
  document.querySelector("#add-medicine-button").disabled = !state.activeMemberId;
  document.querySelector("#search-input").disabled = false;
  document.querySelector("#active-member-name").textContent =
    state.members.find(member => member.id === state.activeMemberId)?.name || "Избери човек";
}

function formatDate(value) {
  return new Intl.DateTimeFormat("bg-BG", { day: "numeric", month: "short", year: "numeric" })
    .format(new Date(`${value}T00:00:00`));
}

function getDaysUntil(value) {
  const [year, month, day] = value.split("-").map(Number);
  const target = Date.UTC(year, month - 1, day);
  const today = new Date();
  const current = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - current) / 86400000);
}

function renderMedicines() {
  const searchInput = document.querySelector("#search-input");
  const rawQuery = searchInput.value.trim();
  const query = rawQuery.toLocaleLowerCase("bg-BG");
  const member = state.members.find(person => person.id === state.activeMemberId);
  if (!member) {
    document.querySelector("#inventory-description").textContent =
      "Лекарствата на всеки член се пазят отделно.";
    const webSearchCard = state.webSearchResult?.barcode === rawQuery
      ? renderWebSearchResult(state.webSearchResult, null)
      : "";
    medicineGrid.innerHTML = webSearchCard + `<div class="empty-state"><span class="empty-icon">✳</span><h3>${state.members.length ? "Избери човек" : "Добави първия човек"}</h3><p>${state.members.length ? "Избери семеен профил отгоре, за да видиш лекарствата му." : "Създай семеен профил, за да започнеш лекарствения регистър."}</p></div>`;
    return;
  }
  const medicines = (state.medicinesByMember.get(member.id) || []).filter(medicine =>
    medicine.productName.toLocaleLowerCase("bg-BG").includes(query)
    || medicine.barcode.includes(query)
  ).sort((first, second) => {
    if (!first.runOutDate) return second.runOutDate ? 1 : 0;
    if (!second.runOutDate) return -1;
    return first.runOutDate.localeCompare(second.runOutDate);
  });
  document.querySelector("#inventory-description").textContent =
    `${medicines.length} ${medicines.length === 1 ? "лекарство" : "лекарства"} в личния списък · подредени по очакван край на наличността`;
  const webSearchCard = state.webSearchResult?.barcode === rawQuery
    ? renderWebSearchResult(state.webSearchResult, member)
    : "";
  const localResults = medicines.length
    ? medicines.map(renderMedicineCard).join("")
    : `<div class="empty-state"><span class="empty-icon">${query ? "⌕" : "✳"}</span><h3>${query ? "Няма намерени лекарства в този списък" : "Списъкът е празен"}</h3><p>${query ? state.webSearchResult?.status === "found" ? "Продуктът е намерен онлайн — добави го към списъка, ако желаеш." : "Проверяваме и онлайн каталозите за този баркод." : `Добави първото лекарство за ${escapeHtml(member.name)}.`}</p></div>`;
  medicineGrid.innerHTML = webSearchCard + localResults;
}

function renderWebSearchResult(result, member) {
  if (result.status === "loading") {
    return `<article class="web-result web-result-loading" role="status"><span class="web-result-spinner" aria-hidden="true"></span><div><strong>Търсене в публичните продуктови каталози…</strong><p>Проверяваме баркод ${escapeHtml(result.barcode)} в няколко онлайн източника.</p></div></article>`;
  }
  if (result.status === "error") {
    return `<article class="web-result web-result-error" role="status"><span class="web-result-icon" aria-hidden="true">!</span><div><strong>Онлайн търсенето не беше успешно</strong><p>${escapeHtml(result.message)}</p><button class="web-retry-button" type="button" data-retry-barcode="${escapeHtml(result.barcode)}">Опитай отново</button></div></article>`;
  }
  if (result.status === "not-found") {
    const unavailableMessage = result.sourcesUnavailable?.length
      ? `<p>Недостъпни източници: ${escapeHtml(result.sourcesUnavailable.join(", "))}.</p>`
      : "";
    return `<article class="web-result" role="status"><span class="web-result-icon" aria-hidden="true">⌕</span><div><strong>${result.sourcesUnavailable?.length ? "Няма намерен продукт в достъпните каталози" : "Няма намерен продукт в проверените каталози"}</strong><p>${escapeHtml(result.message)}</p>${unavailableMessage}<button class="web-add-button" type="button" data-add-web-barcode="${escapeHtml(result.barcode)}">Попълни данните ръчно</button></div></article>`;
  }

  const product = result.product;
  const alreadyAdded = member && (state.medicinesByMember.get(member.id) || [])
    .some(medicine => medicine.barcode === result.barcode);
  const productName = product.productName || `Продукт с баркод ${result.barcode}`;
  return `
    <article class="web-result web-result-found">
      <div class="web-result-image">${product.imageUrl
        ? `<img src="${escapeHtml(product.imageUrl)}" alt="${escapeHtml(productName)}" loading="lazy" referrerpolicy="no-referrer" onerror="medicineImageFailed(this)">`
        : `<span class="image-placeholder">${icons.medicine}</span>`}</div>
      <div class="web-result-copy">
        <span class="web-result-tag">НАМЕРЕНО В ИНТЕРНЕТ</span>
        <strong class="web-result-name">${escapeHtml(productName)}</strong>
        <p>Баркод: ${escapeHtml(result.barcode)}</p>
        ${product.packageSize ? `<p>Опаковка: ${escapeHtml(product.packageSize)}</p>` : ""}
        <span class="web-result-source">Източник: ${escapeHtml(product.source || "публичен продуктов каталог")}</span>
      </div>
      <button class="web-add-button" type="button" data-add-web-barcode="${escapeHtml(result.barcode)}" ${alreadyAdded ? "disabled" : ""}>
        ${alreadyAdded ? "Вече е в списъка" : member ? "Добави в списъка" : "Избери профил за добавяне"}
      </button>
    </article>
  `;
}

function searchBarcodeOnline(barcode, requestId) {
  state.webSearchTimer = setTimeout(async () => {
    try {
      const product = await request(`/api/lookup/${encodeURIComponent(barcode)}`);
      if (
        requestId !== state.webSearchRequestId
        || document.querySelector("#search-input").value.trim() !== barcode
      ) return;
      state.webSearchResult = product.found
        ? { barcode, status: "found", product }
        : { barcode, status: "not-found", message: product.message };
    } catch (error) {
      if (
        requestId !== state.webSearchRequestId
        || document.querySelector("#search-input").value.trim() !== barcode
      ) return;
      state.webSearchResult = { barcode, status: "error", message: error.message };
    }
    renderMedicines();
  }, 450);
}

function handleInventorySearch() {
  clearTimeout(state.webSearchTimer);
  state.webSearchRequestId += 1;
  state.webSearchResult = null;
  renderMedicines();
  const barcode = document.querySelector("#search-input").value.trim();
  if (!/^(?:\d{8}|\d{12,14})$/.test(barcode)) return;
  const requestId = state.webSearchRequestId;
  state.webSearchResult = { barcode, status: "loading" };
  renderMedicines();
  searchBarcodeOnline(barcode, requestId);
}

function renderMedicineCard(medicine) {
  const daysUntilRunOut = medicine.runOutDate ? getDaysUntil(medicine.runOutDate) : null;
  const formattedRunOutDate = medicine.runOutDate
    ? escapeHtml(formatDate(medicine.runOutDate).replace(/\.$/, ""))
    : "";
  const runOutWarning = daysUntilRunOut !== null && daysUntilRunOut <= 3
    ? `<p class="medicine-warning" role="status">${daysUntilRunOut < 0
      ? `Според изчислението наличността е свършила преди ${Math.abs(daysUntilRunOut)} дни (${formattedRunOutDate}). Проверете я.`
      : daysUntilRunOut === 0
        ? `Според изчислението наличността свършва днес (${formattedRunOutDate}). Проверете я.`
        : `Напомняне: наличността се очаква да свърши след ${daysUntilRunOut} ${daysUntilRunOut === 1 ? "ден" : "дни"} — ${formattedRunOutDate}.`}</p>`
    : "";
  return `
    <article class="medicine-card">
      <div class="medicine-image">${medicine.imageUrl
        ? `<img src="${escapeHtml(medicine.imageUrl)}" alt="${escapeHtml(medicine.productName)}" loading="lazy" referrerpolicy="no-referrer" onerror="medicineImageFailed(this)">`
        : `<span class="image-placeholder">${icons.medicine}</span>`}</div>
      <div class="medicine-info">
        <div class="medicine-title-row"><h3 class="medicine-title" title="${escapeHtml(medicine.productName)}">${escapeHtml(medicine.productName)}</h3><button class="delete-button" type="button" data-delete-id="${medicine.id}" aria-label="Изтрий ${escapeHtml(medicine.productName)}">×</button></div>
        <p class="medicine-barcode">Баркод: ${escapeHtml(medicine.barcode)}</p>
        <p class="medicine-detail">Купено количество: <strong>${medicine.quantity} оп.</strong>${medicine.packageSize ? ` · ${escapeHtml(medicine.packageSize)}` : ""}</p>
        <p class="medicine-detail">Дневен прием: <strong>${escapeHtml(medicine.dailyUsage)}</strong></p>
        <span class="medicine-date">Купено на ${escapeHtml(formatDate(medicine.purchaseDate))}</span>
        ${runOutWarning}
      </div>
    </article>
  `;
}

function medicineImageFailed(image) {
  image.replaceWith(Object.assign(document.createElement("span"), {
    className: "image-placeholder",
    innerHTML: icons.medicine
  }));
}

function updateMedicineImagePreview(imageUrl, productName = "") {
  const preview = document.querySelector("#medicine-image-preview");
  const imageInput = medicineForm.elements.imageUrl;
  imageInput.value = imageUrl || "";
  preview.setAttribute(
    "aria-label",
    imageUrl ? `Снимка на ${productName || "продукта"}` : "Няма намерена снимка на продукта"
  );
  preview.innerHTML = imageUrl
    ? `<img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(productName || "Снимка на продукта")}" onerror="medicineImagePreviewFailed(this)">`
    : `<span class="image-placeholder">${icons.medicine}</span><span class="image-preview-caption">Снимката ще се покаже след търсене по баркод.</span>`;
}

function medicineImagePreviewFailed(image) {
  updateMedicineImagePreview("");
  document.querySelector("#lookup-message").textContent =
    "Снимката не можа да се зареди. Можете да продължите без нея.";
}

async function findMissingMedicineImages() {
  const medicines = [...state.medicinesByMember.values()].flat();
  const barcodes = [...new Set(
    medicines
      .filter(medicine => !medicine.imageUrl && !state.imageLookupBarcodes.has(medicine.barcode))
      .map(medicine => medicine.barcode)
  )];

  await Promise.all(barcodes.map(async barcode => {
    state.imageLookupBarcodes.add(barcode);
    try {
      const product = await request(`/api/lookup/${encodeURIComponent(barcode)}`);
      if (!product.found || !product.imageUrl) return;

      const matchingMedicines = medicines.filter(
        medicine => medicine.barcode === barcode && !medicine.imageUrl
      );
      const updatedMedicines = await Promise.all(matchingMedicines.map(medicine =>
        request(`/api/medicines/${medicine.id}/image`, {
          method: "PATCH",
          body: JSON.stringify({ imageUrl: product.imageUrl })
        })
      ));
      const imageUrl = updatedMedicines.find(medicine => medicine.imageUrl)?.imageUrl;
      if (!imageUrl) return;

      for (const [memberId, memberMedicines] of state.medicinesByMember) {
        state.medicinesByMember.set(memberId, memberMedicines.map(medicine =>
          medicine.barcode === barcode && !medicine.imageUrl
            ? { ...medicine, imageUrl }
            : medicine
        ));
      }
      renderMedicines();
    } catch (error) {
      showToast(`Не успяхме да заредим снимката за баркод ${barcode}: ${error.message}`);
    }
  }));
}

async function loadMembers() {
  const overview = await request("/api/overview");
  state.members = overview.members;
  state.medicinesByMember = new Map(
    overview.medicines.map(({ memberId, medicines }) => [memberId, medicines])
  );
  if (!state.members.some(member => member.id === state.activeMemberId)) {
    state.activeMemberId = state.members[0]?.id || null;
  }
  renderMembers();
  renderMedicines();
  findMissingMedicineImages();
}

function selectMember(id, shouldScroll = true) {
  state.activeMemberId = id;
  clearTimeout(state.webSearchTimer);
  state.webSearchRequestId += 1;
  state.webSearchResult = null;
  document.querySelector("#search-input").value = "";
  document.querySelector("#active-member-name").textContent =
    state.members.find(member => member.id === id)?.name || "Избери човек";
  renderMembers();
  renderMedicines();
  if (shouldScroll) {
    document.querySelector(".inventory-section")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

function openMemberDialog() {
  document.querySelector("#member-error").textContent = "";
  memberForm.reset();
  memberDialog.showModal();
  memberForm.elements.name.focus();
}

function openMedicineDialog(memberId = state.activeMemberId) {
  if (!memberId) return;
  clearTimeout(state.lookupTimer);
  state.lookupRequestId += 1;
  state.lastLookedUpBarcode = null;
  state.lookupPromise = null;
  state.lookupPromiseBarcode = null;
  document.querySelector("#lookup-button").disabled = false;
  document.querySelector("#lookup-button").innerHTML = '<span aria-hidden="true">⌕</span> Потърси';
  state.activeMemberId = memberId;
  document.querySelector("#active-member-name").textContent =
    state.members.find(member => member.id === memberId)?.name || "Изберете профил";
  renderMembers();
  document.querySelector("#medicine-error").textContent = "";
  document.querySelector("#lookup-message").textContent = "";
  document.querySelector("#lookup-message").classList.remove("error");
  medicineForm.reset();
  updateMedicineImagePreview("");
  medicineForm.elements.quantity.value = "1";
  const now = new Date();
  medicineForm.elements.purchaseDate.value = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0")
  ].join("-");
  medicineDialog.showModal();
}

function lookupBarcode(barcode = medicineForm.elements.barcode.value.trim()) {
  const button = document.querySelector("#lookup-button");
  const message = document.querySelector("#lookup-message");
  message.classList.remove("error");
  if (!/^(?:\d{8}|\d{12,14})$/.test(barcode)) {
    message.textContent = "Въведете баркод с 8, 12, 13 или 14 цифри.";
    message.classList.add("error");
    return Promise.resolve(false);
  }
  if (state.lastLookedUpBarcode === barcode) return Promise.resolve(true);
  if (state.lookupPromise && state.lookupPromiseBarcode === barcode) return state.lookupPromise;

  const requestId = ++state.lookupRequestId;
  state.lookupPromiseBarcode = barcode;
  button.disabled = true;
  button.textContent = "Търсене…";
  message.textContent = "Търсим продукта в интернет по баркод…";
  const lookupPromise = (async () => {
    try {
      const product = await request(`/api/lookup/${encodeURIComponent(barcode)}`);
      if (
        requestId !== state.lookupRequestId
        || !medicineDialog.open
        || medicineForm.elements.barcode.value.trim() !== barcode
      ) return false;
      state.lastLookedUpBarcode = barcode;
      if (!product.found) {
        message.textContent = product.message;
        return false;
      }
      if (product.productName) medicineForm.elements.productName.value = product.productName;
      updateMedicineImagePreview(product.imageUrl, product.productName);
      if (product.packageSize) medicineForm.elements.packageSize.value = product.packageSize;
      message.textContent = product.productName
        ? "Намерихме продукта — проверете данните и попълнете покупката."
        : "Продуктът е намерен, но името липсва. Попълнете го ръчно.";
      return true;
    } catch (error) {
      if (requestId === state.lookupRequestId && medicineDialog.open) {
        message.textContent = error.message;
        message.classList.add("error");
      }
      return false;
    } finally {
      if (requestId === state.lookupRequestId) {
        button.disabled = false;
        button.innerHTML = '<span aria-hidden="true">⌕</span> Потърси';
      }
      if (state.lookupPromise === lookupPromise) {
        state.lookupPromise = null;
        state.lookupPromiseBarcode = null;
      }
    }
  })();
  state.lookupPromise = lookupPromise;
  return lookupPromise;
}

document.querySelector("#add-medicine-button").addEventListener("click", () => openMedicineDialog());
document.querySelector("#search-input").addEventListener("input", handleInventorySearch);
medicineForm.elements.barcode.addEventListener("input", () => {
  clearTimeout(state.lookupTimer);
  state.lookupRequestId += 1;
  state.lastLookedUpBarcode = null;
  state.lookupPromise = null;
  state.lookupPromiseBarcode = null;
  const button = document.querySelector("#lookup-button");
  button.disabled = false;
  button.innerHTML = '<span aria-hidden="true">⌕</span> Потърси';
  const barcode = medicineForm.elements.barcode.value.trim();
  const message = document.querySelector("#lookup-message");
  message.classList.remove("error");
  if (!/^(?:\d{8}|\d{12,14})$/.test(barcode)) {
    message.textContent = "";
    return;
  }
  message.textContent = "Търсенето ще започне автоматично…";
  state.lookupTimer = setTimeout(() => lookupBarcode(barcode), 500);
});
medicineForm.elements.barcode.addEventListener("blur", () => {
  clearTimeout(state.lookupTimer);
  const barcode = medicineForm.elements.barcode.value.trim();
  if (/^(?:\d{8}|\d{12,14})$/.test(barcode) && state.lastLookedUpBarcode !== barcode) {
    lookupBarcode(barcode);
  }
});
medicineDialog.addEventListener("close", () => {
  clearTimeout(state.lookupTimer);
  state.lookupRequestId += 1;
  state.lookupPromise = null;
  state.lookupPromiseBarcode = null;
});

familyList.addEventListener("click", async event => {
  if (event.target.closest("[data-add-member]")) {
    openMemberDialog();
    return;
  }
  const removeButton = event.target.closest("[data-delete-member-id]");
  if (removeButton) {
    const memberId = Number(removeButton.dataset.deleteMemberId);
    const member = state.members.find(person => person.id === memberId);
    if (!member) return;
    const medicineMessage = member.medicine_count
      ? ` Всички ${member.medicine_count} ${member.medicine_count === 1 ? "лекарство" : "лекарства"} в профила също ще бъдат изтрити.`
      : "";
    if (!window.confirm(`Да премахнем ли профила „${member.name}“?${medicineMessage}`)) return;
    try {
      await request(`/api/family/${memberId}`, { method: "DELETE" });
      await loadMembers();
      selectMember(state.activeMemberId, false);
      showToast("Семейният профил е премахнат.");
    } catch (error) {
      showToast(error.message);
    }
    return;
  }
  const button = event.target.closest("[data-member-id]");
  if (!button) return;
  try {
    selectMember(Number(button.dataset.memberId));
  } catch (error) {
    showToast(error.message);
  }
});

document.querySelectorAll("[data-close]").forEach(button => {
  button.addEventListener("click", () => button.closest("dialog").close());
});

memberForm.addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const member = await request("/api/family", {
      method: "POST",
      body: JSON.stringify({ name: memberForm.elements.name.value })
    });
    memberDialog.close();
    await loadMembers();
    selectMember(member.id);
    showToast("Профилът е добавен.");
  } catch (error) {
    document.querySelector("#member-error").textContent = error.message;
  }
});

document.querySelector("#lookup-button").addEventListener("click", () => {
  clearTimeout(state.lookupTimer);
  lookupBarcode();
});

medicineForm.addEventListener("submit", async event => {
  event.preventDefault();
  clearTimeout(state.lookupTimer);
  const barcode = medicineForm.elements.barcode.value.trim();
  if (/^(?:\d{8}|\d{12,14})$/.test(barcode) && state.lastLookedUpBarcode !== barcode) {
    await lookupBarcode(barcode);
  }
  const formData = new FormData(medicineForm);
  const medicine = Object.fromEntries(formData.entries());
  medicine.memberId = state.activeMemberId;
  medicine.quantity = Number(medicine.quantity);
  try {
    await request("/api/medicines", { method: "POST", body: JSON.stringify(medicine) });
    medicineDialog.close();
    await loadMembers();
    selectMember(state.activeMemberId, false);
    showToast("Лекарството е добавено.");
  } catch (error) {
    document.querySelector("#medicine-error").textContent = error.message;
  }
});

medicineGrid.addEventListener("click", async event => {
  const retryButton = event.target.closest("[data-retry-barcode]");
  if (retryButton) {
    handleInventorySearch();
    return;
  }
  const addWebResultButton = event.target.closest("[data-add-web-barcode]");
  if (addWebResultButton) {
    if (!state.activeMemberId) {
      showToast("Първо изберете член на семейството.");
      return;
    }
    const barcode = addWebResultButton.dataset.addWebBarcode;
    const onlineResult = state.webSearchResult;
    openMedicineDialog(state.activeMemberId);
    medicineForm.elements.barcode.value = barcode;
    if (onlineResult?.barcode === barcode && onlineResult.status === "found") {
      medicineForm.elements.productName.value = onlineResult.product.productName || "";
      updateMedicineImagePreview(
        onlineResult.product.imageUrl || "",
        onlineResult.product.productName || ""
      );
      medicineForm.elements.packageSize.value = onlineResult.product.packageSize || "";
      state.lastLookedUpBarcode = barcode;
      document.querySelector("#lookup-message").textContent =
        "Данните са намерени онлайн. Проверете ги и попълнете покупката.";
    } else {
      document.querySelector("#lookup-message").textContent =
        "Попълнете данните за продукта ръчно.";
    }
    medicineForm.elements.productName.focus();
    return;
  }
  const button = event.target.closest("[data-delete-id]");
  if (!button) return;
  if (!window.confirm("Да изтрием ли това лекарство?")) return;
  try {
    await request(`/api/medicines/${button.dataset.deleteId}`, { method: "DELETE" });
    await loadMembers();
    selectMember(state.activeMemberId, false);
    showToast("Лекарството е изтрито.");
  } catch (error) {
    showToast(error.message);
  }
});

loadMembers().then(() => {
  if (state.activeMemberId) selectMember(state.activeMemberId, false);
}).catch(error => {
  showToast(error.message);
  medicineGrid.innerHTML = `<div class="empty-state"><span class="empty-icon">!</span><h3>Не успяхме да заредим данните</h3><p>${escapeHtml(error.message)} Обновете страницата, за да опитате отново.</p></div>`;
});
