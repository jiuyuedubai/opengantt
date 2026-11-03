<template>
  <section class="panel">
    <header class="panel-head">
      <strong>每日进度记录</strong>
      <span class="panel-sub">每天自动保存每项任务的进度；带说明的记录会汇总进工作日志</span>
      <div class="filter">
        <button :class="{ primary: filter === 'today' }" @click="setFilter('today')">今天</button>
        <button :class="{ primary: filter === 'all' }" @click="setFilter('all')">全部</button>
      </div>
    </header>

    <div class="panel-box">
      <table v-if="logs.length" class="log-table og-zebra">
      <thead>
        <tr>
          <th style="width: 96px">日期</th>
          <th>任务</th>
          <th style="width: 90px" title="任务的当前负责人">负责人</th>
          <th style="width: 66px">进度</th>
          <th>说明</th>
          <th style="width: 96px" title="提交这条进度记录的人（可能是负责人本人、主管或系统自动快照）">记录人</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in logs" :key="r.id">
          <td>{{ r.log_date }}</td>
          <td class="task-cell">#{{ r.task_id }} {{ r.task_name }}</td>
          <td>{{ r.assignee || "未指定" }}</td>
          <td>
            <span class="prog-badge" :class="progClass(r.progress)">{{ r.progress }}%</span>
          </td>
          <td class="note-cell" :title="r.note">{{ r.note || "—" }}</td>
          <td>{{ r.user_name || "系统" }}</td>
        </tr>
      </tbody>
    </table>
      <p v-else class="empty-tip">暂无进度记录{{ filter === "today" ? "（今天还没有更新）" : "" }}</p>
    </div>
  </section>
</template>

<script setup>
import { ref, watch } from "vue";
import { api } from "../api/client.js";

const props = defineProps({
  projectId: { type: Number, default: null },
  refreshKey: { type: Number, default: 0 },
});

const logs = ref([]);
const filter = ref("today");

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function load() {
  if (!props.projectId) {
    logs.value = [];
    return;
  }
  try {
    logs.value = await api.listProgressLogs(
      props.projectId,
      filter.value === "today" ? todayStr() : null
    );
  } catch {
    logs.value = [];
  }
}

function setFilter(f) {
  filter.value = f;
  load();
}

function progClass(p) {
  if (p >= 100) return "done";
  if (p > 0) return "doing";
  return "todo";
}

watch(() => props.projectId, load, { immediate: true });
watch(() => props.refreshKey, load);
</script>

<style scoped>
.panel {
  margin-bottom: 16px;
}

/* 蓝条签名标题（与 og-panel-title 一致） */
.panel-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding-left: 10px;
  border-left: 4px solid var(--primary);
  margin: 18px 0 10px;
  font-size: 15px;
  line-height: 1.3;
  flex-wrap: wrap;
}

.panel-head strong {
  font-weight: 600;
}

.panel-sub {
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
  flex: 1;
  min-width: 0;
}

.panel-box {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  overflow: hidden;
}

.filter {
  display: flex;
  gap: 4px;
}

.filter button {
  padding: 3px 12px;
  font-size: 12px;
}

.log-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.log-table th {
  text-align: left;
  padding: 7px 12px;
  background: #f0f5fb;
  border-bottom: 1px solid var(--border);
  font-weight: 500;
}

.log-table td {
  padding: 6px 12px;
  border-bottom: 1px solid #f0f3f8;
}

.task-cell {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.note-cell {
  max-width: 340px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
}

.prog-badge {
  display: inline-block;
  min-width: 44px;
  text-align: center;
  font-size: 12px;
  border-radius: 999px;
  padding: 1px 8px;
}

.prog-badge.done {
  background: #e5f5ec;
  color: var(--success);
}

.prog-badge.doing {
  background: #e8f1fb;
  color: var(--primary);
}

.prog-badge.todo {
  background: #f2f4f7;
  color: var(--muted);
}

.empty-tip {
  color: var(--muted);
  font-size: 13px;
  text-align: center;
  padding: 20px;
  margin: 0;
}
</style>
