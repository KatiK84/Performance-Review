const state = {
  departments: [],
  employees: [],
  criteria: [],
  monthlySnapshot: null,
  quarterSnapshot: null,
};

function showToast(message, isError = false) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.classList.remove('hidden');
  toast.classList.toggle('error', isError);
  setTimeout(() => toast.classList.add('hidden'), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const isJson = response.headers.get('content-type')?.includes('application/json');
  const payload = isJson ? await response.json() : null;

  if (!response.ok) {
    const message = payload?.error || `Ошибка ${response.status}`;
    throw new Error(message);
  }

  return payload;
}

function setDefaultDates() {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;
  const quarter = Math.floor((month - 1) / 3) + 1;

  document.getElementById('monthlyYear').value = year;
  document.getElementById('monthlyMonth').value = month;

  document.getElementById('quarterYear').value = year;
  document.getElementById('quarterNumber').value = String(quarter);

  document.getElementById('bonusYear').value = year;
  document.getElementById('bonusQuarter').value = String(quarter);

  document.getElementById('reportsYear').value = year;
  document.getElementById('reportsQuarter').value = String(quarter);
}

function setupTabs() {
  document.getElementById('tabs').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-tab]');
    if (!button) return;

    document.querySelectorAll('#tabs button').forEach((btn) => btn.classList.remove('active'));
    button.classList.add('active');

    document.querySelectorAll('.tab').forEach((tab) => tab.classList.remove('active'));
    document.getElementById(`tab-${button.dataset.tab}`).classList.add('active');
  });
}

function fillSelect(select, items, includeAll = false) {
  const prev = select.value;
  select.innerHTML = '';

  if (includeAll) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'Все';
    select.appendChild(option);
  }

  for (const item of items) {
    const option = document.createElement('option');
    option.value = item.id;
    option.textContent = item.name || item.full_name;
    select.appendChild(option);
  }

  if ([...select.options].some((opt) => opt.value === prev)) {
    select.value = prev;
  }
}

async function loadDepartments() {
  state.departments = await api('/api/departments');
  renderDepartments();

  const selectors = [
    'employeeDepartmentSelect',
    'employeeFilterDepartment',
    'monthlyDepartment',
    'quarterDepartment',
    'bonusDepartment',
    'reportsDepartment',
  ];
  selectors.forEach((id, idx) => fillSelect(document.getElementById(id), state.departments, idx === 1));
}

function renderDepartments() {
  const tbody = document.querySelector('#departmentsTable tbody');
  tbody.innerHTML = '';

  for (const item of state.departments) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.id}</td>
      <td>${item.name}</td>
      <td>${item.is_active ? 'Да' : 'Нет'}</td>
      <td><button class="secondary" data-action="edit-department" data-id="${item.id}">Изменить</button></td>
    `;
    tbody.appendChild(tr);
  }
}

async function loadEmployees() {
  const departmentId = document.getElementById('employeeFilterDepartment').value;
  const activeOnly = document.getElementById('employeeFilterActive').checked;

  const params = new URLSearchParams();
  if (departmentId) params.set('department_id', departmentId);
  if (activeOnly) params.set('active_only', '1');

  state.employees = await api(`/api/employees?${params.toString()}`);
  renderEmployees();

  const employeesForReports = await api('/api/employees');
  fillSelect(document.getElementById('reportsEmployee'), employeesForReports);
}

function renderEmployees() {
  const tbody = document.querySelector('#employeesTable tbody');
  tbody.innerHTML = '';

  for (const item of state.employees) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.id}</td>
      <td>${item.full_name}</td>
      <td>${item.department_name}</td>
      <td>${item.position || ''}</td>
      <td>${item.is_active ? 'Да' : 'Нет'}</td>
      <td><button class="secondary" data-action="edit-employee" data-id="${item.id}">Изменить</button></td>
    `;
    tbody.appendChild(tr);
  }
}

async function loadCriteria() {
  const payload = await api('/api/criteria');
  state.criteria = payload.items;
  renderCriteria();

  const weightStatus = payload.weights;
  document.getElementById('weightStatus').textContent =
    `Активных критериев: ${weightStatus.active_count}, сумма весов: ${weightStatus.total_weight.toFixed(2)} (${weightStatus.is_valid ? 'OK' : 'не 100'})`;
}

