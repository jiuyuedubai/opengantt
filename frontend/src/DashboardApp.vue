<template>
  <div v-if="user">
    <header class="og-navbar">
      <a class="brand" href="/">
        <img src="/favicon.svg" alt="logo" width="26" height="26" />
        <div>
          <h1>OpenGantt 驾驶舱</h1>
          <p class="sub">进度总览 · 停滞追踪 · 投入度分析</p>
        </div>
      </a>
      <div class="nav-actions">
        <label class="proj-pick">
          统计范围
          <select v-model.number="projectId" @change="refresh">
            <option :value="0">全部项目</option>
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </label>
        <span class="og-user-chip">
          <b>{{ user?.display_name }}</b>
          <a class="og-nav-link" href="/">← 返回</a>
          <button @click="logout">退出</button>
        </span>
      </div>
    </header>

    <div class="page">
      <p v-if="!allowed" class="state">驾驶舱仅对主管与管理员开放。当前角色：{{ user.role }}。</p>
      <p v-else-if="err" class="state">{{ err }}</p>
      <div v-else>
        <div class="kpi-row">
          <div v-for="k in kpis" :key="k.label" class="kpi" :class="k.cls">
            <b>{{ k.value }}</b><span>{{ k.label }}</span>
          </div>
        </div>

        <div class="grid">
          <div class="card wide">
            <div class="card-title">{{ barTitle }} <small>柱=平均进度 · 右轴=逾期/停滞数</small></div>
            <div ref="deptChartEl" class="chart"></div>
          </div>
          <div class="card">
            <div class="card-title">任务状态分布</div>
            <div ref="statusChartEl" class="chart"></div>
          </div>
          <div class="card wide">
            <div class="card-title">项目进度趋势 <small>实线=实际平均进度 · 虚线=期望进度</small></div>
            <div ref="trendChartEl" class="chart"></div>
          </div>
          <div class="card">
            <div class="card-title">{{ activityTitle }}</div>
            <div ref="activityChartEl" class="chart"></div>
          </div>
          <div class="card wide">
            <div class="card-title">活跃热力图（每人每日进度更新次数）</div>
            <div ref="heatChartEl" class="chart tall"></div>
          </div>
        </div>

        <div class="grid lists">
          <div class="card">
            <div class="card-title danger">🔴 已逾期（{{ overview?.overdue_list.length ?? 0 }}）</div>
            <ul class="mini-list">
              <li v-for="t in overview?.overdue_list ?? []" :key="'o' + t.id">
                <b>#{{ t.id }} {{ t.name }}</b>
                <small>{{ t.project_name }} · {{ t.assignee }} · 进度 {{ t.progress }}% · 计划结束 {{ t.end_date }}</small>
              </li>
              <li v-if="!overview?.overdue_list.length" class="none">无逾期任务 🎉</li>
            </ul>
          </div>
          <div class="card">
            <div class="card-title danger">🟡 停滞 / 阻塞（{{ overview?.stalled_list.length ?? 0 }}）</div>
            <ul class="mini-list">
              <li v-for="t in overview?.stalled_list ?? []" :key="'s' + t.id">
                <b>#{{ t.id }} {{ t.name }}</b>
                <small>{{ t.project_name }} · {{ t.assignee }} · 进度 {{ t.progress }}% · {{ (t.reasons || []).join('；') }}</small>
              </li>
              <li v-if="!overview?.stalled_list.length" class="none">无停滞任务 🎉</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  </div>
  <p v-else class="state plain">正在验证登录…</p>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from "vue";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart, HeatmapChart } from "echarts/charts";
