import { createApp } from "vue";
import App from "./App.vue";
import AdminApp from "./AdminApp.vue";
import DashboardApp from "./DashboardApp.vue";
import "./style.css";

// 轻量路径路由：/ 主应用，/admin 管理后台，/dashboard 驾驶舱
const path = window.location.pathname;
const isAdminPage = path.startsWith("/admin");
const isDashboardPage = path.startsWith("/dashboard");
createApp(isAdminPage ? AdminApp : isDashboardPage ? DashboardApp : App).mount("#app");
