import { createApp } from "vue";
import App from "./App.vue";
import AdminApp from "./AdminApp.vue";
import DashboardApp from "./DashboardApp.vue";
import "./style.css";

// 轻量路径路由：/ 主应用，/admin 管理后台，/dashboard 驾驶舱
const path = window.location.pathname;
const isAdminPage = path.startsWith("/admin");
const isDashboardPage = path.startsWith("/dashboard");
// 构建版本标识：报错排查时先看 console 里的构建时间与页面是否匹配（旧标签页/缓存会显示旧时间）
console.log(
  `[OpenGantt] frontend build ${__BUILD_TIME__} — 若与最近部署时间不符，请强制刷新（Ctrl+Shift+R）`
);
createApp(isAdminPage ? AdminApp : isDashboardPage ? DashboardApp : App).mount("#app");
