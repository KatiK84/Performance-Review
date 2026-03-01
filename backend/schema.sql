PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    department_id INTEGER NOT NULL,
    position TEXT,
    hire_date TEXT NOT NULL,
    dismissal_date TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_employees_department ON employees(department_id);
CREATE INDEX IF NOT EXISTS idx_employees_active ON employees(is_active);

CREATE TABLE IF NOT EXISTS criteria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    weight REAL NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_criteria_active ON criteria(is_active, sort_order);

CREATE TABLE IF NOT EXISTS periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'completed', 'locked')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(year, month)
);

CREATE TABLE IF NOT EXISTS monthly_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    period_id INTEGER NOT NULL,
    criterion_id INTEGER NOT NULL,
    score INTEGER NOT NULL CHECK (score BETWEEN 1 AND 10),
    comment TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(employee_id, period_id, criterion_id),
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
    FOREIGN KEY (period_id) REFERENCES periods(id) ON DELETE CASCADE,
    FOREIGN KEY (criterion_id) REFERENCES criteria(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_monthly_scores_period ON monthly_scores(period_id);
CREATE INDEX IF NOT EXISTS idx_monthly_scores_employee ON monthly_scores(employee_id);

CREATE TABLE IF NOT EXISTS bonus_pools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    department_id INTEGER NOT NULL,
    bonus_pool_amount REAL NOT NULL,
    minimum_threshold_type TEXT NOT NULL CHECK (minimum_threshold_type IN ('avg_score', 'points')),
    minimum_threshold_value REAL NOT NULL,
    distribution_mode TEXT NOT NULL CHECK (distribution_mode IN ('eligible_full_points', 'above_threshold_only')),
    calculated_at TEXT,
    is_locked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(year, quarter, department_id),
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS bonus_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    department_id INTEGER NOT NULL,
    employee_id INTEGER NOT NULL,
    quarter_points REAL NOT NULL,
    quarter_avg_score REAL,
    is_eligible INTEGER NOT NULL DEFAULT 0,
    bonus_amount REAL NOT NULL DEFAULT 0,
    calculation_details TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(year, quarter, department_id, employee_id),
    FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bonus_results_period_dept ON bonus_results(year, quarter, department_id);
