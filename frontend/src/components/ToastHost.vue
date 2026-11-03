<template>
  <div
    v-if="error"
    class="toast"
    :class="{ offline: offline }"
    @click="error = ''"
    role="alert"
  >
    <span>{{ error }}</span>
    <small v-if="offline">点击关闭 · 离线状态下编辑将不会保存</small>
  </div>
  <div v-if="info" class="toast info" @click="info = ''" role="status">
    <span>{{ info }}</span>
  </div>
</template>

<script setup>
import { ref } from "vue";

const error = ref("");
const info = ref("");
const offline = ref(!navigator.onLine);

window.addEventListener("offline", () => {
  offline.value = true;
  showError("网络连接已断开");
});
window.addEventListener("online", () => {
  offline.value = false;
});

function showError(message) {
  error.value = message;
  if (message && !message.includes("断开")) {
    setTimeout(() => {
      if (error.value === message) error.value = "";
    }, 4000);
  }
}

/** 轻量信息提示（自动保存等中性反馈）：更淡的样式、更短停留 */
function showInfo(message) {
  info.value = message;
  setTimeout(() => {
    if (info.value === message) info.value = "";
  }, 3200);
}

defineExpose({ showError, showInfo });
</script>

<style scoped>
.toast {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  background: #7f1d1d;
  color: #fff;
  padding: 10px 18px;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  z-index: 1000;
  cursor: pointer;
  text-align: center;
}
.toast small {
  display: block;
  opacity: 0.8;
  margin-top: 2px;
}
.toast.offline {
  background: #92400e;
}
.toast.info {
  top: 66px;
  background: rgba(30, 58, 95, 0.92);
  font-size: 13px;
  padding: 8px 16px;
  cursor: default;
  backdrop-filter: blur(4px);
}
</style>