function renderCriteria() {
  const tbody = document.querySelector('#criteriaTable tbody');
  tbody.innerHTML = '';

  for (const item of state.criteria) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.id}</td>
      <td>${item.name}</td>
      <td>${Number(item.weight).toFixed(2)}</td>
      <td>${item.is_active ? 'Да' : 'Нет'}</td>
      <td><button class="secondary" data-action="edit-criterion" data-id="${item.id}">Изменить</button></td>
    `;
    tbody.appendChild(tr);
  }
}

function collectFormData(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  for (const checkbox of form.querySelectorAll('input[type="checkbox"]')) {
    data[checkbox.name] = checkbox.checked;
  }
  return data;
}

function setFormField(form, name, value) {
  const field = form.querySelector(`[name="${name}"]`);
  if (field) field.value = value;
}

function setFormCheckbox(form, name, checked) {
  const field = form.querySelector(`[name="${name}"]`);
  if (field) field.checked = Boolean(checked);
}

function resetDepartmentForm() {
  const form = document.getElementById('departmentForm');
  form.reset();
  setFormField(form, 'id', '');
  setFormCheckbox(form, 'is_active', true);
}

function resetEmployeeForm() {
  const form = document.getElementById('employeeForm');
  form.reset();
  setFormField(form, 'id', '');
  setFormCheckbox(form, 'is_active', true);
}

function resetCriterionForm() {
  const form = document.getElementById('criterionForm');
  form.reset();
  setFormField(form, 'id', '');
  setFormField(form, 'sort_order', '0');
  setFormCheckbox(form, 'is_active', true);
}

async function loadMonthlyReview() {
  const year = document.getElementById('monthlyYear').value;
  const month = document.getElementById('monthlyMonth').value;
  const departmentId = document.getElementById('monthlyDepartment').value;

  if (!departmentId) {
    showToast('Выберите отдел', true);
    return;
  }

  const params = new URLSearchParams({ year, month, department_id: departmentId });
  const payload = await api(`/api/reviews/monthly?${params.toString()}`);
  state.monthlySnapshot = payload;
  renderMonthlyReview();
}

function renderMonthlyReview() {
  const snapshot = state.monthlySnapshot;
  if (!snapshot) return;

  const meta = document.getElementById('monthlyMeta');
  meta.textContent = `Статус периода: ${snapshot.period.status}. Средний балл отдела: ${snapshot.department_avg ?? '-'}.
  Сумма весов: ${snapshot.weights.total_weight.toFixed(2)}.`;

  const thead = document.querySelector('#monthlyTable thead');
  const tbody = document.querySelector('#monthlyTable tbody');

  const criteriaHeaders = snapshot.criteria.map(
    (criterion) => `<th>${criterion.name}<br><small>${criterion.weight}%</small></th>`,
  );

  thead.innerHTML = `
    <tr>
      <th>Сотрудник</th>
      ${criteriaHeaders.join('')}
      <th>Итог месяца</th>
    </tr>
  `;

  tbody.innerHTML = '';
  for (const item of snapshot.employees) {
    const cells = snapshot.criteria.map((criterion) => {
      const payload = item.scores[criterion.id] || {};
      const score = payload.score ?? '';
      const comment = payload.comment ?? '';

      return `
        <td>
          <input
            type="number"
            min="1"
            max="10"
            class="score-input"
            data-employee-id="${item.employee.id}"
            data-criterion-id="${criterion.id}"
            value="${score}"
          />
          <input
            type="text"
            class="comment-input"
            data-employee-id="${item.employee.id}"
            data-criterion-id="${criterion.id}"
            placeholder="комментарий"
            value="${comment}"
          />
        </td>
      `;
    });

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.employee.full_name}</td>
      ${cells.join('')}
      <td>${item.monthly_score ?? '-'}</td>
    `;
    tbody.appendChild(tr);
  }
}