import {
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { api, ApiError } from "./api/client.js";

echarts.use([BarChart, LineChart, PieChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent, VisualMapComponent, CanvasRenderer]);

const STATUS_LABELS = {
  not_started: "未开始", in_progress: "进行中", blocked: "阻塞",
  paused: "暂停", done: "已完成", cancelled: "已取消",
};
const PIE_COLORS = { 未开始: "#b9c6d6", 进行中: "#1a6fb5", 阻塞: "#d9534f", 暂停: "#e8a23d", 已完成: "#2e9e5b", 已取消: "#9aa5b1" };

const user = ref(null);
const allowed = ref(false);
const err = ref("");
const overview = ref(null);
const projects = ref([]);
const projectId = ref(0); // 0 = 全部项目
const activityDays = 14;

const kpis = ref([]);
const barTitle = ref("部门进度总览");
const activityTitle = ref("员工投入度（近 14 天更新次数）");

const deptChartEl = ref(null);
const statusChartEl = ref(null);
const trendChartEl = ref(null);
const activityChartEl = ref(null);
const heatChartEl = ref(null);
let charts = [];
let ro = null; // ResizeObserver：视口/容器尺寸变化时重绘，避免仅靠 window resize 的时序空白
const todayStr = () => new Date().toISOString().slice(0, 10);
const isActive = (t) => !["done", "cancelled"].includes(t.status || "");

function makeChart(el, option) {
  if (!el) return null;
  const inst = echarts.init(el);
  inst.setOption(option);
  charts.push(inst);
  if (ro) ro.disconnect();
  ro = new ResizeObserver(() => {
    charts.forEach((c) => c.resize());
  });
  ro.observe(el);
  return inst;
}

/* ---------- 全部项目：全局接口渲染 ---------- */
function renderGlobal() {
  const ov = overview.value;
  kpis.value = [
    { value: ov.totals.project_count, label: "项目总数", cls: "" },
    { value: ov.totals.task_count, label: "任务总数", cls: "" },
    { value: ov.totals.overdue_count, label: "已逾期", cls: "warn" },
    { value: ov.totals.stalled_count, label: "停滞中", cls: "danger" },
  ];
  barTitle.value = "部门进度总览";
  activityTitle.value = `员工投入度（近 ${activityDays} 天更新次数）`;
  const names = ov.departments.map((x) => x.name);
  makeChart(deptChartEl.value, {
    tooltip: { trigger: "axis" },
    // 显式固定图例到顶部：legend.top 默认 'auto' 会把图例放进绘图区中部，
    // 与 x 轴 0 基准线及横轴标签重叠
    legend: { data: ["平均进度%", "逾期", "停滞"], top: 0, left: "center", itemGap: 18, textStyle: { fontSize: 12 } },
    grid: { left: 8, right: 16, top: 36, bottom: 4, containLabel: true },
    xAxis: {
      type: "category", data: names,
      axisLabel: { interval: 0, rotate: 0, width: 56, overflow: "break", lineHeight: 15, fontSize: 11 },
    },
    yAxis: [{ type: "value", max: 100 }, { type: "value", minInterval: 1 }],
    series: [
      { name: "平均进度%", type: "bar", data: ov.departments.map((x) => x.avg_progress), itemStyle: { color: "#1a6fb5" }, barMaxWidth: 30 },
      { name: "逾期", type: "bar", yAxisIndex: 1, data: ov.departments.map((x) => x.overdue), itemStyle: { color: "#d9534f" }, barMaxWidth: 18 },
      { name: "停滞", type: "bar", yAxisIndex: 1, data: ov.departments.map((x) => x.stalled), itemStyle: { color: "#e8a23d" }, barMaxWidth: 18 },
    ],
  });
  const dist = Object.entries(ov.status_distribution).filter(([, v]) => v > 0).map(([k, v]) => ({ name: STATUS_LABELS[k] || k, value: v }));
  makeChart(statusChartEl.value, {
    tooltip: { trigger: "item" },
    legend: { bottom: 0 },
    series: [{ type: "pie", radius: ["42%", "70%"], center: ["50%", "44%"], label: { formatter: "{b}\n{c}" }, data: dist.map((x) => ({ ...x, itemStyle: { color: PIE_COLORS[x.name] || "#8aa" } })) }],
  });
}

function renderTrend(trend) {
  makeChart(trendChartEl.value, {
    tooltip: { trigger: "axis" },
    legend: { data: ["实际", "期望"], top: 0, left: "center", itemGap: 18, textStyle: { fontSize: 12 } },
    grid: { left: 8, right: 16, top: 36, bottom: 0, containLabel: true },
    xAxis: { type: "category", data: trend.map((x) => x.date.slice(5)) },
    yAxis: { type: "value", max: 100 },
    series: [
      { name: "实际", type: "line", data: trend.map((x) => x.actual), smooth: true, itemStyle: { color: "#1a6fb5" }, areaStyle: { opacity: 0.12 } },
      { name: "期望", type: "line", data: trend.map((x) => x.expected ?? null), smooth: true, lineStyle: { type: "dashed", color: "#e8a23d" }, itemStyle: { color: "#e8a23d" } },
    ],
  });
}

function renderActivity(list) {
  const sorted = [...list].sort((a, b) => b.updates - a.updates).slice(0, 10);
  makeChart(activityChartEl.value, {
    tooltip: {},
    grid: { left: 8, right: 24, top: 8, bottom: 0, containLabel: true },
    xAxis: { type: "value", minInterval: 1 },
    yAxis: { type: "category", data: sorted.map((x) => x.name).reverse() },
    series: [{ type: "bar", data: sorted.map((x) => x.updates).reverse(), itemStyle: { color: "#1a6fb5" }, barMaxWidth: 18, label: { show: true, position: "right" } }],
  });
}

function renderHeat(matrix) {
  const cells = [];
  matrix.users.forEach((u) => {
    u.cells.forEach((c) => cells.push([matrix.dates.indexOf(c.date), matrix.users.indexOf(u), c.count]));
  });
  makeChart(heatChartEl.value, {
    tooltip: { formatter: (p) => `${matrix.users[p.value[1]].name} · ${matrix.dates[p.value[0]]}：${p.value[2]} 次更新` },
    grid: { left: 8, right: 16, top: 8, bottom: 40, containLabel: true },
    xAxis: { type: "category", data: matrix.dates.map((d) => d.slice(5)) },
    yAxis: { type: "category", data: matrix.users.map((u) => u.name) },
    visualMap: { min: 0, max: 4, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#f0f3f8", "#9cc3e8", "#1a6fb5"] } },
    series: [{ type: "heatmap", data: cells, label: { show: true, formatter: (p) => (p.value[2] ? p.value[2] : "") } }],
  });
}

/* ---------- 单个项目：任务+进度日志客户端聚合 ---------- */
function renderProjectScoped(tasks, logs) {
  const today = todayStr();
  const active = tasks.filter(isActive);
  const overdue = active.filter((t) => t.end_date < today);
  const stalled = tasks.filter((t) => t.risk_level === "stall");
  const avg = tasks.length ? Math.round(tasks.reduce((s, t) => s + t.progress, 0) / tasks.length) : 0;
  kpis.value = [
    { value: tasks.length, label: "任务总数", cls: "" },
    { value: avg + "%", label: "平均进度", cls: "" },
    { value: overdue.length, label: "已逾期", cls: "warn" },
    { value: stalled.length, label: "停滞中", cls: "danger" },
  ];
  barTitle.value = "负责人进度总览（本项目）";
  activityTitle.value = `成员更新次数（近 ${activityDays} 天）`;

  // 负责人维度：平均进度 / 逾期 / 停滞
  const byOwner = {};
  tasks.forEach((t) => {
    const key = t.assignee || "未指定";
    byOwner[key] = byOwner[key] || { sum: 0, n: 0, overdue: 0, stalled: 0 };
    byOwner[key].sum += t.progress;
    byOwner[key].n += 1;
    if (t.end_date < today && isActive(t)) byOwner[key].overdue += 1;
    if (t.risk_level === "stall") byOwner[key].stalled += 1;
  });
  const owners = Object.keys(byOwner);
  makeChart(deptChartEl.value, {
    tooltip: { trigger: "axis" },
    // 同上：显式固定图例到顶部，避免 'auto' 布局压住 0 基准线
    legend: { data: ["平均进度%", "逾期", "停滞"], top: 0, left: "center", itemGap: 18, textStyle: { fontSize: 12 } },
    grid: { left: 8, right: 16, top: 36, bottom: 4, containLabel: true },
    xAxis: {
      type: "category", data: owners,
      axisLabel: { interval: 0, rotate: 0, width: 56, overflow: "break", lineHeight: 15, fontSize: 11 },
    },
    yAxis: [{ type: "value", max: 100 }, { type: "value", minInterval: 1 }],
    series: [
      { name: "平均进度%", type: "bar", data: owners.map((k) => Math.round(byOwner[k].sum / byOwner[k].n)), itemStyle: { color: "#1a6fb5" }, barMaxWidth: 30 },
      { name: "逾期", type: "bar", yAxisIndex: 1, data: owners.map((k) => byOwner[k].overdue), itemStyle: { color: "#d9534f" }, barMaxWidth: 18 },
      { name: "停滞", type: "bar", yAxisIndex: 1, data: owners.map((k) => byOwner[k].stalled), itemStyle: { color: "#e8a23d" }, barMaxWidth: 18 },
    ],
  });

  // 状态分布
  const dist = {};
  tasks.forEach((t) => { dist[t.status || "not_started"] = (dist[t.status || "not_started"] || 0) + 1; });
  const pie = Object.entries(dist).map(([k, v]) => ({ name: STATUS_LABELS[k] || k, value: v }));
  makeChart(statusChartEl.value, {
    tooltip: { trigger: "item" },
    legend: { bottom: 0 },
    series: [{ type: "pie", radius: ["42%", "70%"], center: ["50%", "44%"], label: { formatter: "{b}\n{c}" }, data: pie.map((x) => ({ ...x, itemStyle: { color: PIE_COLORS[x.name] || "#8aa" } })) }],
  });

  // 趋势：每日平均进度（快照）
  const byDay = {};
  logs.forEach((l) => { (byDay[l.log_date] = byDay[l.log_date] || []).push(l.progress); });
  const days = Object.keys(byDay).sort();
  makeChart(trendChartEl.value, {
    tooltip: { trigger: "axis" },
    grid: { left: 8, right: 16, top: 16, bottom: 0, containLabel: true },
    xAxis: { type: "category", data: days.map((x) => x.slice(5)) },
    yAxis: { type: "value", max: 100 },
    series: [{ name: "实际平均", type: "line", data: days.map((d) => Math.round(byDay[d].reduce((s, v) => s + v, 0) / byDay[d].length)), smooth: true, itemStyle: { color: "#1a6fb5" }, areaStyle: { opacity: 0.12 } }],
  });

  // 成员更新次数 + 热力图（按说明记录的用户名；排除系统自动快照，只统计真人更新）
  const byUser = {};
  logs.forEach((l) => {
    if (!l.user_name) return;
    const key = l.user_name;
    byUser[key] = byUser[key] || {};
    byUser[key][l.log_date] = (byUser[key][l.log_date] || 0) + 1;
  });
  const names = Object.keys(byUser);
  makeChart(activityChartEl.value, {
    tooltip: {},
    grid: { left: 8, right: 24, top: 8, bottom: 0, containLabel: true },
    xAxis: { type: "value", minInterval: 1 },
    yAxis: { type: "category", data: [...names].sort((a, b) => (byUser[b] ? Object.values(byUser[b]).reduce((s, v) => s + v, 0) : 0) - (byUser[a] ? Object.values(byUser[a]).reduce((s, v) => s + v, 0) : 0)) },
    series: [{ type: "bar", data: [...names].sort((a, b) => Object.values(byUser[b] || {}).reduce((s, v) => s + v, 0) - Object.values(byUser[a] || {}).reduce((s, v) => s + v, 0)).map((k) => Object.values(byUser[k] || {}).reduce((s, v) => s + v, 0)), itemStyle: { color: "#1a6fb5" }, barMaxWidth: 18, label: { show: true, position: "right" } }],
  });

  const allDates = [...new Set(logs.map((l) => l.log_date))].sort();
  const cells = [];
  names.forEach((n, yi) => {
    allDates.forEach((d, xi) => {
      cells.push([xi, yi, (byUser[n] || {})[d] || 0]);
    });
  });
  makeChart(heatChartEl.value, {
    tooltip: { formatter: (p) => `${names[p.value[1]]} · ${allDates[p.value[0]]}：${p.value[2]} 次更新` },
    grid: { left: 8, right: 16, top: 8, bottom: 40, containLabel: true },
    xAxis: { type: "category", data: allDates.map((x) => x.slice(5)) },
    yAxis: { type: "category", data: names },
    visualMap: { min: 0, max: 4, calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#f0f3f8", "#9cc3e8", "#1a6fb5"] } },
    series: [{ type: "heatmap", data: cells, label: { show: true, formatter: (p) => (p.value[2] ? p.value[2] : "") } }],
  });

  // 清单
  overdueList.value = overdue.map((t) => ({
    id: t.id, name: t.name, project_name: "", assignee: t.assignee || "未指定",
    progress: t.progress, end_date: t.end_date, reasons: ["逾期未完成"],
  }));
  stallList.value = stalled.map((t) => ({
    id: t.id, name: t.name, project_name: "", assignee: t.assignee || "未指定",
    progress: t.progress, end_date: t.end_date, reasons: t.risk_reasons || [],
  }));
}

const overdueList = ref([]);
const stallList = ref([]);

async function refresh() {
  err.value = "";
  disposeCharts();
  try {
    projects.value = await api.listProjects();
    if (!projectId.value) {
      overview.value = await api.stats.overview();
      const activity = await api.stats.userActivity(activityDays);
      const matrix = await api.stats.activityMatrix(activityDays);
      const trend = await api.stats.progressTrend(0);
      await nextTick();
      renderGlobal();
      renderTrend(trend.trend);
      renderActivity(activity);
      renderHeat(matrix);
      overdueList.value = overview.value.overdue_list;
      stallList.value = overview.value.stalled_list;
    } else {
      const [tasks, logs] = await Promise.all([api.listTasks(projectId.value), api.listProgressLogs(projectId.value)]);
      await nextTick();
      renderProjectScoped(tasks, logs);
    }
  } catch (e) {
    err.value = e.message || "数据加载失败";
  }
}

function disposeCharts() {
  if (ro) {
    ro.disconnect();
    ro = null;
  }
  charts.forEach((c) => c.dispose());
  charts = [];
}

function logout() {
  api.logout().catch(() => {}).finally(() => {
    user.value = null;
  });
}

onMounted(async () => {
  try {
    user.value = await api.me();
    if (["admin", "supervisor"].includes(user.value.role)) {
      allowed.value = true;
      await refresh();
    } else {
      err.value = "驾驶舱仅对主管与管理员开放";
    }
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) {
      location.href = "/";
    } else {
      err.value = e.message || "加载失败";
    }
  }
});

function handleResize() {
  charts.forEach((c) => c.resize());
}
window.addEventListener("resize", handleResize);
onBeforeUnmount(() => {
  window.removeEventListener("resize", handleResize);
  disposeCharts();
});
</script>

<style scoped>
.page {
  max-width: 1280px;
  margin: 0 auto;
  padding: 18px 20px 48px;
  width: 100%;
}

.proj-pick {
  display: flex;
  align-items: center;
  gap: 6px;
  color: rgba(255, 255, 255, 0.8);
  font-size: 13px;
}

.proj-pick select {
  min-width: 180px;
}

.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.kpi {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
  text-align: center;
}

.kpi b {
  display: block;
  font-size: 26px;
  color: var(--primary);
}

.kpi.warn b {
  color: var(--warning);
}

.kpi.danger b {
  color: var(--danger);
}

.kpi span {
  color: var(--muted);
  font-size: 12px;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 14px;
}

.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
}

.card.wide {
  grid-column: 1 / -1;
}

.card-title {
  font-weight: 600;
  font-size: 13.5px;
  margin-bottom: 6px;
}

.card-title small {
  font-weight: 400;
  color: var(--muted);
  margin-left: 8px;
}

.card-title.danger {
  color: var(--danger);
}

.chart {
  height: 260px;
}

.chart.tall {
  height: 300px;
}

.mini-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 260px;
  overflow: auto;
}

.mini-list li {
  padding: 7px 4px;
  border-bottom: 1px solid #f0f3f8;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
}

.mini-list small {
  color: var(--muted);
  font-size: 12px;
}

.mini-list .none {
  color: var(--muted);
  text-align: center;
}

.lists {
  grid-template-columns: 1fr 1fr;
}

.state {
  text-align: center;
  color: var(--muted);
  padding: 60px 0;
}

.state.plain {
  padding: 120px 0;
}

@media (max-width: 860px) {
  .grid,
  .lists {
    grid-template-columns: 1fr;
  }
}
</style>
