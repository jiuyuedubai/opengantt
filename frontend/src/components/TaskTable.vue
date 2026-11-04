<template>
  <div class="task-table-wrap">
    <table class="task-table og-zebra">
      <thead>
        <tr>
          <th style="width: 64px" title="点击 ▶ 展开编辑开始/结束日期、进度说明与依赖">ID</th>
          <th style="width: 30%">任务名称</th>
          <th style="width: 170px">负责人</th>
          <th style="width: 64px">进度</th>
          <th style="width: 74px">状态</th>
          <th style="width: 34px" title="风险分级：🟢正常 🟡关注 🔴停滞（悬停查看原因）">风险</th>
          <th v-if="canEdit" style="width: 76px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!tasks.length">
          <td :colspan="canEdit ? 7 : 6" class="empty">暂无任务{{ canEdit ? "，点击「新增任务」开始排期" : "" }}</td>
        </tr>
        <template v-for="t in tasks" :key="t.id">
          <tr :class="{ 'main-row': true, done: t.progress >= 100 }">
            <td class="task-id">
              <button
                type="button"
                class="expander"
                :title="expandedId === t.id ? '收起' : '展开编辑日期、进度说明与依赖'"
                @click="toggleExpand(t)"
              >{{ expandedId === t.id ? "▼" : "▶" }}</button>
              <span :title="`任务 ID：${t.id}`">#{{ t.id }}</span>
            </td>
            <td><input v-model="t.name" :disabled="!rowEditable(t)" @change="save(t, { name: t.name })" maxlength="200" /></td>
            <td>
              <div v-if="rowEditable(t)" class="assignee-picker" @click.stop>
                <button
                  type="button"
                  class="assignee-summary"
                  :title="`负责人：${t.assignee || '未指定'}（点击选择，可多选）`"
                  @click="togglePicker($event, t)"
                >
                  {{ t.assignee || "未指定" }}
                </button>
                <div v-if="picker?.id === t.id" class="assignee-menu" :style="menuStyle">
                  <label v-for="u in users" :key="u.id" class="assignee-option">
                    <input
                      type="checkbox"
                      :checked="picker.ids.includes(u.id)"
                      @change="toggleDraft(u.id, $event.target.checked)"
                    />
                    <span class="assignee-name">{{ u.display_name }}</span>
                  </label>
                  <p v-if="!users.length" class="assignee-empty">暂无可选账号</p>
                  <div class="assignee-actions">
                    <button type="button" class="mini" @click="closePicker">取消</button>
                    <button type="button" class="mini primary" @click="confirmAssignees(t)">保存</button>
                  </div>
                </div>
              </div>
              <span v-else class="assignee-text">{{ t.assignee || "—" }}</span>
            </td>
            <td>
              <select :value="t.progress" :disabled="!rowEditable(t)" @change="save(t, { progress: Number($event.target.value) })">
                <option v-for="p in progressOptions" :key="p" :value="p">{{ p }}%</option>
              </select>
            </td>
            <td>
              <div class="status-wrap">
                <select
                  v-if="rowEditable(t)"
                  class="status-select"
                  :class="'st-' + t.status"
                  :value="t.status"
                  :title="t.status === 'blocked' ? '阻塞中（转阻塞需填原因）' : ''"
                  @change="onStatusChange(t, $event.target.value)"
                >
                  <option v-for="(label, key) in statusLabels" :key="key" :value="key">{{ label }}</option>
                </select>
                <span v-else class="status-text" :class="'st-' + t.status">{{ statusLabels[t.status] || t.status }}</span>
                <button
                  v-if="t.status === 'blocked' && rowEditable(t)"
                  type="button"
                  class="blocked-reason-btn"
                  :title="'阻塞原因：' + (t.blocked_reason || '未填写') + '（点击查看/修改）'"
                  @click="editBlockedReason(t)"
                >📝</button>
              </div>
              <div v-if="t.status === 'blocked' && t.blocked_reason" class="blocked-reason-text" :title="t.blocked_reason">
                ⛔ {{ t.blocked_reason }}
              </div>
            </td>
            <td class="risk-cell">
              <span
                class="risk-badge"
                :class="'risk-' + t.risk_level"
                :title="(t.risk_reasons && t.risk_reasons.length ? t.risk_reasons.join('；') : '正常')"
              >{{ riskIcon(t.risk_level) }}</span>
            </td>
            <td v-if="canEdit" class="ops">
              <button
                class="icon"
                :disabled="remindingId === t.id"
                :title="remindingId === t.id ? '提醒发送中…' : '在企业微信群提醒负责人（配置了企微手机号的负责人会被 @）'"
                @click="$emit('remind', t)"
              >{{ remindingId === t.id ? "…" : "🔔" }}</button>
              <button class="icon danger" title="删除任务" @click="$emit('remove', t)">✕</button>
            </td>
          </tr>
          <tr v-show="expandedId === t.id" class="detail-row">
            <td :colspan="canEdit ? 7 : 6">
              <div class="detail-grid">
                <label>开始日期
                  <input type="date" v-model="t.start_date" :disabled="!rowEditable(t)" @change="save(t, { start_date: t.start_date })" />
                </label>
                <label>结束日期
                  <input type="date" v-model="t.end_date" :disabled="!rowEditable(t)" @change="save(t, { end_date: t.end_date })" />
                </label>
                <label class="detail-grow">我的进度说明（按人独立填写，仅本人可见，自动汇总到我的工作日志）
                  <textarea
                    v-if="rowEditable(t)"
                    class="note-input"
                    rows="3"
                    :value="t.note"
                    @change="save(t, { note: $event.target.value })"
                    placeholder="记录我的今日进展，可换行输入多行…"
                    maxlength="500"
                  ></textarea>
                  <span v-else class="note-text">{{ t.note || "—" }}</span>
                </label>
                <label>依赖（前置任务 ID）
                  <input v-model="t.dependencies" :disabled="!rowEditable(t)" @change="save(t, { dependencies: t.dependencies })" placeholder="如 3,5" title="填前置任务的 ID（见左侧 ID 列），多个用英文逗号分隔" />
                </label>
              </div>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, onBeforeUnmount } from "vue";

