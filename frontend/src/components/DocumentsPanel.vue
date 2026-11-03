<template>
  <section class="docs-panel">
    <header
      class="docs-head"
      role="button"
      :aria-expanded="expanded"
      :title="expanded ? '点击收起「项目进度文档」' : '点击展开「项目进度文档」'"
      @click="expanded = !expanded"
    >
      <span class="docs-caret" :class="{ open: expanded }" aria-hidden="true">▶</span>
      <strong>项目进度文档</strong>
      <span class="docs-sub">周报、验收单等项目资料归档 · 点击标题折叠/展开</span>
      <span class="docs-count">{{ documents.length }} 份</span>
    </header>

    <div v-if="expanded" class="docs-body">
      <div v-if="canEdit" class="docs-upload">
        <label class="upload-btn">
          <input type="file" :disabled="uploading" @change="onFileChange" hidden />
          {{ uploading ? "上传中…" : "＋ 上传文档" }}
        </label>
        <input
          v-model="note"
          class="upload-note"
          placeholder="备注（选填，如：第 3 周进度周报）"
          maxlength="200"
        />
      </div>
      <p v-else class="docs-tip">仅项目负责人、本部门主管与管理员可上传</p>

      <p v-if="error" class="docs-error">{{ error }}</p>

      <table v-if="documents.length" class="docs-table">
        <thead>
          <tr>
            <th>文件名</th>
            <th style="width: 90px">大小</th>
            <th style="width: 150px">上传人</th>
            <th style="width: 150px">上传时间</th>
            <th>备注</th>
            <th style="width: 110px"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in documents" :key="d.id">
            <td class="doc-name" :title="d.original_name">{{ d.original_name }}</td>
            <td>{{ formatSize(d.size) }}</td>
            <td>{{ d.uploader_name }}</td>
            <td>{{ formatTime(d.uploaded_at) }}</td>
            <td>{{ d.note || "—" }}</td>
            <td class="doc-ops">
              <a :href="`/api/documents/${d.id}/download`" target="_blank" rel="noopener">
                <button class="mini">下载</button>
              </a>
              <button
                v-if="canDelete(d)"
                class="mini danger"
                @click="removeDoc(d)"
              >删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="docs-tip">暂无文档</p>
    </div>
  </section>
</template>

<script setup>
import { ref, watch } from "vue";
import { api } from "../api/client.js";

const props = defineProps({
  projectId: { type: Number, default: null },
  canEdit: { type: Boolean, default: false },
  currentUser: { type: Object, default: null },
});

const documents = ref([]);
const expanded = ref(false);
const uploading = ref(false);
const note = ref("");
const error = ref("");

async function load() {
  if (!props.projectId) {
    documents.value = [];
    return;
  }
  try {
    documents.value = await api.listDocuments(props.projectId);
  } catch (e) {
    error.value = e.message || "文档列表加载失败";
  }
}

watch(() => props.projectId, load, { immediate: true });

function canDelete(d) {
  if (!props.currentUser) return false;
  return props.currentUser.role === "admin" || d.uploader_name === (props.currentUser.display_name || props.currentUser.username);
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

async function onFileChange(e) {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (!file || !props.projectId) return;
  uploading.value = true;
  error.value = "";
  try {
    await api.uploadDocument(props.projectId, file, note.value.trim());
    note.value = "";
    await load();
  } catch (err) {
    error.value = err.message || "上传失败";
  } finally {
    uploading.value = false;
  }
}

async function removeDoc(d) {
  if (!window.confirm(`确定删除文档「${d.original_name}」？`)) return;
  try {
    await api.deleteDocument(d.id);
    await load();
  } catch (err) {
    error.value = err.message || "删除失败";
  }
}
</script>

<style scoped>
.docs-panel {
  margin-bottom: 16px;
}

/* 蓝条签名标题（与 og-panel-title 一致），点击折叠/展开 */
.docs-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border-left: 4px solid var(--primary);
  border-radius: 0 8px 8px 0;
  margin: 18px 0 10px;
  font-size: 15px;
  line-height: 1.3;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s ease;
}

.docs-head:hover {
  background: var(--primary-weak, rgba(47, 107, 255, 0.08));
}

.docs-head strong {
  font-weight: 600;
}

/* 圆形旋转箭头徽标（与任务清单等折叠区一致） */
.docs-caret {
  flex: none;
  width: 19px;
  height: 19px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #e8ebf0;
  color: var(--muted);
  font-size: 9px;
  line-height: 1;
  transition: transform 0.18s ease, background 0.15s ease, color 0.15s ease;
}

.docs-caret.open {
  transform: rotate(90deg);
  background: var(--primary);
  color: #fff;
}

.docs-head:hover .docs-caret {
  background: var(--primary);
  color: #fff;
}

.docs-sub {
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.docs-count {
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
}

.docs-body {
  padding: 12px 14px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--panel);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.docs-upload {
  display: flex;
  gap: 8px;
}

.upload-btn {
  display: inline-block;
  padding: 6px 14px;
  background: var(--primary);
  color: #fff;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
}

.upload-btn:hover {
  background: var(--primary-dark);
}

.upload-note {
  flex: 1;
}

.docs-error {
  color: var(--danger);
  font-size: 13px;
  margin: 0;
}

.docs-tip {
  color: var(--muted);
  font-size: 12px;
  margin: 0;
}

.docs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.docs-table th {
  text-align: left;
  padding: 6px;
  background: #f7f9fc;
  border-bottom: 1px solid var(--border);
  font-weight: 500;
}

.docs-table td {
  padding: 6px;
  border-bottom: 1px solid #eef2f7;
}

.doc-name {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-ops {
  display: flex;
  gap: 6px;
}

button.mini {
  padding: 2px 10px;
  font-size: 12px;
}

button.mini.danger:hover {
  border-color: var(--danger);
  color: var(--danger);
}

a {
  text-decoration: none;
}
</style>
