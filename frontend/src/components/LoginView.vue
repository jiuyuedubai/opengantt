<template>
  <div class="login-mask">
    <form class="login-card" @submit.prevent="submit">
      <div class="login-brand">
        <img src="/favicon.svg" alt="logo" width="44" height="44" />
        <h1>OpenGantt 项目进度管理</h1>
        <p>请使用管理员下发的账号登录</p>
      </div>
      <label>
        <span>用户名</span>
        <input v-model="username" autocomplete="username" placeholder="员工账号" />
      </label>
      <label>
        <span>密码</span>
        <input
          v-model="password"
          type="password"
          autocomplete="current-password"
          placeholder="密码"
        />
      </label>
      <p v-if="error" class="login-error">{{ error }}</p>
      <button class="primary login-btn" type="submit" :disabled="busy || !username || !password">
        {{ busy ? "登录中…" : "登 录" }}
      </button>
    </form>
  </div>
</template>

<script setup>
import { ref } from "vue";

const emit = defineEmits(["logged-in"]);

const username = ref("");
const password = ref("");
const error = ref("");
const busy = ref(false);

async function submit() {
  busy.value = true;
  error.value = "";
  try {
    const { api } = await import("../api/client.js");
    const user = await api.login(username.value.trim(), password.value);
    emit("logged-in", user);
  } catch (e) {
    error.value = e.message || "登录失败";
  } finally {
    busy.value = false;
  }
}
</script>

<style scoped>
.login-mask {
  position: fixed;
  inset: 0;
  background: linear-gradient(180deg, #eef3fb 0%, #f5f7fa 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.login-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 32px;
  width: min(380px, calc(100vw - 40px));
  box-shadow: 0 16px 40px rgba(30, 64, 175, 0.12);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.login-brand {
  text-align: center;
  margin-bottom: 6px;
}

.login-brand h1 {
  font-size: 17px;
  margin: 10px 0 4px;
}

.login-brand p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.login-card label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 13px;
  color: var(--muted);
}

.login-card input {
  padding: 9px 12px;
  font-size: 14px;
}

.login-error {
  color: var(--danger);
  font-size: 13px;
  margin: 0;
}

.login-btn {
  padding: 10px;
  font-size: 14px;
}
</style>
