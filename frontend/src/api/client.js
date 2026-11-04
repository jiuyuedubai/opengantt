/**
 * 类型化 fetch 封装：
 * - 会话基于 httpOnly Cookie（同源自动携带），令牌不落 localStorage
 * - 401 统一派发 og:unauthorized 事件，由应用层弹出登录页
 * - 兼容两种错误结构：{error:{code,message}} 与 {detail}
 */

const BASE = ""; // 同源部署 + Vite 代理，均使用相对路径

class ApiError extends Error {
  constructor(message, code, status) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function request(method, url, body, opts = {}) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    if (body instanceof FormData) {
      init.body = body; // 浏览器自动设置 multipart 边界
    } else {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
  }
  if (opts.query) {
    const qs = new URLSearchParams(
      Object.entries(opts.query).filter(([, v]) => v !== "" && v != null)
    );
    if (qs.toString()) url += (url.includes("?") ? "&" : "?") + qs;
  }
  let resp;
  try {
    resp = await fetch(BASE + url, init);
  } catch {
    throw new ApiError("网络连接失败，请检查服务是否运行", "network_error", 0);
  }
  if (resp.status === 401 && !url.startsWith("/api/auth/login")) {
    window.dispatchEvent(new CustomEvent("og:unauthorized", { detail: await resp.text() }));
    throw new ApiError("请先登录", "unauthorized", 401);
  }
  if (resp.status === 204) return null;
  const text = await resp.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!resp.ok) {
    const message =
      data?.error?.message ?? (typeof data?.detail === "string" ? data.detail : null) ??
      `请求失败（${resp.status}）`;
    throw new ApiError(message, data?.error?.code ?? "unknown", resp.status);
  }
  return data;
}