async function saveMonthlyReview() {
  const snapshot = state.monthlySnapshot;
  if (!snapshot) {
    showToast('Сначала загрузите месяц', true);
    return;
  }

  const year = Number(document.getElementById('monthlyYear').value);
  const month = Number(document.getElementById('monthlyMonth').value);
  const departmentId = Number(document.getElementById('monthlyDepartment').value);

  const entries = [];
  const scoreInputs = document.querySelectorAll('#monthlyTable .score-input');
  for (const scoreInput of scoreInputs) {
    if (!scoreInput.value) continue;

    const employeeId = Number(scoreInput.dataset.employeeId);
    const criterionId = Number(scoreInput.dataset.criterionId);
    const commentInput = document.querySelector(
      `#monthlyTable .comment-input[data-employee-id="${employeeId}"][data-criterion-id="${criterionId}"]`,
    );

    entries.push({
      employee_id: employeeId,
      criterion_id: criterionId,
      score: Number(scoreInput.value),
      comment: commentInput?.value || '',
    });
  }

  const payload = await api('/api/reviews/monthly/save', {
    method: 'POST',
    body: JSON.stringify({ year, month, department_id: departmentId, entries }),
  });

  state.monthlySnapshot = payload;
  renderMonthlyReview();
  showToast('Оценки сохранены');
}

async function completeMonthlyReview() {
  const year = Number(document.getElementById('monthlyYear').value);
  const month = Number(document.getElementById('monthlyMonth').value);
  const departmentId = Number(document.getElementById('monthlyDepartment').value);

  await api('/api/reviews/monthly/complete', {
    method: 'POST',
    body: JSON.stringify({ year, month, department_id: departmentId }),
  });

  await loadMonthlyReview();
  showToast('Месяц завершен');
}

async function lockMonthlyReview() {
  const year = Number(document.getElementById('monthlyYear').value);
  const month = Number(document.getElementById('monthlyMonth').value);

  await api('/api/reviews/monthly/lock', {
    method: 'POST',
    body: JSON.stringify({ year, month }),
  });

  await loadMonthlyReview();
  showToast('Месяц заблокирован');
}

async function loadQuarterlyReview() {
  const year = document.getElementById('quarterYear').value;
  const quarter = document.getElementById('quarterNumber').value;
  const departmentId = document.getElementById('quarterDepartment').value;

  if (!departmentId) {
    showToast('Выберите отдел', true);
    return;
  }

  const params = new URLSearchParams({ year, quarter, department_id: departmentId });
  const payload = await api(`/api/reviews/quarterly?${params.toString()}`);
  state.quarterSnapshot = payload;
  renderQuarterlyReview();
}

function renderQuarterlyReview() {
  const payload = state.quarterSnapshot;
  if (!payload) return;

  document.getElementById('quarterMeta').textContent =
    `Квартальный средний балл отдела: ${payload.department_quarter_avg ?? '-'}`;

  const thead = document.querySelector('#quarterTable thead');
  const tbody = document.querySelector('#quarterTable tbody');

  thead.innerHTML = `
    <tr>
      <th>Сотрудник</th>
      <th>Месяц ${payload.months[0]}</th>
      <th>Месяц ${payload.months[1]}</th>
      <th>Месяц ${payload.months[2]}</th>
      <th>Квартальные пункты</th>
      <th>Квартальный средний балл</th>
    </tr>
  `;

  tbody.innerHTML = '';
  for (const item of payload.employees) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.employee.full_name}</td>
      <td>${item.monthly_scores[payload.months[0]] ?? '-'}</td>
      <td>${item.monthly_scores[payload.months[1]] ?? '-'}</td>
      <td>${item.monthly_scores[payload.months[2]] ?? '-'}</td>
      <td>${item.quarter_points}</td>
      <td>${item.quarter_avg_score ?? '-'}</td>
    `;
    tbody.appendChild(tr);
  }
}

function renderBonusResults(results) {
  const tbody = document.querySelector('#bonusTable tbody');
  tbody.innerHTML = '';

  for (const item of results) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.employee.full_name}</td>
      <td>${item.quarter_points}</td>
      <td>${item.quarter_avg_score ?? '-'}</td>
      <td>${item.is_eligible ? 'Да' : 'Нет'}</td>
      <td>${Number(item.bonus_amount).toFixed(2)}</td>
    `;
    tbody.appendChild(tr);
  }
}

