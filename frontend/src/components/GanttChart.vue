<template>
  <div ref="wrapEl" class="gantt-container"></div>
</template>

<script setup>
/**
 * frappe-gantt 封装组件（纯展示模式）：
 * - 甘特图不提供任何拖拽调整（防误触），所有修改请使用左侧任务表格
 * - 点击任务条可查看信息弹窗
 * - 重建时保存并恢复水平滚动位置（更新数据不跳回最左侧）
 * - "回到今天"使用日期列定位（不依赖库内部不可靠的定位逻辑）
 */
import { ref, watch, onMounted, onBeforeUnmount } from "vue";
import Gantt from "frappe-gantt";
import "../assets/frappe-gantt.css";

const props = defineProps({
  tasks: { type: Array, required: true },
  viewMode: { type: String, default: "Month" },
  language: { type: String, default: "zh" },
});

const emit = defineEmits(["task-click", "view-change"]);

const wrapEl = ref(null);
let gantt = null;

function toYMD(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function ym(d) {
  return `${d.getFullYear()}年${d.getMonth() + 1}月`;
}

/** 中文日期表头（覆盖库默认的英式区间）：
 *  月视图：上年份 / 下"10月"；日视图：上"2026年10月" / 下"15日"；
 *  周视图：上"2026年10月" / 下"10/12"；年视图：下"2026年"。
 *  所有视图 date_format 统一为完整日期，使今日标线与列定位在全视图可用。 */
const zhViewModes = [
  {
    name: "Month",
    padding: "2m",
    step: "1m",
    column_width: 90,
    date_format: "YYYY-MM-DD",
    upper_text: (d) => (d.getMonth() === 0 ? `${d.getFullYear()}年` : ""),
    lower_text: (d) => `${d.getMonth() + 1}月`,
    upper_text_frequency: 12,
  },
  {
    name: "Day",
    padding: "7d",
    step: "1d",
    column_width: 45,
    date_format: "YYYY-MM-DD",
    upper_text: (d) => (d.getDate() === 1 ? ym(d) : ""),
    lower_text: (d) => `${d.getDate()}日`,
    upper_text_frequency: 30,
  },
  {
    name: "Week",
    padding: "1m",
    step: "7d",
    column_width: 110,
    date_format: "YYYY-MM-DD",
    upper_text: (d, ld) => (!ld || ld.getMonth() !== d.getMonth() ? ym(d) : ""),
    lower_text: (d) =>
      `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}`,
    upper_text_frequency: 4,
  },
  {
    name: "Year",
    padding: "2y",
    step: "1y",
    column_width: 140,
    date_format: "YYYY-MM-DD",
    upper_text: () => "",
    lower_text: (d) => `${d.getFullYear()}年`,
    upper_text_frequency: 1,
  },
];

/** 计算今天在图表内容区的 x 坐标：优先逐日回退匹配日期列（日/周视图必有），
 *  月/年视图列稀疏时退化为月首/年首轮询；按列内天数比例折算精确位置。 */
function findTodayX() {
  if (!gantt || !gantt.$container) return null;
  const container = gantt.$container;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const modeName = (gantt.config.view_mode && gantt.config.view_mode.name) || "Day";
  const columnWidth = gantt.config.column_width || 45;

  const candidates = [];
  if (modeName !== "Year") {
    const d = new Date(today);
    for (let i = 0; i < 62; i++) {
      candidates.push(new Date(d));
      d.setDate(d.getDate() - 1);
    }
  }
  if (modeName === "Month" || modeName === "Year") {
    const m = new Date(today.getFullYear(), today.getMonth(), 1);
    for (let i = 0; i < 14; i++) {
      candidates.push(new Date(m));
      m.setMonth(m.getMonth() - 1);
    }
  }
  if (modeName === "Year") {
    const y = new Date(today.getFullYear(), 0, 1);
    for (let i = 0; i < 6; i++) {
      candidates.push(new Date(y));
      y.setFullYear(y.getFullYear() - 1);
    }
  }

  for (const colStart of candidates) {
    const el = container.querySelector(`.date_${toYMD(colStart)}`);
    if (!el) continue;
    const left = parseFloat(el.style.left) || 0;
    let spanDays = 1;
    if (modeName === "Month") {
      spanDays = Math.round((new Date(colStart.getFullYear(), colStart.getMonth() + 1, 1) - colStart) / 86400000);
    } else if (modeName === "Week") {
      spanDays = 7;
    } else if (modeName === "Year") {
      spanDays = colStart.getFullYear() % 4 === 0 ? 366 : 365;
    }
    const diffDays = Math.max(0, Math.round((today - colStart) / 86400000));
    return left + (Math.min(diffDays, spanDays) / spanDays) * columnWidth;
  }
  return null;
}

/** 库缺陷兜底：库在滚动监听与定位逻辑中执行
 *  upperTexts.find(textContent === upper_text(当前日期))，稀疏表头下可能返回 undefined
 *  → undefined.clientWidth 崩溃。给实例的 upperTexts 追加一个"哨兵"元素，
 *  保证任何 find 都有结果（哨兵宽度为 0、classList 为空操作，不影响视觉）。 */
function installUpperTextsGuard(g) {
  const SENTINEL = {
    textContent: "",
    clientWidth: 0,
    clientLeft: 0,
    offsetLeft: 0,
    offsetWidth: 0,
    classList: { add() {}, remove() {} },
  };
  try {
    Object.defineProperty(g, "upperTexts", {
      configurable: true,
      get() {
        return (this.__ogUpperTexts || []).concat([SENTINEL]);
      },
      set(v) {
        this.__ogUpperTexts = v;
      },
    });
  } catch {
    /* 老环境无法 defineProperty 时忽略（后果仅是滚动时报错，不影响数据） */
  }
}

/** 自绘"今天"标线（库内置标线在月/周视图因列类名缺失而不渲染） */
function updateTodayMarker() {
  if (!gantt || !gantt.$container) return;
  gantt.$container.querySelectorAll(".og-today-marker, .og-today-label").forEach((e) => e.remove());
  const x = findTodayX();
  if (x == null) return;
  const line = document.createElement("div");
  line.className = "og-today-marker";
  line.style.left = x + "px";
  const label = document.createElement("div");
  label.className = "og-today-label";
  label.style.left = x + "px";
  label.textContent = "今天";
  gantt.$container.appendChild(line);
  gantt.$container.appendChild(label);
}

function scrollToToday({ instant = false } = {}) {
  if (!gantt || !gantt.$container) return;
  const x = findTodayX();
  if (x == null) return;
  // 首次定位用瞬时滚动（避免数据二次加载触发重建时打断平滑动画）
  gantt.$container.scrollTo({
    left: Math.max(0, x - gantt.$container.clientWidth / 3),
    behavior: instant ? "auto" : "smooth",
  });
}

function build(tasks, viewMode, { isFirstBuild = false } = {}) {
  if (!wrapEl.value) return;
  // 关键修复：重建会销毁滚动容器，先保存当前位置
  // 关键修复（库缺陷）：set_scroll_position 内部会执行
  // upperTexts.find(textContent === current_upper)，而自定义稀疏表头（upper_text 对
  // 非起始列返回 ""）会让 current_upper 为空串 → find 返回 undefined →
  // undefined.clientWidth TypeError。该异常在【构造函数内部】与 change_view_mode 中
  // 冒出（render 末尾必然调用 set_scroll_position），导致图表渲染中断、
  // 日/周/月/年切换无响应、今天标线丢失。
  // 安全补丁：构造前替换【原型方法】，只负责滚动定位，跳过库内部的"当前列文本"重算
  // （今天标线与定位由本组件的 findTodayX/scrollToToday/updateTodayMarker 接管）。
  if (!Gantt.prototype.__ogScrollPatched) {
    Gantt.prototype.__ogScrollPatched = true;
    Gantt.prototype.set_scroll_position = function (date) {
      if (date === "today") {
        scrollToToday({ instant: true });
      }
      // null / "start" / 其他：不自动滚动，由调用方决定定位
    };
  }
  const prevScroll = gantt && gantt.$container ? gantt.$container.scrollLeft : null;
  const wasBuilt = gantt != null;
  wrapEl.value.innerHTML = "";
  const data = tasks.map((t) => ({
    id: String(t.id),
    name: t.name,
    start: t.start_date,
    end: t.end_date,
    progress: t.progress,
    dependencies: t.dependencies,
    custom_class:
      t.status === "blocked"
        ? "og-blocked"
        : t.status === "paused"
          ? "og-paused"
          : t.status === "cancelled"
            ? "og-cancelled"
            : t.progress >= 100
              ? "og-done"
              : "",
  }));
  gantt = new Gantt(wrapEl.value, data, {
    language: props.language,
    view_mode: viewMode,
    view_modes: zhViewModes, // 自定义中文日期表头（首项为默认视图：月）
    bar_height: 28,
    today_button: false, // 用工具栏自研"回到今天"按钮替代内置按钮
    scroll_to: null, // 定位一律由 scrollToToday 完成
    // 关键修复：关闭无限扩展。其 mousewheel 处理器会在滚动中整图重建并补偿
    // scrollLeft，滚轮一格触发一次重排——正是"滚轮乱跳"的根源。
    // 关闭后图表范围由任务日期 + 各视图 padding 决定，滚轮走原生平滑滚动。
    infinite_padding: false,
    // 纯展示模式：禁用拖拽改期与进度拖动（防止误触），编辑统一走任务表格
    readonly_dates: true,
    readonly_progress: true,
    on_click: (task) => {
      emit("task-click", Number(task.id));
    },
    on_view_change: (mode) => {
      if (mode && mode.name) emit("view-change", mode.name);
    },
  });
  installUpperTextsGuard(gantt);
  // 恢复重建前的水平滚动位置；每次渲染后更新"今天"标线
  if (prevScroll != null && wasBuilt) {
    gantt.$container.scrollLeft = prevScroll;
  } else if (isFirstBuild) {
    scrollToToday({ instant: true });
  }
  updateTodayMarker();
}

onMounted(() => {
  build(props.tasks, props.viewMode, { isFirstBuild: true });
});

watch(
  () => props.tasks,
  (tasks) => {
    build(tasks, props.viewMode);
  }
);

watch(
  () => props.viewMode,
  (mode) => {
    if (!gantt || !gantt.$container) return;
    try {
      // 切换视图时保持"视口中心的日期"不变（不同视图列宽不同，纯像素保持会错位）
      const c = gantt.$container;
      const centerPx = c.scrollLeft + c.clientWidth / 2;
      const colIdx = Math.min(
        Math.floor(centerPx / (gantt.config.column_width || 45)),
        gantt.dates.length - 1
      );
      const centerDate = gantt.dates[Math.max(0, colIdx)];
      gantt.change_view_mode(mode, false);
      const dates = gantt.dates;
      let idx = 0;
      for (let i = 0; i < dates.length; i++) {
        if (dates[i] <= centerDate) idx = i;
        else break;
      }
      const next = dates[idx + 1] || new Date(dates[idx].getTime() + 7 * 86400000);
      const span = Math.max(1, next - dates[idx]);
      const frac = Math.max(0, Math.min(1, (centerDate - dates[idx]) / span));
      c.scrollLeft =
        idx * gantt.config.column_width + frac * gantt.config.column_width - c.clientWidth / 2;
    } catch (e) {
      // 兜底：保持中心日期失败时直接切换视图
      gantt.change_view_mode(mode, false);
    } finally {
      updateTodayMarker();
    }
  }
);

onBeforeUnmount(() => {
  gantt = null;
  if (wrapEl.value) wrapEl.value.innerHTML = "";
});

defineExpose({
  scrollToToday,
  reRender: () => build(props.tasks, props.viewMode),
});
</script>

<style scoped>
.gantt-container {
  width: 100%;
  background: var(--panel);
  border-radius: var(--radius);
  padding: 0;
}

.gantt-container :deep(.bar-wrapper.og-done .bar) {
  fill: #dbe3ec;
}
.gantt-container :deep(.bar-wrapper.og-done .bar-progress) {
  fill: #a9b8c9;
}
/* 状态着色：阻塞=红、暂停=灰黄、取消=浅红斜纹由边框表达 */
.gantt-container :deep(.bar-wrapper.og-blocked .bar) {
  fill: #f6c6c2;
}
.gantt-container :deep(.bar-wrapper.og-blocked .bar-progress) {
  fill: #d9534f;
}
.gantt-container :deep(.bar-wrapper.og-paused .bar) {
  fill: #efe6c8;
}
.gantt-container :deep(.bar-wrapper.og-paused .bar-progress) {
  fill: #c9a13d;
}
.gantt-container :deep(.bar-wrapper.og-cancelled .bar) {
  fill: #e7e7e7;
}
.gantt-container :deep(.bar-wrapper.og-cancelled .bar-progress) {
  fill: #bdbdbd;
}
/* 纯展示模式：隐藏拖拽把手与库内置今日线（统一使用自绘标线），进一步防误触 */
.gantt-container :deep(.bar-wrapper .handle) {
  display: none;
}
.gantt-container :deep(.current-highlight),
.gantt-container :deep(.current-ball-highlight) {
  display: none;
}

/* 自绘"今天"标线：贯穿图表高度，顶部带"今天"标签 */
.gantt-container :deep(.og-today-marker) {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #f59e0b;
  z-index: 5;
  pointer-events: none;
}

.gantt-container :deep(.og-today-label) {
  position: absolute;
  top: 2px;
  transform: translateX(-50%);
  background: #f59e0b;
  color: #fff;
  font-size: 11px;
  line-height: 16px;
  padding: 0 5px;
  border-radius: 3px;
  z-index: 6;
  pointer-events: none;
  white-space: nowrap;
}
</style>