const props = defineProps({
  tasks: { type: Array, required: true },
  /** 项目级编辑权限（管理员/本部门主管/项目负责人） */
  canEdit: { type: Boolean, default: false },
  /** 全部启用账号（负责人下拉） */
  users: { type: Array, default: () => [] },
  /** 当前登录用户 ID：被分配的任务即使无项目权限也可编辑 */
  currentUserId: { type: Number, default: null },
  /** 正在发送提醒的任务 ID（父组件持有请求状态，本组件仅展示） */
  remindingId: { type: Number, default: null },
});

const emit = defineEmits(["update", "remove", "remind"]);

/** 行折叠/展开：默认折叠，点击 ▶ 展开编辑详情（日期/进度说明/依赖） */
const expandedId = ref(null);

function toggleExpand(t) {
  expandedId.value = expandedId.value === t.id ? null : t.id;
}

const progressOptions = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100];

const statusLabels = {
  not_started: "未开始",
  in_progress: "进行中",
  blocked: "阻塞",
  paused: "暂停",
  done: "已完成",
  cancelled: "已取消",
};

function riskIcon(level) {
  return level === "stall" ? "🔴" : level === "watch" ? "🟡" : "🟢";
}

/** 状态变更：转阻塞时提示填写原因（后端强制校验） */
function onStatusChange(task, value) {
  if (value === "blocked" && task.status !== "blocked") {
    const reason = window.prompt(`将「${task.name}」标记为阻塞，请填写原因：`);
    if (reason === null) return; // 取消
    emit("update", task, { status: value, status_reason: reason });
    return;
  }
  emit("update", task, { status: value });
}

/** 查看/修改阻塞原因：blocked→blocked 提交新原因（后端追加一条状态日志，最近一条即当前原因） */
function editBlockedReason(task) {
  const current = task.blocked_reason || "";
  const reason = window.prompt(
    `「${task.name}」当前阻塞原因：\n${current || "（未填写）"}\n\n请输入新的阻塞原因（留空取消）：`,
    current
  );
  if (reason === null) return; // 取消
  const trimmed = reason.trim();
  if (!trimmed) return;
  if (trimmed === current) return; // 未变更
  emit("update", task, { status: "blocked", status_reason: trimmed });
}

/** 行级编辑权限：项目可编辑（本部门成员/项目负责人/管理员），或该任务分配给了当前登录人（跨部门亦然） */
function rowEditable(t) {
  if (props.canEdit) return true;
  return props.currentUserId != null && (t.assignee_ids || []).includes(props.currentUserId);
}

// ---------- 负责人多选选择器（草稿 + 确认保存） ----------
const picker = ref(null); // { id: 任务ID, ids: 草稿勾选集合 }
const menuStyle = ref({});

/** 点击切换：打开时记录草稿并按按钮位置定位面板（fixed 定位，不被表格滚动容器裁剪） */
function togglePicker(e, t) {
  if (picker.value?.id === t.id) {
    picker.value = null;
    return;
  }
  picker.value = { id: t.id, ids: [...(t.assignee_ids || [])] };
  const rect = e.currentTarget.getBoundingClientRect();
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - 240));
  const top = Math.min(rect.bottom + 4, window.innerHeight - 280);
  menuStyle.value = { left: `${left}px`, top: `${top}px` };
}