async function calculateBonus(event) {
  event.preventDefault();
  const form = document.getElementById('bonusForm');
  const data = collectFormData(form);

  const payload = await api('/api/bonus/calculate', {
    method: 'POST',
    body: JSON.stringify(data),
  });

  renderBonusResults(payload.results);
  showToast('Премия рассчитана');
}

async function loadSavedBonus() {
  const year = document.getElementById('bonusYear').value;
  const quarter = document.getElementById('bonusQuarter').value;
  const departmentId = document.getElementById('bonusDepartment').value;

  const params = new URLSearchParams({ year, quarter, department_id: departmentId });
  const payload = await api(`/api/bonus/results?${params.toString()}`);

  const rows = payload.results.map((item) => ({
    employee: { full_name: item.full_name },
    quarter_points: item.quarter_points,
    quarter_avg_score: item.quarter_avg_score,
    is_eligible: !!item.is_eligible,
    bonus_amount: item.bonus_amount,
  }));

  renderBonusResults(rows);
  showToast('Загружен сохраненный расчет');
}

async function loadEmployeeReport() {
  const employeeId = document.getElementById('reportsEmployee').value;
  const year = document.getElementById('reportsYear').value;
  const quarter = document.getElementById('reportsQuarter').value;

  if (!employeeId) {
    showToast('Выберите сотрудника', true);
    return;
  }

  const params = new URLSearchParams({ year, quarter });
  const payload = await api(`/api/reports/employee/${employeeId}?${params.toString()}`);
  document.getElementById('reportOutput').textContent = JSON.stringify(payload, null, 2);
}

async function loadDepartmentReport() {
  const year = document.getElementById('reportsYear').value;
  const quarter = document.getElementById('reportsQuarter').value;
  const departmentId = document.getElementById('reportsDepartment').value;

  if (!departmentId) {
    showToast('Выберите отдел', true);
    return;
  }

  const params = new URLSearchParams({ year, quarter, department_id: departmentId });
  const payload = await api(`/api/reports/department?${params.toString()}`);
  document.getElementById('reportOutput').textContent = JSON.stringify(payload, null, 2);
}

function triggerExport(type) {
  const year = document.getElementById('reportsYear').value;
  const quarter = document.getElementById('reportsQuarter').value;
  const departmentId = document.getElementById('reportsDepartment').value;

  if (!departmentId) {
    showToast('Выберите отдел', true);
    return;
  }

  const params = new URLSearchParams({ year, quarter, department_id: departmentId });
  window.open(`/api/reports/quarter/export.${type}?${params.toString()}`, '_blank');
}

async function createBackup() {
  const payload = await api('/api/backup', { method: 'POST', body: JSON.stringify({}) });
  showToast(`Backup создан: ${payload.backup_file}`);
}