export const api = {
  // 认证
  login: (username, password) => request("POST", "/api/auth/login", { username, password }),
  logout: () => request("POST", "/api/auth/logout"),
  me: () => request("GET", "/api/auth/me"),
  changePassword: (oldPassword, newPassword) =>
    request("POST", "/api/auth/change-password", {
      old_password: oldPassword,
      new_password: newPassword,
    }),

  // 项目
  listProjects: () => request("GET", "/api/projects"),
  createProject: (payload) => request("POST", "/api/projects", payload),
  updateProject: (id, payload) => request("PATCH", `/api/projects/${id}`, payload),
  deleteProject: (id) => request("DELETE", `/api/projects/${id}`),
  migrateProject: (id, department_id) =>
    request("POST", `/api/projects/${id}/migrate`, { department_id }),
  // 跨部门文档查询授权（员工端）
  requestDocAccess: (departmentId, expiresAt, note) =>
    request("POST", "/api/doc-access/requests", {
      department_id: departmentId,
      expires_at: expiresAt,
      note: note || "",
    }),
  myDocAccess: () => request("GET", "/api/doc-access/mine"),

  // 部门概览（全员可读，主页/部门页用）
  listDepartments: () => request("GET", "/api/departments"),

  // 用户列表（任务负责人选择用，最小信息）
  listUsers: () => request("GET", "/api/users"),

  // 全局搜索
  search: (q) => request("GET", "/api/search", undefined, { query: { q } }),

  // 统计（驾驶舱 / 投入度分析，主管与管理员）
  stats: {
    overview: () => request("GET", "/api/stats/overview"),
    userActivity: (days) => request("GET", "/api/stats/user-activity", undefined, { query: { days } }),
    progressTrend: (projectId) => request("GET", `/api/stats/progress-trend`, undefined, { query: { project_id: projectId } }),
    activityMatrix: (days) => request("GET", "/api/stats/activity-matrix", undefined, { query: { days } }),
  },

  // 任务
  listTasks: (projectId) => request("GET", `/api/projects/${projectId}/tasks`),
  createTask: (projectId, payload) => request("POST", `/api/projects/${projectId}/tasks`, payload),
  updateTask: (projectId, taskId, payload) =>
    request("PATCH", `/api/projects/${projectId}/tasks/${taskId}`, payload),
  bulkUpdateTasks: (projectId, changes) =>
    request("PATCH", `/api/projects/${projectId}/tasks/bulk`, { changes }),
  deleteTask: (projectId, taskId) =>
    request("DELETE", `/api/projects/${projectId}/tasks/${taskId}`),
  remindTask: (projectId, taskId) =>
    request("POST", `/api/projects/${projectId}/tasks/${taskId}/remind`),

  // 每日任务（个人周期清单，日期恒为当天）
  listDailyTasks: () => request("GET", "/api/daily-tasks"),
  createDailyTask: (payload) => request("POST", "/api/daily-tasks", payload),
  updateDailyTask: (id, payload) => request("PATCH", `/api/daily-tasks/${id}`, payload),
  deleteDailyTask: (id) => request("DELETE", `/api/daily-tasks/${id}`),

  // 工作状态（自助设置）与进度文档树
  setWorkStatus: (workStatus, until) =>
    request("PATCH", "/api/users/me/work-status", {
      work_status: workStatus,
      work_status_until: until || null,
    }),
  documentTree: () => request("GET", "/api/documents/tree"),

  // 进度文档
  listDocuments: (projectId) => request("GET", `/api/projects/${projectId}/documents`),
  uploadDocument: (projectId, file, note) => {
    const form = new FormData();
    form.append("file", file);
    return request("POST", `/api/projects/${projectId}/documents`, form, { query: { note } });
  },
  // 批量上传（多选文件或整个文件夹）：逐个 append 到 files 列表，zip 由服务端自动解压；
  // XHR 实现 fetch 无法提供的上传进度（onProgress 回调 0-100）
  uploadDocumentsBulk: (projectId, files, note, onProgress) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.webkitRelativePath || f.name);
    const qs = new URLSearchParams({ note: note || "" }).toString();
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/projects/${projectId}/documents?${qs}`);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      };
      xhr.onload = () => {
        let data = null;
        try {
          data = JSON.parse(xhr.responseText || "null");
        } catch {
          data = null;
        }
        if (xhr.status === 401) {
          window.dispatchEvent(new CustomEvent("og:unauthorized", { detail: xhr.responseText }));
          reject(new ApiError("请先登录", "unauthorized", 401));
          return;
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(data);
          return;
        }
        const message =
          data?.error?.message ?? (typeof data?.detail === "string" ? data.detail : null) ??
          `上传失败（${xhr.status}）`;
        reject(new ApiError(message, data?.error?.code ?? "unknown", xhr.status));
      };
      xhr.onerror = () => reject(new ApiError("网络连接失败，请检查服务是否运行", "network_error", 0));
      xhr.send(form);
    });
  },
  deleteDocument: (docId) => request("DELETE", `/api/documents/${docId}`),
  // 下载走 <a href> 由浏览器携带 Cookie 完成，无需 fetch

  // 进度记录与每日工作日志
  listProgressLogs: (projectId, date) =>
    request("GET", `/api/projects/${projectId}/progress-logs`, undefined, { query: { date } }),
  /** 工作日志为 Markdown 纯文本，走独立 fetch */
  dailyReport: async (date) => {
    const url = BASE + "/api/reports/daily" + (date ? `?date=${date}` : "");
    const resp = await fetch(url);
    if (!resp.ok) {
      if (resp.status === 401) {
        window.dispatchEvent(new CustomEvent("og:unauthorized"));
        throw new ApiError("请先登录", "unauthorized", 401);
      }
      throw new ApiError("工作日志获取失败", "unknown", resp.status);
    }
    return resp.text();
  },
  weeklyReport: async (date) => {
    const url = BASE + "/api/reports/weekly" + (date ? `?date=${date}` : "");
    const resp = await fetch(url);
    if (!resp.ok) {
      if (resp.status === 401) {
        window.dispatchEvent(new CustomEvent("og:unauthorized"));
        throw new ApiError("请先登录", "unauthorized", 401);
      }
      throw new ApiError("工作周报获取失败", "unknown", resp.status);
    }
    return resp.text();
  },
  getDailyDecisions: (date) => request("GET", `/api/reports/daily/decisions`, undefined, { query: { date } }),
  saveDailyDecisions: (date, decisions) =>
    request("PUT", "/api/reports/daily/decisions", { date, decisions }),
  /** 五、补充事项：临时事项（每行一条），保存后进入当日日志 */
  saveDailyExtras: (date, extras) =>
    request("PUT", "/api/reports/daily/decisions", { date, extras }),
  getAutoSaveStatus: () => request("GET", "/api/reports/auto-save-status"),
  /** 管理员导出某用户全部历史工作日志（Markdown 文本） */
  adminUserHistory: async (userId) => {
    const resp = await fetch(`${BASE}/api/reports/user/${userId}/history`);
    if (!resp.ok) {
      if (resp.status === 401) {
        window.dispatchEvent(new CustomEvent("og:unauthorized"));
        throw new ApiError("请先登录", "unauthorized", 401);
      }
      if (resp.status === 403) throw new ApiError("仅管理员可导出", "forbidden", 403);
      throw new ApiError("导出失败", "unknown", resp.status);
    }
    return resp.text();
  },

  // 管理员后台
  admin: {
    listUsers: () => request("GET", "/api/admin/users"),
    createUser: (payload) => request("POST", "/api/admin/users", payload),
    updateUser: (id, payload) => request("PATCH", `/api/admin/users/${id}`, payload),
    resetPassword: (id, newPassword) =>
      request("POST", `/api/admin/users/${id}/reset-password`, { new_password: newPassword }),
    deleteUser: (id) => request("DELETE", `/api/admin/users/${id}`),
    listDepartments: () => request("GET", "/api/admin/departments"),
    createDepartment: (payload) => request("POST", "/api/admin/departments", payload),
    updateDepartment: (id, payload) => request("PATCH", `/api/admin/departments/${id}`, payload),
    deleteDepartment: (id) => request("DELETE", `/api/admin/departments/${id}`),
    stats: () => request("GET", "/api/admin/stats"),
    // 操作审计日志（仅管理员）
    auditLogs: (params) =>
      request("GET", "/api/audit-logs", undefined, {
        query: {
          user_id: params.user_id || "",
          action: params.action || "",
          start_date: params.start_date || "",
          end_date: params.end_date || "",
          page: params.page || 1,
          page_size: params.page_size || 20,
        },
      }),
    auditActions: () => request("GET", "/api/audit-logs/actions"),
    wecomTestPush: (payload) => request("POST", "/api/admin/wecom/test-push", payload),
    // 数据备份与回退
    listBackups: () => request("GET", "/api/admin/backups"),
    createBackup: () => request("POST", "/api/admin/backups"),
    restoreBackup: (filename) => request("POST", "/api/admin/backups/restore", { filename }),
    deleteBackups: (filenames) => request("POST", "/api/admin/backups/delete", { filenames }),
    // 跨部门文档查询授权（管理员）
    listDocAccess: (status) => request("GET", "/api/doc-access/all", undefined, { query: status ? { status } : {} }),
    grantDocAccess: (userId, departmentId, expiresAt) =>
      request("POST", "/api/doc-access/grant", { user_id: userId, department_id: departmentId, expires_at: expiresAt }),
    decideDocAccess: (grantId, action, expiresAt) =>
      request("POST", `/api/doc-access/${grantId}/decide`, { action, expires_at: expiresAt || null }),
    // 文档批量删除（管理员，按上传人/日期）
    docBulkStats: (userId, date) =>
      request("GET", "/api/admin/documents/bulk-stats", undefined, { query: { user_id: userId, date: date || "" } }),
    docBulkDelete: (userId, date) =>
      request("POST", "/api/admin/documents/bulk-delete", { user_id: userId || null, date: date || null }),
    // 绩效考核（管理员）
    listPerfTemplates: () => request("GET", "/api/admin/performance/templates"),
    uploadPerfTemplate: (userId, file) => {
      const fd = new FormData();
      fd.append("user_id", userId);
      fd.append("file", file);
      return request("POST", "/api/admin/performance/templates", fd);
    },
    deletePerfTemplate: (id) => request("DELETE", `/api/admin/performance/templates/${id}`),
    generatePerf: (userIds, period, aiScore) =>
      request("POST", "/api/admin/performance/generate", { user_ids: userIds, period, ai_score: !!aiScore }),
    listPerfResults: (period) => request("GET", "/api/admin/performance/results", undefined, { query: period ? { period } : {} }),
  },
};

export { ApiError };