function closePicker() {
  picker.value = null;
}

function confirmAssignees(task) {
  save(task, { assignee_ids: [...picker.value.ids] });
  picker.value = null;
}

function toggleDraft(userId, checked) {
  const ids = new Set(picker.value.ids);
  if (checked) ids.add(userId);
  else ids.delete(userId);
  picker.value.ids = [...ids];
}

/** 点击面板外或按 Esc 时收起（面板内点击已 stopPropagation） */
function onDocClick() {
  if (picker.value) picker.value = null;
}
function onDocKeydown(e) {
  if (e.key === "Escape" && picker.value) picker.value = null;
}
window.addEventListener("click", onDocClick);
window.addEventListener("keydown", onDocKeydown);
onBeforeUnmount(() => {
  window.removeEventListener("click", onDocClick);
  window.removeEventListener("keydown", onDocKeydown);
});

function save(task, patch) {
  emit("update", task, patch);
}
</script>

<style scoped>
.task-table-wrap {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: auto;
  max-height: 340px;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

th {
  position: sticky;
  top: 0;
  background: #eef3f9;
  text-align: left;
  padding: 8px 6px;
  font-weight: 500;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
  color: #3d4f63;
}

td {
  padding: 4px 6px;
  border-bottom: 1px solid #f0f3f8;
}

td.empty {
  text-align: center;
  color: var(--muted);
  padding: 24px;
}

td.task-id {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  white-space: nowrap;
}

/* 行折叠：展开箭头与详情区 */
.expander {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--muted);
  font-size: 10px;
  padding: 0 2px;
}

.expander:hover {
  color: var(--primary);
}

tr.main-row {
  cursor: default;
}

tr.detail-row td {
  background: #f7fafd;
  padding: 10px 12px;
}

.detail-grid {
  display: flex;
  gap: 14px;
  align-items: flex-end;
  flex-wrap: wrap;
}

.detail-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  color: var(--muted);
}

.detail-grid label.detail-grow {
  flex: 1;
  min-width: 220px;
}

.detail-grid input {
  min-width: 130px;
}

tr.done td {
  background: #f7faf7;
}

input,
select {
  width: 100%;
  border: 1px solid transparent;
  background: transparent;
  padding: 4px 6px;
  border-radius: 4px;
}

input:disabled,
select:disabled {
  color: var(--text);
  opacity: 1;
}

input:hover:not(:disabled),
select:hover:not(:disabled) {
  border-color: var(--border);
}

input:focus,
select:focus {
  border-color: var(--primary);
  background: #fff;
}

.assignee-text {
  color: var(--muted);
  padding: 0 2px;
}

/* 负责人多选选择器（fixed 定位面板，不被表格滚动容器裁剪） */
.assignee-summary {
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 12.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 130px;
}

.assignee-summary:hover {
  background: #eef5fd;
  border-color: transparent;
  color: var(--primary);
}

.assignee-menu {
  position: fixed;
  z-index: 300;
  width: 200px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(15, 40, 70, 0.18);
  padding: 6px;
  max-height: 240px;
  overflow-y: auto;
}

.assignee-option {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
}

/* 抵消本组件对 table 输入框的 width:100% 样式，避免勾选框挤掉姓名 */
.assignee-option input[type="checkbox"] {
  width: auto;
  flex: 0 0 auto;
  margin: 0;
}

.assignee-option:hover {
  background: #f0f5ff;
}

.assignee-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assignee-empty {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  padding: 4px 8px;
}

.assignee-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
}

.status-wrap {
  display: flex;
  align-items: center;
  gap: 4px;
}

.blocked-reason-btn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 13px;
  padding: 0 2px;
}

.blocked-reason-text {
  font-size: 11px;
  color: #d46b08;
  margin-top: 2px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-select,
.status-text {
  font-size: 12px;
}

.status-select.st-blocked,
.status-text.st-blocked {
  color: var(--danger);
  font-weight: 600;
}

.status-select.st-done,
.status-text.st-done {
  color: var(--success);
}

.status-select.st-paused,
.status-text.st-paused {
  color: var(--warning);
}

.risk-cell {
  text-align: center;
}

.risk-badge {
  cursor: help;
  font-size: 13px;
}

.note-text {
  color: var(--muted);
  font-size: 12px;
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 多行进度说明输入域：随内容自适应高度，失焦自动保存 */
.note-input {
  width: 100%;
  min-height: 56px;
  resize: vertical;
  font: inherit;
  line-height: 1.5;
  padding: 6px 8px;
}

button.icon {
  border: none;
  background: none;
  padding: 2px 6px;
  color: var(--muted);
}

button.icon:hover {
  color: var(--danger);
}
</style>