function bindEvents() {
  document.getElementById('departmentForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = collectFormData(form);

    if (data.id) {
      await api(`/api/departments/${data.id}`, { method: 'PUT', body: JSON.stringify(data) });
      showToast('Отдел обновлен');
    } else {
      await api('/api/departments', { method: 'POST', body: JSON.stringify(data) });
      showToast('Отдел создан');
    }

    resetDepartmentForm();
    await loadDepartments();
    await loadEmployees();
  });

  document.getElementById('departmentReset').addEventListener('click', resetDepartmentForm);

  document.querySelector('#departmentsTable tbody').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action="edit-department"]');
    if (!button) return;

    const department = state.departments.find((x) => x.id === Number(button.dataset.id));
    if (!department) return;

    const form = document.getElementById('departmentForm');
    setFormField(form, 'id', department.id);
    setFormField(form, 'name', department.name);
    setFormCheckbox(form, 'is_active', !!department.is_active);
  });

  document.getElementById('employeeForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = collectFormData(form);

    if (data.id) {
      await api(`/api/employees/${data.id}`, { method: 'PUT', body: JSON.stringify(data) });
      showToast('Сотрудник обновлен');
    } else {
      await api('/api/employees', { method: 'POST', body: JSON.stringify(data) });
      showToast('Сотрудник создан');
    }

    resetEmployeeForm();
    await loadEmployees();
  });

  document.getElementById('employeeReset').addEventListener('click', resetEmployeeForm);
  document.getElementById('employeeReload').addEventListener('click', loadEmployees);

  document.querySelector('#employeesTable tbody').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action="edit-employee"]');
    if (!button) return;

    const employee = state.employees.find((x) => x.id === Number(button.dataset.id));
    if (!employee) return;

    const form = document.getElementById('employeeForm');
    setFormField(form, 'id', employee.id);
    setFormField(form, 'full_name', employee.full_name);
    setFormField(form, 'department_id', employee.department_id);
    setFormField(form, 'position', employee.position || '');
    setFormField(form, 'hire_date', employee.hire_date);
    setFormField(form, 'dismissal_date', employee.dismissal_date || '');
    setFormField(form, 'notes', employee.notes || '');
    setFormCheckbox(form, 'is_active', !!employee.is_active);
  });

  document.getElementById('criterionForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = collectFormData(form);

    if (data.id) {
      await api(`/api/criteria/${data.id}`, { method: 'PUT', body: JSON.stringify(data) });
      showToast('Критерий обновлен');
    } else {
      await api('/api/criteria', { method: 'POST', body: JSON.stringify(data) });
      showToast('Критерий создан');
    }

    resetCriterionForm();
    await loadCriteria();
  });

  document.getElementById('criterionReset').addEventListener('click', resetCriterionForm);

  document.querySelector('#criteriaTable tbody').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action="edit-criterion"]');
    if (!button) return;

    const criterion = state.criteria.find((x) => x.id === Number(button.dataset.id));
    if (!criterion) return;

    const form = document.getElementById('criterionForm');
    setFormField(form, 'id', criterion.id);
    setFormField(form, 'name', criterion.name);
    setFormField(form, 'description', criterion.description || '');
    setFormField(form, 'weight', criterion.weight);
    setFormField(form, 'sort_order', criterion.sort_order);
    setFormCheckbox(form, 'is_active', !!criterion.is_active);
  });

  document.getElementById('monthlyLoad').addEventListener('click', async () => {
    try {
      await loadMonthlyReview();
      showToast('Месяц загружен');
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.getElementById('monthlySave').addEventListener('click', async () => {
    try {
      await saveMonthlyReview();
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.getElementById('monthlyComplete').addEventListener('click', async () => {
    try {
      await completeMonthlyReview();
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.getElementById('monthlyLock').addEventListener('click', async () => {
    try {
      await lockMonthlyReview();
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.getElementById('quarterLoad').addEventListener('click', async () => {
    try {
      await loadQuarterlyReview();
      showToast('Квартальный обзор обновлен');
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.getElementById('bonusForm').addEventListener('submit', async (event) => {
    try {
      await calculateBonus(event);
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.getElementById('bonusLoadSaved').addEventListener('click', async () => {
    try {
      await loadSavedBonus();
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.getElementById('reportEmployeeBtn').addEventListener('click', async () => {
    try {
      await loadEmployeeReport();
      showToast('Отчет сотрудника готов');
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.getElementById('reportDepartmentBtn').addEventListener('click', async () => {
    try {
      await loadDepartmentReport();
      showToast('Отчет отдела готов');
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.getElementById('exportCsvBtn').addEventListener('click', () => triggerExport('csv'));
  document.getElementById('exportXlsxBtn').addEventListener('click', () => triggerExport('xlsx'));
  document.getElementById('backupBtn').addEventListener('click', async () => {
    try {
      await createBackup();
    } catch (error) {
      showToast(error.message, true);
    }
  });

  document.getElementById('reportsDepartment').addEventListener('change', async () => {
    const departmentId = document.getElementById('reportsDepartment').value;
    const params = new URLSearchParams();
    if (departmentId) params.set('department_id', departmentId);
    const employees = await api(`/api/employees?${params.toString()}`);
    fillSelect(document.getElementById('reportsEmployee'), employees);
  });
}

async function init() {
  setupTabs();
  setDefaultDates();
  bindEvents();

  try {
    await loadDepartments();
    await loadEmployees();
    await loadCriteria();
  } catch (error) {
    showToast(error.message, true);
  }
}

init();
