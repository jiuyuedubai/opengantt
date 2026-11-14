<template>
  <!-- 登录门禁 -->
  <LoginView v-if="!currentUser" @logged-in="onLoggedIn" />

  <template v-else>
    <header class="og-navbar">
      <a class="brand" href="/">
        <img src="/favicon.svg" alt="logo" width="26" height="26" />
        <div>
          <h1>OpenGantt 项目进度管理</h1>
          <p class="sub">免费开源 · 可私有化部署</p>
        </div>
      </a>
      <div class="nav-actions">
        <div class="search-box">
          <input
            ref="searchInputRef"
            v-model="searchQ"
            placeholder="搜索任务 / 项目 / 人员（Ctrl+K）"
            @input="onSearchInput"
            @keydown.escape="searchResults = null"
          />
          <div v-if="searchResults" class="search-results">
            <template v-if="searchResults.tasks.length">
              <div class="sr-group">任务</div>
              <a
                v-for="t in searchResults.tasks"
                :key="'t' + t.id"
                class="sr-item"
                :href="`/dept/${t.department_id ?? 0}`"
                @click="gotoProject(t.project_id)"
              >
                <span class="sr-tag">#{{ t.id }}</span> {{ t.name }}
                <small>{{ t.project_name }} · {{ t.assignee || "未指定" }} · {{ t.progress }}%</small>
              </a>
            </template>
            <template v-if="searchResults.projects.length">
              <div class="sr-group">项目</div>
              <a
                v-for="p in searchResults.projects"
                :key="'p' + p.id"
                class="sr-item"
                :href="`/dept/${p.department_id ?? 0}`"
                @click="gotoProject(p.id)"
              >
                {{ p.name }} <small>{{ p.task_count }} 项任务</small>
              </a>
            </template>
            <template v-if="searchResults.users.length">
              <div class="sr-group">人员</div>
              <div v-for="u in searchResults.users" :key="'u' + u.id" class="sr-item static">
                {{ u.name }} <small>@{{ u.username }}</small>
              </div>
            </template>
            <div v-if="!searchResults.tasks.length && !searchResults.projects.length && !searchResults.users.length" class="sr-item static">
              无匹配结果
            </div>
          </div>
        </div>
        <template v-if="view === 'dept'">
          <button class="primary" @click="openNewProject">＋ 新建项目</button>
        <template v-if="currentProject">
          <button v-if="currentProject.can_edit" class="primary" @click="showNewTask = true">＋ 新增任务</button>
          <button @click="exportCsv" title="导出当前项目任务清单">导出 CSV</button>
          <button v-if="canMigrateProject" title="将项目迁移到其他部门（任务/负责人/进度/文档全部跟随）" @click="openMigrate">📦 迁移部门</button>
          <button v-if="canDeleteProject" @click="removeProject">删除项目</button>
        </template>
        <button @click="openReport">📋 我的工作日志</button>
        <a v-if="canSeeDashboard" class="og-nav-link" href="/dashboard">📊 驾驶舱</a>
        </template>
        <button :class="{ primary: view === 'docs' }" title="按 部门 → 成员 → 文档 层级浏览进度文档" @click="toggleDocsView">📄 进度文档</button>
        <span class="og-user-chip">
          <b>{{ currentUser.display_name }}</b>
          <select
            class="ws-select"
            :value="currentUser.work_status"
            title="工作状态：每日日志统计仅计入「在岗」成员"
            @change="setMyStatus($event.target.value)"
          >
            <option value="working">🟢 在岗</option>
            <option value="leave">🟠 请假</option>
            <option value="vacation">🔵 休假</option>
            <option value="trip">🟣 出差</option>
          </select>
          <input
            v-if="currentUser.work_status !== 'working'"
            v-model="wsUntilDraft"
            type="datetime-local"
            class="ws-until-input"
            title="预计结束时间（可选）：到时自动恢复为「在岗」"
            @change="saveWsUntil"
          />
          <button
            v-if="currentUser.work_status !== 'working' && wsUntilDraft"
            class="chip-link"
            title="保存预计结束时间，到时自动恢复在岗"
            @click="saveWsUntil"
          >⏰ 设定恢复</button>
          <i v-if="currentUser.work_status_until" class="ws-until-tip">
            🕐 {{ fmtWsUntil(currentUser.work_status_until) }} 自动恢复
          </i>
          <i>{{ roleLabel }}{{ currentUser.department_name ? " · " + currentUser.department_name : "" }}</i>
      <button class="chip-link" @click="showChangePw = true">修改密码</button>
      <a v-if="currentUser.role === 'admin'" href="/admin" class="og-nav-link" target="_blank" rel="noopener">管理后台</a>
          <button @click="doLogout">退出</button>
        </span>
      </div>
    </header>

    <div class="page">
      <!-- ============ 主页：部门导航 ============ -->
      <template v-if="view === 'home'">
        <section class="hero">
          <div class="hero-pattern" aria-hidden="true"></div>
          <div class="hero-main">
            <h2>您好，{{ currentUser.display_name }} 👋</h2>
            <p>选择一个部门进入，查看项目排期、进度说明与每日工作日志。</p>
            <div class="hero-stats">
              <div class="stat">
                <b>{{ totalProjects }}</b>
                <span>项目总数</span>
              </div>
              <div class="stat">
                <b>{{ totalTasks }}</b>
                <span>任务总数</span>
              </div>
              <div class="stat">
                <b>{{ departments.length }}</b>
                <span>参与部门</span>
              </div>
              <div class="stat">
                <b>{{ totalMembers }}</b>
                <span>团队成员</span>
              </div>
            </div>
          </div>
        </section>

        <div class="og-panel-title">
          按部门进入
          <small>点击卡片查看该部门的项目与排期</small>
        </div>
        <div class="dept-grid">
          <a v-for="(d, i) in departments" :key="d.id" class="dept-card" :href="`/dept/${d.id}`">
            <div class="dept-top">
              <span class="dept-icon" :class="`accent-${i % 6}`">{{ deptIcon(d.name) }}</span>
              <div class="dept-title">
                <b class="dept-name">{{ d.name }}</b>
                <span class="dept-members">{{ d.user_count }} 名成员</span>
              </div>
              <span class="dept-arrow">→</span>
            </div>
            <p class="dept-desc">{{ d.description || "—" }}</p>
            <div class="dept-stats">
              <span class="pill"><b>{{ d.project_count }}</b> 项目</span>
              <span class="pill"><b>{{ d.task_count }}</b> 任务</span>
            </div>
          </a>
          <a v-if="uncategorizedCount" class="dept-card" href="/dept/0">
            <div class="dept-top">
              <span class="dept-icon accent-6">🗂</span>
              <div class="dept-title">
                <b class="dept-name">未分部门项目</b>
                <span class="dept-members">待归类</span>
              </div>
              <span class="dept-arrow">→</span>
            </div>
            <p class="dept-desc">尚未归属任何部门的项目</p>
            <div class="dept-stats">
              <span class="pill"><b>{{ uncategorizedCount }}</b> 项目</span>
            </div>
          </a>
        </div>
        <p v-if="!departments.length && !uncategorizedCount" class="state">暂无部门数据，请联系管理员。</p>
      </template>

    <!-- ============ 进度文档中心：部门 → 成员 → 文档 ============ -->
    <template v-if="view === 'docs'">
      <nav class="crumb"><a href="/">主页</a><span>/</span><b>项目进度文档</b></nav>

      <div class="og-panel-title docs-title">
        <b>项目进度文档</b>
        <small>按「部门 → 成员 → 文档」三级浏览，点击行展开/收起；上传时文档归属于所选项目</small>
        <button class="mini" style="margin-left: auto" @click="openDocAccess">🔐 跨部门查询权限</button>
      </div>

      <!-- 工具条：筛选 / 批量操作（独立面板，与上传区、文档树并列） -->
      <section class="panel doc-toolbar">
        <div class="doc-toolbar-group">
          <span class="doc-toolbar-label">📅 日期筛选</span>
          <input type="date" v-model="docDateFilter" title="只显示该日期上传的文档" />
          <button v-if="docDateFilter" class="mini" @click="docDateFilter = ''">清除</button>
          <small v-if="docDateFilter" class="muted">
            命中 {{ docFilterCount }} 份 · {{ filteredDocTree.length }} 个部门
          </small>
          <small v-else class="muted">未筛选（显示全部）</small>
        </div>
        <div class="doc-toolbar-divider"></div>
        <div class="doc-toolbar-group" v-if="docDeletableCount">
          <span class="doc-toolbar-label">🗑 批量删除</span>
          <label
            class="muted"
            style="display: inline-flex; align-items: center; gap: 4px; cursor: pointer"
            :title="docDateFilter ? '全选当前筛选结果中的可删除文档' : '请先用「日期筛选」缩小范围，再全选删除'"
          >
            <input
              type="checkbox"
              :checked="allVisibleSelected"
              :disabled="!docDateFilter"
              @change="toggleSelectAllVisible($event.target.checked)"
            />
            全选可删（{{ docDeletableCount }}）
          </label>
          <button
            class="mini danger"
            :disabled="!selectedDocIds.size"
            title="删除勾选的文档"
            @click="deleteSelectedDocs"
          >删除所选（{{ selectedDocIds.size }}）</button>
          <small v-if="!docDateFilter" class="muted">全选需先按日期筛选，防止误删全部文档</small>
        </div>
      </section>

      <!-- 跨部门查询权限：我的授权与申请 -->
      <section v-if="showDocAccess" class="panel" style="border: 1px solid var(--border); border-radius: 10px; padding: 12px">
        <div class="report-controls" v-if="docAccessRows.some((r) => r.status === 'approved' && !r.expired)">
          <p class="report-hint" style="margin: 0">
            🔓 已生效授权：<b>{{ docAccessRows.filter((r) => r.status === "approved" && !r.expired).map((r) => r.department_name + "（至 " + r.expires_at.slice(0, 16).replace("T", " ") + "）").join("、") }}</b>
          </p>
        </div>
        <div class="report-controls">
          <select v-model.number="daReqDept">
            <option :value="null" disabled>申请查询哪个部门的文档…</option>
            <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
          <label>期望有效期至 <input type="datetime-local" v-model="daReqUntil" /></label>
          <input v-model="daReqNote" placeholder="申请说明（选填，如：项目对接需要）" maxlength="200" />
          <button class="primary" :disabled="daReqBusy || !daReqDept || !daReqUntil" @click="submitDocAccess">
            {{ daReqBusy ? "提交中…" : "提交申请" }}
          </button>
        </div>
        <table class="data-table" v-if="docAccessRows.length">
          <thead><tr><th>目标部门</th><th>状态</th><th>有效期至</th><th>说明</th></tr></thead>
          <tbody>
            <tr v-for="g in docAccessRows" :key="g.id">
              <td>{{ g.department_name }}</td>
              <td>{{ g.status === "approved" && g.expired ? "已过期" : g.status_label }}</td>
              <td class="mono">{{ g.expires_at }}</td>
              <td>{{ g.note || "—" }}</td>
            </tr>
          </tbody>
        </table>
        <p class="report-hint" v-else>尚无申请记录。提交后由管理员审批，批准且在有效期内即可在下方浏览该部门的文档。</p>
      </section>

      <section class="panel doc-upload">
        <select v-model.number="docUpload.project_id" title="上传到哪个项目（文档归属该项目）">
          <option :value="null" disabled>请选择项目…</option>
          <option v-for="p in editableProjects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <input ref="docFileRef" type="file" multiple title="可多选文件；zip 压缩包将自动解压为独立文档" @change="docFilesPicked" />
        <input
          ref="docFolderRef"
          type="file"
          webkitdirectory
          title="选择整个文件夹（保留内部目录结构）"
          @change="docFilesPicked"
          style="display: none"
        />
        <button class="mini" @click="docFolderRef?.click()">📁 选择文件夹</button>
        <input v-model="docUpload.note" placeholder="备注（选填）" maxlength="200" />
        <button class="primary" :disabled="docBusy || !docUpload.project_id || !docFiles.length" @click="uploadDoc">
          {{ docBusy ? `⬆ 上传中 ${docProgress}%` : `⬆ 上传${docFiles.length > 1 ? `（${docFiles.length} 个文件）` : ""}` }}
        </button>
        <small v-if="docFiles.length" class="muted">已选 {{ docFiles.length }} 个文件；单次 ≤200 个、单文件 ≤20MB</small>
        <p v-if="!editableProjects.length" class="modal-tip">
          您还没有可上传文档的项目——需为项目负责人或项目所在部门成员；请联系管理员或先创建项目。
        </p>
        <div v-if="docBusy" class="upload-progress" aria-live="polite">
          <div class="upload-progress-bar" :style="{ width: docProgress + '%' }"></div>
          <span class="upload-progress-text">上传中 {{ docProgress }}%（{{ docProgressLabel }}）</span>
        </div>
      </section>

      <section class="doc-tree">
        <div v-for="d in filteredDocTree" :key="d.department_id" class="dt-dept">
          <div class="dt-row dt-l1" @click="toggleTree('d' + d.department_id)">
            <span class="dt-arrow">{{ expandedTree["d" + d.department_id] ? "▼" : "▶" }}</span>
            🏢 <b>{{ d.department_name }}</b>
            <small>{{ d.members.length }} 名成员</small>
          </div>
          <div v-if="expandedTree['d' + d.department_id]" class="dt-children">
            <div v-for="m in d.members" :key="'m' + d.department_id + '-' + m.user_id">
              <div class="dt-row dt-l2" @click="toggleTree('e' + d.department_id + '-' + m.user_id)">
                <span class="dt-arrow">{{ expandedTree["e" + d.department_id + "-" + m.user_id] ? "▼" : "▶" }}</span>
                👤 {{ m.name }}
                <small>{{ m.documents.length }} 份文档</small>
              </div>
              <div v-if="expandedTree['e' + d.department_id + '-' + m.user_id]" class="dt-children">
                <div v-for="doc in m.documents" :key="doc.id" class="dt-row dt-doc">
                  <input
                    v-if="doc.can_delete"
                    type="checkbox"
                    class="dt-check"
                    :checked="selectedDocIds.has(doc.id)"
                    @change="toggleDocSelect(doc, $event.target.checked)"
                    @click.stop
                  />
                  📄 <a :href="`/api/documents/${doc.id}/download`" target="_blank" rel="noopener">{{ doc.original_name }}</a>
                  <small>{{ doc.project_name }} · {{ fmtSize(doc.size) }} · {{ fmtDate(doc.uploaded_at) }}<template v-if="doc.note"> · {{ doc.note }}</template></small>
                  <button v-if="doc.can_delete" class="mini danger" @click.stop="removeDoc(doc)">删除</button>
                </div>
                <p v-if="!m.documents.length" class="dt-empty">该成员暂无文档</p>
              </div>
            </div>
          </div>
        </div>
        <p v-if="docDateFilter && !filteredDocTree.length" class="state">
          该日期没有找到文档——请更换日期或点击「清除筛选」查看全部。
        </p>
        <p v-if="!docTree.length" class="state">暂无文档，先在上方选择项目并上传。</p>
      </section>
    </template>

    <!-- ============ 部门页 ============ -->
    <template v-else-if="view === 'dept'">
      <nav class="crumb"><a href="/">主页</a><span>/</span><b>{{ deptInfo?.name || (deptId === 0 ? "未分部门项目" : "…") }}</b></nav>

      <!-- 功能大类导航：点击进入大类后再访问具体功能 -->
      <div class="dept-tabs">
        <button :class="{ primary: deptTab === 'overview' }" @click="deptTab = 'overview'">📁 项目概览</button>
        <button :class="{ primary: deptTab === 'tasks' }" @click="deptTab = 'tasks'">✅ 任务与进度</button>
        <button :class="{ primary: deptTab === 'daily' }" @click="deptTab = 'daily'">📋 每日任务</button>
      </div>

      <template v-if="deptTab === 'overview'">
      <div class="og-panel-title">部门项目
        <small>点选项目进入「任务与进度」查看排期、进度说明与每日记录</small>
      </div>
      <section class="dept-projects">
        <div class="proj-list">
          <button
            v-for="p in deptProjects"
            :key="p.id"
            class="proj-card"
            :class="{ active: p.id === currentProjectId }"
            @click="selectProject(p.id)"
          >
            <b class="proj-name"><i class="prio-badge" :class="p.priority">{{ p.priority_label }}</i>{{ p.name }}</b>
            <span class="proj-meta">负责人 {{ p.owner_name || "—" }} · {{ p.task_count }} 项任务</span>
            <i class="proj-flag" :class="{ editable: p.can_edit }">{{ p.can_edit ? "可编辑" : "只读" }}</i>
          </button>
          <p v-if="!deptProjects.length" class="state small">该部门暂无项目，可点击右上角「新建项目」。</p>
        </div>
      </section>
      </template>

      <!-- 每日任务：持久化，日期自动为当天；可分配多名成员（交互与任务清单一致） -->
      <section v-if="deptTab === 'daily'" class="daily-section">
        <div class="og-panel-title">📋 每日任务
          <small>日期自动为当天 · 完成状态按人按天记录 · 刷新/重启不丢失</small>
        </div>
        <div class="dt2-add">
          <input
            v-model="newDaily.name"
            :placeholder="`新增每日任务，如：晨会、日报（${todayStr()}）`"
            maxlength="200"
            @keyup.enter="addDailyTask"
          />
          <button class="primary" :disabled="!newDaily.name.trim()" @click="addDailyTask">＋ 添加</button>
        </div>
        <div class="daily-table-wrap">
          <table class="daily-table">
            <thead>
              <tr>
                <th style="width: 52px">ID</th>
                <th>任务名称</th>
                <th>我的说明</th>
                <th style="width: 170px">负责人</th>
                <th style="width: 76px">今日完成</th>
                <th style="width: 100px">日期</th>
                <th style="width: 52px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in dailyTasks" :key="t.id">
                <td>#{{ t.id }}</td>
                <td><input :value="t.name" :disabled="!t.can_manage" @change="saveDaily(t, { name: $event.target.value })" /></td>
                <td>
                  <input
                    :value="t.note"
                    :disabled="!t.assignees.some(a => a.is_me)"
                    :title="t.assignees.some(a => a.is_me) ? '我的内容进度说明（各负责人独立填写、互不可见）' : '仅任务负责人可填写自己的说明'"
                    placeholder="各自独立填写"
                    @change="saveDaily(t, { note: $event.target.value })"
                  />
                </td>
                <td>
                  <button
                    v-if="t.can_manage"
                    class="assignee-summary"
                    title="负责人（可多选）"
                    @click.stop="openDailyPicker($event, t)"
                  >{{ t.assignees.map(a => a.name).join("、") || "未指定" }}</button>
                  <span v-else class="assignee-text">{{ t.assignees.map(a => a.name).join("、") || "—" }}</span>
                </td>
                <td>
                  <input
                    type="checkbox"
                    :checked="t.done_today"
                    :disabled="!t.done_today && !t.assignees.some(a => a.is_me) && !t.can_manage"
                    :title="t.done_today ? '今日已完成（点击取消）' : t.assignees.some(a => a.is_me) || t.can_manage ? '标记今日完成' : '仅负责人可勾选'"
                    @change="toggleDaily(t, $event.target.checked)"
                  />
                </td>
                <td class="dt2-date">{{ t.date }}</td>
                <td><button v-if="t.can_delete" class="icon danger" title="删除任务" @click="removeDaily(t)">✕</button></td>
              </tr>
            </tbody>
          </table>
          <p v-if="!dailyTasks.length" class="state small">暂无每日任务，添加后每天自动出现，可分配给多名成员。</p>
        </div>

        <!-- 负责人多选面板（fixed 定位 + 草稿保存，与任务清单交互一致） -->
        <div v-if="dailyPicker" class="daily-menu" :style="dailyMenuStyle" @click.stop>
          <label v-for="u in selectableUsers" :key="u.id" class="assignee-option">
            <input type="checkbox" :checked="dailyPicker.ids.includes(u.id)" @change="toggleDailyDraft(u.id, $event.target.checked)" />
            <span class="assignee-name">{{ u.display_name }}</span>
          </label>
          <div class="assignee-actions">
            <button type="button" class="mini" @click="dailyPicker = null">取消</button>
            <button type="button" class="mini primary" @click="confirmDailyAssignees">保存</button>
          </div>
        </div>
      </section>

      <template v-if="deptTab === 'tasks' && currentProject">
        <div class="og-panel-title">
          <i class="prio-badge" :class="currentProject.priority">{{ currentProject.priority_label }}</i>
          {{ currentProject.name }}
          <select
            v-if="currentProject.can_edit"
            class="prio-select"
            :value="currentProject.priority"
            title="项目优先级（通知与项目列表中展示）"
            @change="changePriority($event.target.value)"
          >
            <option value="high">🔴 高</option>
            <option value="medium">🟡 中</option>
            <option value="low">⚪ 低</option>
          </select>
          <small>{{ currentProject.department_name }} · 负责人：<button
              v-if="currentUser.role === 'admin'"
              type="button"
              class="owner-edit-link"
              title="点击修改项目负责人"
              @click="openOwnerModal"
            >{{ currentProject.owner_name || "—" }} ✎</button>
            <template v-else>{{ currentProject.owner_name || "—" }}</template>
            <b v-if="!currentProject.can_edit" class="readonly-tag">
              （您对项目仅可查看；作为任务负责人仍可编辑自己的任务）
            </b>
          </small>
        </div>

        <!-- 修改项目负责人（管理员，点项目信息里的名字弹出） -->
        <div v-if="showOwnerModal" class="modal-mask" @click.self="showOwnerModal = false">
          <div class="modal">
            <h2>👤 修改项目负责人</h2>
            <p class="modal-tip">项目「{{ currentProject?.name }}」当前负责人：{{ currentProject?.owner_name || "—" }}</p>
            <label>
              新负责人
              <select v-model.number="ownerDraft">
                <option v-for="u in adminUsers" :key="u.id" :value="u.id">
                  {{ u.display_name }}（{{ u.username }}）
                </option>
              </select>
            </label>
            <footer>
              <button @click="showOwnerModal = false">取消</button>
              <button class="primary" :disabled="ownerSaving || !ownerDraft" @click="saveOwnerModal">
                {{ ownerSaving ? "保存中…" : "确认修改" }}
              </button>
            </footer>
          </div>
        </div>

        <!-- 任务清单：可展开子项（交互样式与"项目进度文档"一致） -->
        <section class="coll-section">
          <header
            class="coll-head"
            role="button"
            :aria-expanded="secTasks"
            :title="secTasks ? '点击收起「任务清单」' : '点击展开「任务清单」'"
            @click="secTasks = !secTasks"
          >
            <span class="coll-caret" :class="{ open: secTasks }" aria-hidden="true">▶</span>
            <strong>任务清单</strong>
            <span class="coll-sub">行内编辑实时保存 · 点击行首 ▶ 展开日期/说明/依赖 · 风险 🔴停滞 🟡关注 🟢正常</span>
            <span class="coll-count">{{ tasks.length }} 项</span>
          </header>
          <div v-if="secTasks" class="coll-body">
            <div class="filter-tabs">
              <button
                v-for="f in filterTabs"
                :key="f.key"
                :class="{ primary: taskFilter === f.key }"
                @click="taskFilter = f.key"
              >
                {{ f.label }} <span class="ft-count">{{ filterCounts[f.key] }}</span>
              </button>
            </div>

            <section class="task-section">
              <TaskTable
                :tasks="filteredTasks"
                :can-edit="!!currentProject.can_edit"
                :users="selectableUsers"
                :current-user-id="currentUser.id"
                :reminding-id="remindingId"
                @update="onTableUpdate"
                @remove="removeTask"
                @remind="remindTask"
              />
            </section>
          </div>
        </section>

        <!-- 项目排期：可展开子项 -->
        <section class="coll-section">
          <header
            class="coll-head"
            role="button"
            :aria-expanded="secGantt"
            :title="secGantt ? '点击收起「项目排期」' : '点击展开「项目排期」（甘特图）'"
            @click="secGantt = !secGantt"
          >
            <span class="coll-caret" :class="{ open: secGantt }" aria-hidden="true">▶</span>
            <strong>项目排期</strong>
            <span class="coll-sub">甘特图为展示视图（不支持拖拽，防止误触）；调整日期或进度请用任务清单</span>
          </header>
          <div v-if="secGantt" class="coll-body">
            <section class="chart-section">
              <div class="chart-toolbar">
                <div class="view-modes" role="group" aria-label="视图切换">
                  <button
                    v-for="m in viewModes"
                    :key="m"
                    :class="{ primary: m === viewMode }"
                    @click="viewMode = m"
                  >
                    {{ viewModeLabel(m) }}
                  </button>
                </div>
                <button class="today-btn" title="滚动到今天所在位置" @click="scrollToToday">
                  <span class="today-dot" aria-hidden="true"></span>回到今天
                </button>
              </div>
              <GanttChart ref="ganttRef" :tasks="tasks" :view-mode="viewMode" />
            </section>
          </div>
        </section>

        <DocumentsPanel
          :project-id="currentProject.id"
          :can-edit="!!currentProject.can_edit"
          :current-user="currentUser"
        />

        <!-- 每日进度记录：可展开子项 -->
        <section class="coll-section">
          <header
            class="coll-head"
            role="button"
            :aria-expanded="secLogs"
            :title="secLogs ? '点击收起「每日进度记录」' : '点击展开「每日进度记录」'"
            @click="secLogs = !secLogs"
          >
            <span class="coll-caret" :class="{ open: secLogs }" aria-hidden="true">▶</span>
            <strong>每日进度记录</strong>
            <span class="coll-sub">项目任务与每日任务的当日快照 · 汇总到工作日志</span>
          </header>
          <div v-if="secLogs" class="coll-body">
            <ProgressLogs :project-id="currentProject.id" :refresh-key="progressRefreshKey" />
          </div>
        </section>
      </template>
      <p v-if="deptTab === 'tasks' && !currentProject" class="state">请先在「项目概览」中选择一个项目。</p>
    </template>

    <!-- 新建项目 -->
    <div v-if="showNewProject" class="modal-mask" @click.self="showNewProject = false">
      <div class="modal">
        <h2>新建项目</h2>
        <label>项目名称 <input v-model="newProject.name" placeholder="如：Q4 版本研发" maxlength="120" /></label>
        <label>项目描述 <input v-model="newProject.description" placeholder="选填" maxlength="500" /></label>
        <label>优先级
          <select v-model="newProject.priority">
            <option value="high">🔴 高</option>
            <option value="medium">🟡 中</option>
            <option value="low">⚪ 低</option>
          </select>
        </label>
        <label>
          所属部门
          <select v-model.number="newProject.department_id" title="项目归属部门（决定谁能看到与编辑该项目）">
            <option v-for="d in projectDeptOptions" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
        </label>
        <template v-if="currentUser.role === 'admin'">
          <label>
            负责人
            <select v-model.number="newProject.owner_id">
              <option v-for="u in adminUsers" :key="u.id" :value="u.id">{{ u.display_name }}（{{ u.username }}）</option>
            </select>
          </label>
        </template>
        <p v-else class="modal-tip">项目将归属上方所选部门，负责人为本人；负责人候选包含您所属部门（含多部门）的成员。</p>
        <footer>
          <button @click="showNewProject = false">取消</button>
          <button class="primary" :disabled="!newProject.name.trim()" @click="createProject">创建</button>
        </footer>
      </div>
    </div>

    <!-- 迁移项目 -->
    <div v-if="showMigrate" class="modal-mask" @click.self="showMigrate = false">
      <div class="modal">
        <h2>📦 迁移项目</h2>
        <p class="modal-tip">
          将「{{ currentProject?.name }}」迁移到其他部门。
          迁移后：任务、负责人、进度日志与文档<b>全部跟随</b>项目，创建人不变；
          原部门中与该项目无关联的成员将不再可见。
        </p>
        <label>
          目标部门
          <select v-model.number="migrateTarget">
            <option v-for="d in migrateDeptOptions" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
        </label>
        <footer>
          <button @click="showMigrate = false">取消</button>
          <button class="primary" :disabled="!migrateTarget || migrateBusy" @click="doMigrate">
            {{ migrateBusy ? "迁移中…" : "确认迁移" }}
          </button>
        </footer>
      </div>
    </div>

    <!-- 修改密码：原密码校验 + 新密码 + 确认一致 -->
    <div v-if="showChangePw" class="modal-mask" @click.self="showChangePw = false">
      <div class="modal">
        <h2>修改密码</h2>
        <label>原密码
          <input type="password" v-model="pwForm.old" placeholder="输入当前密码" autocomplete="current-password" />
        </label>
        <label>新密码
          <input type="password" v-model="pwForm.next" placeholder="至少 6 位" autocomplete="new-password" />
        </label>
        <label>确认新密码
          <input type="password" v-model="pwForm.confirm" placeholder="再次输入新密码" autocomplete="new-password" @keyup.enter="submitChangePw" />
        </label>
        <p v-if="pwError" class="modal-tip pw-error">{{ pwError }}</p>
        <footer>
          <button @click="showChangePw = false">取消</button>
          <button class="primary" :disabled="pwBusy" @click="submitChangePw">{{ pwBusy ? "提交中…" : "确认修改" }}</button>
        </footer>
      </div>
    </div>

    <!-- 新增任务 -->
    <div v-if="showNewTask" class="modal-mask" @click.self="showNewTask = false">
      <div class="modal">
        <h2>新增任务</h2>
        <label>任务名称 <input v-model="newTask.name" placeholder="必填" maxlength="200" /></label>
        <div class="row">
          <label>开始日期 <input type="date" v-model="newTask.start_date" /></label>
          <label>结束日期 <input type="date" v-model="newTask.end_date" /></label>
        </div>
        <div class="row">
          <label>进度
            <select v-model.number="newTask.progress">
              <option v-for="p in progressOptions" :key="p" :value="p">{{ p }}%</option>
            </select>
          </label>
          <div class="field">
            <span class="field-label">负责人（可多选，按部门选择）</span>
            <template v-if="assigneeDeptId === null">
              <div class="dep-list assignee-list">
                <button type="button" class="dep-item dept-entry" @click="assigneeDeptId = -1">
                  <span class="dep-name">👥 全部人员</span>
                  <span class="dept-count">{{ selectableUsers.length }} 人</span>
                  <span class="dt-arrow">▶</span>
                </button>
                <button
                  v-for="g in assigneeDeptGroups"
                  :key="g.deptId"
                  type="button"
                  class="dep-item dept-entry"
                  @click="assigneeDeptId = g.deptId"
                >
                  <span class="dep-name">🏢 {{ g.deptName }}</span>
                  <span class="dept-count">{{ g.users.length }} 人</span>
                  <span v-if="g.checkedCount" class="dept-checked">已选 {{ g.checkedCount }}</span>
                  <span class="dt-arrow">▶</span>
                </button>
                <p v-if="!assigneeDeptGroups.length" class="modal-tip">暂无可选账号</p>
              </div>
            </template>
            <template v-else>
              <div class="assignee-nav">
                <button type="button" class="mini" @click="assigneeDeptId = null">← 返回部门列表</button>
                <span class="muted">{{ currentAssigneeDeptName }}（{{ currentAssigneeUsers.length }} 人）</span>
              </div>
              <div class="dep-list assignee-list">
                <label v-for="u in currentAssigneeUsers" :key="u.id" class="dep-item">
                  <input
                    type="checkbox"
                    :checked="newTask.assignee_ids.includes(u.id)"
                    @change="toggleNewAssignee(u.id, $event.target.checked)"
                  />
                  <span class="dep-name">{{ u.display_name }}</span>
                </label>
              </div>
            </template>
            <div v-if="newTask.assignee_ids.length" class="assignee-actions">
              <span class="field-label">已选负责人：</span>
              <button
                v-for="uid in newTask.assignee_ids"
                :key="uid"
                type="button"
                class="assignee-chip"
                :title="'点击移除 ' + newTaskAssigneeName(uid)"
                @click="removeNewAssignee(uid)"
              >
                {{ newTaskAssigneeName(uid) }} ✕
              </button>
            </div>
          </div>
        </div>
        <div class="field">
          <span class="field-label">前置依赖（勾选需要先完成的任务，可多选）</span>
          <div class="dep-list">
            <label v-for="t in tasks" :key="t.id" class="dep-item">
              <input
                type="checkbox"
                :checked="newTask.depIds.includes(t.id)"
                @change="toggleDep(t.id, $event.target.checked)"
              />
              <span class="dep-id">#{{ t.id }}</span>
              <span class="dep-name">{{ t.name }}</span>
            </label>
            <p v-if="!tasks.length" class="modal-tip">当前项目暂无其他任务，创建后可在表格中补充依赖</p>
          </div>
        </div>
        <footer>
          <button @click="showNewTask = false">取消</button>
          <button class="primary" :disabled="!newTask.name.trim()" @click="createTask">创建</button>
        </footer>
      </div>
    </div>

    <!-- 我的工作日志 -->
    <div v-if="showReport" class="modal-mask" @click.self="showReport = false">
      <div class="modal report-modal">
        <h2>
          {{ reportMode === "weekly" ? "📅 我的工作周报" : "📋 我的工作日志" }}
          <small>{{ reportMode === "weekly" ? weeklyRangeLabel : reportDate }}</small>
        </h2>
        <div class="report-tabs">
          <button :class="{ primary: reportMode === 'daily' }" @click="switchReportMode('daily')">日报</button>
          <button :class="{ primary: reportMode === 'weekly' }" @click="switchReportMode('weekly')">周报</button>
        </div>
        <pre v-if="reportText" class="report-pre">{{ reportText }}</pre>
        <p v-else class="modal-tip">{{ reportLoading ? "生成中…" : "暂无内容" }}</p>
        <div v-if="isToday && reportMode === 'daily'" class="decisions-box">
          <span class="field-label">四、关键决策（当日可填写，保存后自动进入日志）</span>
          <textarea
            v-model="decisionsText"
            rows="3"
            maxlength="1000"
            placeholder="每行一条，如：确定采用 PostgreSQL 作为生产数据库"
          ></textarea>
          <div class="decisions-actions">
            <button class="primary" :disabled="decisionsSaving" @click="saveDecisions">
              {{ decisionsSaving ? "保存中…" : "保存关键决策" }}
            </button>
          </div>
        </div>
        <div v-if="isToday && reportMode === 'daily'" class="decisions-box">
          <span class="field-label">五、补充事项（临时事项，每行一条，保存后自动进入日志）</span>
          <textarea
            v-model="extrasText"
            rows="3"
            maxlength="2000"
            placeholder="每行一条，如：今天XX总经理找我开会"
          ></textarea>
          <div class="decisions-actions">
            <button class="primary" :disabled="extrasSaving" @click="saveExtras">
              {{ extrasSaving ? "保存中…" : "保存补充事项" }}
            </button>
          </div>
        </div>
        <footer>
          <button @click="copyReport">复制全文</button>
          <button class="primary" @click="showReport = false">关闭</button>
        </footer>
      </div>
    </div>

    <ToastHost ref="toastRef" />
    </div>
  </template>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from "vue";
import { api, ApiError } from "./api/client.js";
import TaskTable from "./components/TaskTable.vue";
import GanttChart from "./components/GanttChart.vue";
import DocumentsPanel from "./components/DocumentsPanel.vue";
import ProgressLogs from "./components/ProgressLogs.vue";
import ToastHost from "./components/ToastHost.vue";
import LoginView from "./components/LoginView.vue";

// ---------- 轻量路由：/ 主页；/dept/<id> 部门页（id=0 未分部门） ----------
const route = (() => {
  const m = window.location.pathname.match(/^\/dept\/(\d+)\/?$/);
  return m ? { view: "dept", deptId: Number(m[1]) } : { view: "home" };
})();
const view = ref(route.view);
const deptId = ref(route.deptId ?? null);
// 部门页功能大类页签（项目概览/任务与进度/每日任务）——必须是 ref，否则点击赋值不触发视图切换
const deptTab = ref("overview");

const loading = ref(true);
const currentUser = ref(null);
const projects = ref([]);
const departments = ref([]);
const adminUsers = ref([]);
const users = ref([]);
const tasks = ref([]);
const currentProjectId = ref(null);
const viewMode = ref("Month");
const ganttRef = ref(null);
const toastRef = ref(null);

const showNewProject = ref(false);
const showNewTask = ref(false);
const newProject = reactive({ name: "", description: "", priority: "medium", department_id: null, owner_id: null });
const newTask = reactive({ name: "", start_date: "", end_date: "", progress: 0, assignee_ids: [], depIds: [] });

const showReport = ref(false);
const reportText = ref("");
const reportLoading = ref(false);
const reportDate = new Date().toISOString().slice(0, 10);
const progressRefreshKey = ref(0);
const decisionsText = ref("");
const decisionsSaving = ref(false);
const extrasText = ref(""); // 五、补充事项（临时事项，每行一条）
const extrasSaving = ref(false);
const isToday = computed(() => reportDate === new Date().toISOString().slice(0, 10));

/** 部门图标（禅道风卡片） */
const deptIcons = { 人事行政部: "👥", 财务部: "💰", 总经办: "🏢", 商务运营部: "📊", 销售部: "📈", 项管中心: "📋" };
function deptIcon(name) {
  return deptIcons[name] || "🗂";
}

/** 主页统计条数据 */
const totalProjects = computed(() => departments.value.reduce((s, d) => s + d.project_count, 0) + uncategorizedCount.value);
const totalTasks = computed(() => departments.value.reduce((s, d) => s + d.task_count, 0));
const totalMembers = computed(() => departments.value.reduce((s, d) => s + d.user_count, 0));

async function openReport() {
  showReport.value = true;
  reportLoading.value = true;
  reportText.value = "";
  try {
    reportText.value = await api.dailyReport(reportDate);
    if (isToday.value) {
      const res = await api.getDailyDecisions(reportDate);
      decisionsText.value = res.decisions || "";
      extrasText.value = res.extras || "";
    }
  } catch (e) {
    fail(e);
    showReport.value = false;
  } finally {
    reportLoading.value = false;
  }
}

/** 日报/周报切换 */
const reportMode = ref("daily");
const weeklyRangeLabel = computed(() => {
  const d = new Date(reportDate + "T00:00:00");
  if (Number.isNaN(d.getTime())) return reportDate;
  const monday = new Date(d);
  monday.setDate(d.getDate() - d.getDay() + (d.getDay() === 0 ? -6 : 1));
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  const pad = (n) => String(n).padStart(2, "0");
  const fmt = (x) => `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}`;
  return `${fmt(monday)} ~ ${fmt(sunday)}`;
});

async function switchReportMode(mode) {
  if (reportMode.value === mode) return;
  reportMode.value = mode;
  reportLoading.value = true;
  reportText.value = "";
  try {
    reportText.value =
      mode === "weekly" ? await api.weeklyReport(reportDate) : await api.dailyReport(reportDate);
  } catch (e) {
    fail(e);
  } finally {
    reportLoading.value = false;
  }
}

async function saveDecisions() {
  decisionsSaving.value = true;
  try {
    await api.saveDailyDecisions(reportDate, decisionsText.value);
    reportText.value = await api.dailyReport(reportDate);
    toastRef.value?.showError("关键决策已保存并更新到日志");
  } catch (e) {
    fail(e);
  } finally {
    decisionsSaving.value = false;
  }
}

/** 五、补充事项：临时事项逐行填写，保存后进入当日日志 */
async function saveExtras() {
  extrasSaving.value = true;
  try {
    await api.saveDailyExtras(reportDate, extrasText.value);
    reportText.value = await api.dailyReport(reportDate);
    toastRef.value?.showError("补充事项已保存并更新到日志");
  } catch (e) {
    fail(e);
  } finally {
    extrasSaving.value = false;
  }
}

/** 复制日志全文：Clipboard API 仅在 HTTPS/localhost 可用，
 * 生产是 HTTP 环境（navigator.clipboard 为 undefined）→ 降级 execCommand('copy')。 */
async function copyReport() {
  const text = (reportText.value || "").trim();
  if (!text) {
    toastRef.value?.showInfo("暂无内容可复制");
    return;
  }
  // 1) 优先 Clipboard API（HTTPS / localhost）
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      toastRef.value?.showInfo("已复制到剪贴板");
      return;
    } catch {
      /* 继续尝试降级方案 */
    }
  }
  // 2) 降级：隐藏 textarea + execCommand（HTTP 环境可用）
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    if (!ok) throw new Error("execCommand('copy') 返回 false");
    toastRef.value?.showInfo("已复制到剪贴板");
  } catch {
    fail(new Error("自动复制失败，请长按/全选日志文本手动复制"));
  }
}

const viewModes = ["Day", "Week", "Month", "Year"];
const viewModeLabels = { Day: "日", Week: "周", Month: "月", Year: "年" };
const progressOptions = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100];

const roleLabels = { admin: "管理员", supervisor: "部门主管", employee: "员工" };
const roleLabel = computed(() => roleLabels[currentUser.value?.role] || "");

const deptInfo = computed(() => departments.value.find((d) => d.id === deptId.value) || null);
const deptProjects = computed(() => {
  if (view.value !== "dept") return [];
  if (deptId.value === 0) return projects.value.filter((p) => !p.department_id);
  return projects.value.filter((p) => p.department_id === deptId.value);
});
const uncategorizedCount = computed(() => projects.value.filter((p) => !p.department_id).length);

const currentProject = computed(() => projects.value.find((p) => p.id === currentProjectId.value) || null);
const canDeleteProject = computed(
  () => currentProject.value && (currentUser.value.role === "admin" || currentProject.value.owner_id === currentUser.value.id)
);

/** "我的任务"过滤：当前用户是任务负责人（多选之一） */
function isMine(task) {
  return (task.assignee_ids || []).includes(currentUser.value?.id);
}

const canSeeDashboard = computed(() => ["admin", "supervisor"].includes(currentUser.value?.role));

// ---------- 快捷过滤（全部/我的任务/本周到期/已逾期/停滞） ----------
const taskFilter = ref("all");
const filterTabs = [
  { key: "all", label: "全部" },
  { key: "mine", label: "我的任务" },
  { key: "due_week", label: "本周到期" },
  { key: "overdue", label: "已逾期" },
  { key: "stalled", label: "停滞/关注" },
];

function _isActive(t) {
  return !["done", "cancelled"].includes(t.status || "");
}

const filteredTasks = computed(() => {
  const uid = currentUser.value?.id;
  const today = todayStr();
  const weekLater = todayStr(7);
  return tasks.value.filter((t) => {
    if (taskFilter.value === "mine") return isMine(t);
    if (!_isActive(t)) return taskFilter.value === "all";
    if (taskFilter.value === "due_week") return t.end_date >= today && t.end_date <= weekLater;
    if (taskFilter.value === "overdue") return t.end_date < today;
    if (taskFilter.value === "stalled") return t.risk_level && t.risk_level !== "ok";
    return true;
  });
});

const filterCounts = computed(() => {
  const uid = currentUser.value?.id;
  const today = todayStr();
  const weekLater = todayStr(7);
  const active = tasks.value.filter(_isActive);
  return {
    all: tasks.value.length,
    mine: tasks.value.filter(isMine).length,
    due_week: active.filter((t) => t.end_date >= today && t.end_date <= weekLater).length,
    overdue: active.filter((t) => t.end_date < today).length,
    stalled: tasks.value.filter((t) => t.risk_level && t.risk_level !== "ok").length,
  };
});

// ---------- 全局搜索 ----------
const searchQ = ref("");
const searchResults = ref(null);
const searchInputRef = ref(null);
let searchTimer = null;

function onSearchInput() {
  clearTimeout(searchTimer);
  const q = searchQ.value.trim();
  if (!q) {
    searchResults.value = null;
    return;
  }
  searchTimer = setTimeout(async () => {
    try {
      searchResults.value = await api.search(q);
    } catch {
      /* 静默 */
    }
  }, 250);
}

function gotoProject(projectId) {
  sessionStorage.setItem("og-target-project", String(projectId));
  searchResults.value = null;
  searchQ.value = "";
}

function onGlobalKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    searchInputRef.value?.focus();
  }
}

function viewModeLabel(m) {
  return viewModeLabels[m] || m;
}

function fail(err) {
  if (err instanceof ApiError && err.status === 401) return; // 已由登录门禁接管
  toastRef.value?.showError(err.message || "操作失败，请稍后重试");
}

function todayStr(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function selectProject(id) {
  currentProjectId.value = id;
  deptTab.value = "tasks"; // 选中项目后自动进入「任务与进度」
  loadTasks();
}

async function loadTasks() {
  if (!currentProjectId.value) {
    tasks.value = [];
    return;
  }
  try {
    tasks.value = await api.listTasks(currentProjectId.value);
  } catch (e) {
    fail(e);
  }
}

async function reloadAfterChange() {
  projects.value = await api.listProjects();
  await loadTasks();
  progressRefreshKey.value += 1; // 刷新每日进度记录面板
}

async function onLoggedIn(user) {
  currentUser.value = user;
  await bootstrapData();
  loadDailyTasks();
}

function doLogout() {
  api.logout().catch(() => {}).finally(() => {
    currentUser.value = null;
    projects.value = [];
    tasks.value = [];
  });
}

/** 新建项目可选的部门范围：管理员可选全部；主管/员工只能选自己所属的部门
 * （一人多部门时含全部归属部门），与后端 create_project 校验口径一致。 */
const projectDeptOptions = computed(() => {
  const me = currentUser.value;
  if (!me) return departments.value;
  if (me.role === "admin") return departments.value;
  const mine = new Set(me.department_ids || (me.department_id ? [me.department_id] : []));
  return departments.value.filter((d) => mine.has(d.id));
});

/** 打开新建项目弹窗：预选当前部门页的部门（须属于自己），否则主部门 */
function openNewProject() {
  const opts = projectDeptOptions.value;
  if (opts.length) {
    const inCurrent = view.value === "dept" && opts.some((d) => d.id === deptId.value);
    newProject.department_id = inCurrent ? deptId.value : opts[0].id;
  }
  showNewProject.value = true;
}

// ---------- 项目迁移到其他部门 ----------
const showMigrate = ref(false);
const migrateTarget = ref(null);
const migrateBusy = ref(false);

/** 迁移按钮可见性：管理员/主管对有编辑权的项目；普通员工仅自己创建的项目（与后端口径一致） */
const canMigrateProject = computed(() => {
  const me = currentUser.value;
  const p = currentProject.value;
  if (!me || !p || !p.can_edit) return false;
  if (me.role === "admin" || me.role === "supervisor") return true;
  return p.owner_id === me.id;
});

/** 目标部门选项：管理员/主管可选任意部门；普通员工仅本人所属部门；均排除当前部门 */
const migrateDeptOptions = computed(() => {
  const me = currentUser.value;
  const p = currentProject.value;
  if (!me || !p) return [];
  const exclude = p.department_id;
  if (me.role === "admin" || me.role === "supervisor") {
    return departments.value.filter((d) => d.id !== exclude);
  }
  const mine = new Set(me.department_ids || (me.department_id ? [me.department_id] : []));
  return departments.value.filter((d) => mine.has(d.id) && d.id !== exclude);
});

function openMigrate() {
  migrateTarget.value = migrateDeptOptions.value[0]?.id ?? null;
  showMigrate.value = true;
}

async function doMigrate() {
  const target = migrateDeptOptions.value.find((d) => d.id === migrateTarget.value);
  if (!target || !currentProject.value) return;
  if (
    !window.confirm(
      `确认将项目「${currentProject.value.name}」迁移到「${target.name}」？\n\n` +
        "迁移后任务/负责人/进度/文档全部跟随；原部门中与该项目无关联的成员将不再可见。"
    )
  )
    return;
  migrateBusy.value = true;
  try {
    await api.migrateProject(currentProject.value.id, target.id);
    toastRef.value?.showInfo(`项目已迁移到「${target.name}」`);
    showMigrate.value = false;
    // 迁出后当前部门页不再包含该项目：清空选择并刷新列表
    currentProjectId.value = null;
    tasks.value = [];
    projects.value = await api.listProjects();
    departments.value = await api.listDepartments();
  } catch (e) {
    fail(e);
  } finally {
    migrateBusy.value = false;
  }
}

async function createProject() {
  try {
    const payload = {
      name: newProject.name.trim(),
      description: newProject.description.trim(),
      priority: newProject.priority,
    };
    if (currentUser.value.role === "admin") {
      // 部门页新建时预选该部门
      payload.department_id = newProject.department_id ?? (view.value === "dept" && deptId.value > 0 ? deptId.value : null);
      payload.owner_id = newProject.owner_id;
    } else {
      // 主管/员工：在所属任一部门创建（弹窗已按权限过滤可选项），未选时后端默认主部门
      payload.department_id = newProject.department_id ?? null;
    }
    const created = await api.createProject(payload);
    showNewProject.value = false;
    newProject.name = "";
    newProject.description = "";
    newProject.priority = "medium";
    if (view.value === "dept" && created.department_id === deptId.value) {
      currentProjectId.value = created.id;
    }
    projects.value = await api.listProjects();
    departments.value = await api.listDepartments();
    await loadTasks();
  } catch (e) {
    fail(e);
  }
}

/** 管理员修改项目负责人：点项目信息里的负责人名字 → 弹窗选择 → 保存 */
const showOwnerModal = ref(false);
const ownerDraft = ref(null);
const ownerSaving = ref(false);

function openOwnerModal() {
  ownerDraft.value = currentProject.value?.owner_id ?? null;
  showOwnerModal.value = true;
}

async function saveOwnerModal() {
  const p = currentProject.value;
  if (!p || !ownerDraft.value) return;
  const u = adminUsers.value.find((x) => x.id === ownerDraft.value);
  if (u && u.id === p.owner_id) {
    toastRef.value?.showError("新负责人与当前负责人相同");
    return;
  }
  ownerSaving.value = true;
  try {
    await api.updateProject(p.id, { owner_id: Number(ownerDraft.value) });
    toastRef.value?.showInfo(`项目负责人已改为「${u?.display_name || ownerDraft.value}」`);
    showOwnerModal.value = false;
    projects.value = await api.listProjects();
  } catch (e) {
    fail(e);
  } finally {
    ownerSaving.value = false;
  }
}

async function removeProject() {
  const project = projects.value.find((p) => p.id === currentProjectId.value);
  if (!project) return;
  if (!window.confirm(`确定删除项目「${project.name}」及其所有任务与文档？此操作不可恢复。`)) return;
  try {
    await api.deleteProject(project.id);
    currentProjectId.value = null;
    projects.value = await api.listProjects();
    departments.value = await api.listDepartments();
    tasks.value = [];
  } catch (e) {
    fail(e);
  }
}

function toggleDep(id, checked) {
  const has = newTask.depIds.includes(id);
  if (checked && !has) newTask.depIds.push(id);
  if (!checked && has) newTask.depIds = newTask.depIds.filter((d) => d !== id);
}

/** 新建任务弹窗：负责人多选 */
function toggleNewAssignee(id, checked) {
  const has = newTask.assignee_ids.includes(id);
  if (checked && !has) newTask.assignee_ids.push(id);
  if (!checked && has) newTask.assignee_ids = newTask.assignee_ids.filter((x) => x !== id);
}

/** 负责人两级选择：先部门后人员；跨部门已选人员始终在"已选负责人"区回显可移除 */
const assigneeDeptId = ref(null); // null=部门列表层；-1=全部人员；>0=具体部门
const assigneeDeptGroups = computed(() => {
  const groups = new Map();
  for (const u of selectableUsers.value) {
    const key = u.department_id ?? 0;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(u);
  }
  return [...groups.entries()].map(([deptId, us]) => ({
    deptId,
    deptName: departments.value.find((d) => d.id === deptId)?.name || "未分部门",
    users: us,
    checkedCount: us.filter((u) => newTask.assignee_ids.includes(u.id)).length,
  }));
});
const currentAssigneeDeptName = computed(() => {
  if (assigneeDeptId.value === -1) return "全部人员";
  return (
    assigneeDeptGroups.value.find((g) => g.deptId === assigneeDeptId.value)?.deptName || ""
  );
});
const currentAssigneeUsers = computed(() => {
  if (assigneeDeptId.value === -1) return selectableUsers.value;
  return assigneeDeptGroups.value.find((g) => g.deptId === assigneeDeptId.value)?.users || [];
});
function newTaskAssigneeName(uid) {
  return users.value.find((u) => u.id === uid)?.display_name || `用户#${uid}`;
}
function removeNewAssignee(uid) {
  newTask.assignee_ids = newTask.assignee_ids.filter((x) => x !== uid);
}
watch(showNewTask, (open) => {
  if (open) {
    assigneeDeptId.value = null; // 每次打开回到部门列表层
    // 普通员工（非管理员/主管）新建任务时，负责人默认勾选本人（仍可手动取消或改选他人）
    if (currentUser.value.role === "employee") {
      newTask.assignee_ids = [currentUser.value.id];
    }
  }
});

async function createTask() {
  try {
    await api.createTask(currentProjectId.value, {
      name: newTask.name.trim(),
      start_date: newTask.start_date,
      end_date: newTask.end_date,
      progress: newTask.progress,
      assignee_ids: [...newTask.assignee_ids],
      dependencies: newTask.depIds.join(","),
    });
    showNewTask.value = false;
    newTask.name = "";
    newTask.depIds = [];
    newTask.assignee_ids = [];
    newTask.progress = 0;
    await reloadAfterChange();
  } catch (e) {
    fail(e);
  }
}

async function removeTask(task) {
  if (!window.confirm(`确定删除任务「${task.name}」？`)) return;
  try {
    await api.deleteTask(currentProjectId.value, task.id);
    await reloadAfterChange();
  } catch (e) {
    fail(e);
  }
}

// ---------- 企微任务提醒 ----------
const remindingId = ref(null);

/** 切换项目优先级（详情头部选择器，需编辑权限） */
async function changePriority(priority) {
  try {
    await api.updateProject(currentProjectId.value, { priority });
    projects.value = await api.listProjects();
    toastRef.value?.showError("项目优先级已更新");
  } catch (e) {
    fail(e);
    projects.value = await api.listProjects();
  }
}

// ---------- 我的每日任务（持久化，日期恒为当天；可分配多名成员） ----------
const dailyTasks = ref([]);
const newDaily = reactive({ name: "" });
const dailyPicker = ref(null); // { id: 任务ID, ids: 草稿勾选集合 }
const dailyMenuStyle = ref({});

async function loadDailyTasks() {
  try {
    dailyTasks.value = await api.listDailyTasks();
  } catch (e) {
    fail(e);
  }
}

async function addDailyTask() {
  const name = newDaily.name.trim();
  if (!name) return;
  try {
    await api.createDailyTask({ name });
    newDaily.name = "";
    await loadDailyTasks();
  } catch (e) {
    fail(e);
  }
}

/** 行内编辑保存（名称/说明/负责人），与任务清单一致：变更即存 */
async function saveDaily(task, patch) {
  try {
    const r = await api.updateDailyTask(task.id, patch);
    Object.assign(task, r);
  } catch (e) {
    fail(e);
    await loadDailyTasks();
  }
}

/** 勾选/取消自己的今日完成（完成状态按人按天记录） */
async function toggleDaily(task, done) {
  try {
    const r = await api.updateDailyTask(task.id, { done_today: done });
    Object.assign(task, r);
  } catch (e) {
    fail(e);
    await loadDailyTasks();
  }
}

async function removeDaily(task) {
  if (!window.confirm(`删除每日任务「${task.name}」？`)) return;
  try {
    await api.deleteDailyTask(task.id);
    await loadDailyTasks();
  } catch (e) {
    fail(e);
  }
}

/** 展开负责人多选面板：记录草稿并按按钮位置定位（fixed，避免被容器裁剪） */
function openDailyPicker(e, task) {
  dailyPicker.value = { id: task.id, ids: task.assignees.map(a => a.user_id) };
  const rect = e.currentTarget.getBoundingClientRect();
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - 240));
  const top = Math.min(rect.bottom + 4, window.innerHeight - 280);
  dailyMenuStyle.value = { left: `${left}px`, top: `${top}px` };
}

function toggleDailyDraft(userId, checked) {
  const ids = new Set(dailyPicker.value.ids);
  if (checked) ids.add(userId);
  else ids.delete(userId);
  dailyPicker.value.ids = [...ids];
}

async function confirmDailyAssignees() {
  const task = dailyTasks.value.find(t => t.id === dailyPicker.value.id);
  if (task) await saveDaily(task, { assignee_ids: [...dailyPicker.value.ids] });
  dailyPicker.value = null;
}

function onDailyDocClick(e) {
  if (dailyPicker.value && !e.target.closest(".daily-menu") && !e.target.closest(".assignee-summary")) {
    dailyPicker.value = null;
  }
}

function onDailyKeydown(e) {
  if (e.key === "Escape") dailyPicker.value = null;
}

// ---------- 部门页折叠子项（与"项目进度文档"面板同款交互） ----------
const secTasks = ref(true); // 任务清单默认展开
const secGantt = ref(false);
const secLogs = ref(false);

// ---------- 折叠区首次使用引导（localStorage 记忆，只提示一次） ----------
const collHintShown = ref(localStorage.getItem("og-coll-hint") === "1");
watch([deptTab, currentProjectId], ([tab, pid]) => {
  if (collHintShown.value || tab !== "tasks" || !pid) return;
  collHintShown.value = true;
  localStorage.setItem("og-coll-hint", "1");
  toastRef.value?.showInfo("💡 小提示：点击「任务清单 / 项目排期」等区块标题，可折叠或展开内容");
});

// ---------- 修改密码（原密码校验 + 两次确认 + 规则校验） ----------
const showChangePw = ref(false);
const pwBusy = ref(false);
const pwError = ref("");
const pwForm = reactive({ old: "", next: "", confirm: "" });

async function submitChangePw() {
  pwError.value = "";
  if (!pwForm.old) {
    pwError.value = "请输入原密码";
    return;
  }
  if (pwForm.next.length < 6) {
    pwError.value = "新密码至少 6 位";
    return;
  }
  if (pwForm.next !== pwForm.confirm) {
    pwError.value = "两次输入的新密码不一致";
    return;
  }
  if (pwForm.next === pwForm.old) {
    pwError.value = "新密码不能与原密码相同";
    return;
  }
  pwBusy.value = true;
  try {
    await api.changePassword(pwForm.old, pwForm.next);
    showChangePw.value = false;
    pwForm.old = "";
    pwForm.next = "";
    pwForm.confirm = "";
    toastRef.value?.showError("密码修改成功，下次登录请使用新密码");
  } catch (e) {
    pwError.value = e.message || "修改失败，请稍后重试";
  } finally {
    pwBusy.value = false;
  }
}

// ---------- 工作状态（自助设置；简报统计仅计在岗；支持预计结束时间自动恢复） ----------
const wsUntilDraft = ref("");
function fmtWsUntil(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function setMyStatus(workStatus) {
  try {
    const r = await api.setWorkStatus(workStatus, wsUntilDraft.value || null);
    currentUser.value.work_status = r.work_status;
    currentUser.value.work_status_label = r.work_status_label;
    currentUser.value.work_status_until = r.work_status_until;
    wsUntilDraft.value = r.work_status_until ? r.work_status_until.slice(0, 16) : "";
    toastRef.value?.showError(`工作状态已设为：${r.work_status_label}`);
  } catch (e) {
    fail(e);
  }
}

/** 保存预计结束时间：以当前状态重新提交（时间随请求一并校验与存储） */
async function saveWsUntil() {
  if (!wsUntilDraft.value) return;
  await setMyStatus(currentUser.value.work_status);
}

// ---------- 进度文档中心（部门 → 成员 → 文档） ----------
const docTree = ref([]);
const expandedTree = reactive({});
const docUpload = reactive({ project_id: null, note: "" });
const docBusy = ref(false);
const docFileRef = ref(null);
const docFolderRef = ref(null);
const docFiles = ref([]); // 支持多选与整个文件夹（webkikitDirectory 的 File 列表）
const docProgress = ref(0);
const docProgressLabel = ref("准备上传");
const prevView = ref("home");

const editableProjects = computed(() => projects.value.filter((p) => p.can_edit));

// ---------- 按上传日期筛选文档树（本地时区日期匹配；后端零改动） ----------
const docDateFilter = ref(""); // "" = 显示全部

function docLocalDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const filteredDocTree = computed(() => {
  if (!docDateFilter.value) return docTree.value;
  return docTree.value
    .map((dept) => {
      const members = dept.members
        .map((m) => ({
          ...m,
          documents: (m.documents || []).filter((d) => docLocalDate(d.uploaded_at) === docDateFilter.value),
        }))
        .filter((m) => m.documents.length);
      return { ...dept, members };
    })
    .filter((dept) => dept.members.length);
});

const docFilterCount = computed(() =>
  filteredDocTree.value.reduce((s, d) => s + d.members.reduce((x, m) => x + m.documents.length, 0), 0)
);

// ---------- 多选删除（配合日期筛选：筛某天 → 全选 → 删除） ----------
const selectedDocIds = ref(new Set());

// 当前显示（含筛选）且本人有删除权限的文档
const deletableVisibleDocs = computed(() => {
  const list = [];
  for (const d of filteredDocTree.value) {
    for (const m of d.members) {
      for (const doc of m.documents) {
        if (doc.can_delete) list.push(doc);
      }
    }
  }
  return list;
});

const docDeletableCount = computed(() => deletableVisibleDocs.value.length);

const allVisibleSelected = computed(
  () =>
    docDeletableCount.value > 0 &&
    deletableVisibleDocs.value.every((d) => selectedDocIds.value.has(d.id))
);

function toggleDocSelect(doc, checked) {
  const next = new Set(selectedDocIds.value);
  if (checked) next.add(doc.id);
  else next.delete(doc.id);
  selectedDocIds.value = next;
}

function toggleSelectAllVisible(checked) {
  const next = new Set();
  if (checked) {
    for (const d of deletableVisibleDocs.value) next.add(d.id);
  }
  selectedDocIds.value = next;
}

watch([docDateFilter, docTree], () => {
  if (selectedDocIds.value.size) selectedDocIds.value = new Set(); // 数据刷新后清空选择
});

async function deleteSelectedDocs() {
  const ids = [...selectedDocIds.value];
  if (!ids.length) return;
  if (!window.confirm(`⚠️ 确定删除已勾选的 ${ids.length} 份文档吗？\n删除后不可恢复（文件与记录一并移除）。`)) return;
  // 大规模删除二次确认：超过 20 份需再确认一次，防止误删
  if (ids.length > 20) {
    if (!window.confirm(`⛔ 高危操作：即将删除 ${ids.length} 份文档（含他人的文档时请特别留意）。\n请再次确认是否继续。`)) return;
  }
  docBusy.value = true;
  try {
    const r = await api.bulkDeleteDocIds(ids);
    toastRef.value?.showInfo(`已删除 ${r.deleted} 份文档，释放 ${r.freed_mb} MB`);
    selectedDocIds.value = new Set();
    await loadDocTree();
  } catch (e) {
    fail(e);
  } finally {
    docBusy.value = false;
  }
}

// 进入文档中心（或项目权限变化）时自动选中第一个可编辑项目——
// 否则 select 显示了项目名但 v-model 仍为 null，上传按钮会一直禁用（点击无反应）
watch(
  [() => view.value, editableProjects],
  () => {
    if (view.value !== "docs") return;
    if (
      !docUpload.project_id ||
      !editableProjects.value.some((p) => p.id === docUpload.project_id)
    ) {
      docUpload.project_id = editableProjects.value[0]?.id ?? null;
    }
  },
  { immediate: true }
);

function docFilesPicked() {
  const fromPicker = [...(docFileRef.value?.files || []), ...(docFolderRef.value?.files || [])];
  if (!fromPicker.length) return;
  // 上传前预校验：数量/大小/压缩包格式，选完立即提示，避免上传后才发现不符合条件
  const issues = [];
  let oversized = 0;
  let badArchive = 0;
  let hugeZip = 0;
  for (const f of fromPicker) {
    const rel = f.webkitRelativePath || f.name;
    if (/\.rar$|\.7z$/i.test(rel)) badArchive++;
    else if (/\.zip$/i.test(rel)) {
      if (f.size > 500 * 1024 * 1024) hugeZip++;
    } else if (f.size > 20 * 1024 * 1024) oversized++;
  }
  if (fromPicker.length > 200) {
    issues.push(`已选 ${fromPicker.length} 个文件，超过单次上限 200 个——请分批上传，或将文件夹压缩为 zip（自动解压，包内最多 1000 个文件）`);
  }
  if (badArchive) issues.push(`包含 ${badArchive} 个 rar/7z 压缩包（不支持），请转为 zip`);
  if (hugeZip) issues.push(`包含 ${hugeZip} 个超过 500MB 的 zip 包（zip 上限 500MB）`);
  if (oversized) issues.push(`包含 ${oversized} 个超过 20MB 的普通文件（单文件上限 20MB；请压缩为 zip，包内单文件上限 100MB）`);
  if (issues.length) toastRef.value?.showError(issues.join("；"));
  // 文件夹上传时保留相对路径（webkitRelativePath），服务端按路径归档
  docFiles.value = fromPicker.slice(0, 200);
  if (docFiles.value.length) {
    const totalMB = (docFiles.value.reduce((s, f) => s + f.size, 0) / 1024 / 1024).toFixed(1);
    const first = docFiles.value[0];
    const label = docFiles.value.length > 1 ? `${first.webkitRelativePath || first.name} 等` : (first.webkitRelativePath || first.name);
    toastRef.value?.showInfo(`已选择 ${docFiles.value.length} 个文件（共 ${totalMB} MB）：${label}——请确认项目与备注后点击"上传"`);
  }
}

function toggleDocsView() {
  if (view.value === "docs") {
    view.value = prevView.value;
    return;
  }
  prevView.value = view.value === "docs" ? "home" : view.value;
  view.value = "docs";
  loadDocTree();
}

async function loadDocTree() {
  try {
    docTree.value = await api.documentTree();
  } catch (e) {
    fail(e);
  }
}

async function uploadDoc() {
  if (!docFiles.value.length || !docUpload.project_id) return;
  docBusy.value = true;
  docProgress.value = 0;
  docProgressLabel.value = "准备上传";
  try {
    const first = docFiles.value[0];
    const totalMB = (docFiles.value.reduce((s, f) => s + f.size, 0) / 1024 / 1024).toFixed(1);
    const r = await api.uploadDocumentsBulk(
      docUpload.project_id,
      docFiles.value,
      docUpload.note.trim(),
      (pct) => {
        docProgress.value = pct;
        docProgressLabel.value = `共 ${totalMB} MB`;
      }
    );
    const hint = r.count > 1 ? `（含压缩包解压共 ${r.count} 个文件）` : "";
    toastRef.value?.showInfo(`✅ 上传成功：「${first.webkitRelativePath || first.name}」${hint}`);
    docUpload.note = "";
    docFiles.value = [];
    if (docFileRef.value) docFileRef.value.value = "";
    if (docFolderRef.value) docFolderRef.value.value = "";
    await loadDocTree();
  } catch (e) {
    toastRef.value?.showError(`❌ 上传失败：${e?.message || "未知错误"}`);
    fail(e);
  } finally {
    docBusy.value = false;
    docProgress.value = 0;
  }
}

// ---------- 跨部门文档查询权限（员工自助申请 + 我的授权） ----------
const showDocAccess = ref(false);
const docAccessRows = ref([]);
const daReqDept = ref(null);
const daReqUntil = ref("");
const daReqNote = ref("");
const daReqBusy = ref(false);

function openDocAccess() {
  showDocAccess.value = !showDocAccess.value;
  if (showDocAccess.value) loadDocAccess();
}

async function loadDocAccess() {
  try {
    docAccessRows.value = await api.myDocAccess();
  } catch (e) {
    fail(e);
  }
}

async function submitDocAccess() {
  daReqBusy.value = true;
  try {
    await api.requestDocAccess(daReqDept.value, daReqUntil.value, daReqNote.value);
    const dept = departments.value.find((d) => d.id === daReqDept.value);
    toastRef.value?.showInfo(`已提交申请：查询「${dept?.name || "目标部门"}」文档，等待管理员审批`);
    daReqDept.value = null;
    daReqUntil.value = "";
    daReqNote.value = "";
    await loadDocAccess();
  } catch (e) {
    fail(e);
  } finally {
    daReqBusy.value = false;
  }
}

function toggleTree(key) {
  expandedTree[key] = !expandedTree[key];
}

function fmtSize(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function fmtDate(iso) {
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

async function removeDoc(doc) {
  if (!window.confirm(`删除文档「${doc.original_name}」？`)) return;
  try {
    await api.deleteDocument(doc.id);
    await loadDocTree();
  } catch (e) {
    fail(e);
  }
}

async function remindTask(task) {
  if (remindingId.value != null) return; // 防连点：一次只发一条
  remindingId.value = task.id;
  try {
    const r = await api.remindTask(currentProjectId.value, task.id);
    if (r.ok) {
      const at = r.mentioned_by_mobile?.length
        ? `已 @ ${r.mentioned_by_mobile.join("、")}`
        : "已发送（负责人未配置企微手机号，未 @）";
      toastRef.value?.showError(`「${task.name}」提醒已发到企微群：${at}`);
    } else {
      toastRef.value?.showError(r.reason || r.error || "提醒发送失败");
    }
  } catch (e) {
    fail(e);
  } finally {
    remindingId.value = null;
  }
}

/** 表格行内编辑是唯一的修改入口（甘特图为纯展示，防误触） */
async function onTableUpdate(task, patch) {
  try {
    await api.updateTask(currentProjectId.value, task.id, patch);
    await reloadAfterChange();
  } catch (e) {
    fail(e);
    await loadTasks();
  }
}

function scrollToToday() {
  ganttRef.value?.scrollToToday();
}

function exportCsv() {
  const header = ["ID", "任务名称", "开始日期", "结束日期", "进度%", "负责人", "前置依赖"];
  const rows = tasks.value.map((t) => [t.id, t.name, t.start_date, t.end_date, t.progress, t.assignee, t.dependencies]);
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [header, ...rows].map((r) => r.map(esc).join(",")).join("\r\n");
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${currentProject.value?.name || "tasks"}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * 负责人候选（分级权限）：普通用户只能选择本部门（自己所属任一部门）成员；
 * 主管/管理员可选全部成员。后端在保存时同步强制校验。
 */
const selectableUsers = computed(() => {
  const me = currentUser.value;
  if (!me || me.role !== "employee") return users.value;
  const myDepts = new Set(me.department_ids || (me.department_id ? [me.department_id] : []));
  if (!myDepts.size) return users.value;
  return users.value.filter((u) => {
    const depts = u.department_ids || (u.department_id ? [u.department_id] : []);
    return depts.some((d) => myDepts.has(d));
  });
});

async function bootstrapData() {
  projects.value = await api.listProjects();
  departments.value = await api.listDepartments();
  users.value = await api.listUsers();
  if (currentUser.value.role === "admin") {
    adminUsers.value = await api.admin.listUsers();
    if (departments.value.length) newProject.department_id = departments.value[0].id;
    if (adminUsers.value.length) newProject.owner_id = currentUser.value.id;
  }
  // 部门页默认选中该部门第一个项目；全局搜索跳转时优先选中目标项目
  if (view.value === "dept") {
    const target = sessionStorage.getItem("og-target-project");
    sessionStorage.removeItem("og-target-project");
    const pid = Number(target);
    if (pid && projects.value.some((p) => p.id === pid)) {
      currentProjectId.value = pid;
    } else if (deptProjects.value.length) {
      currentProjectId.value = deptProjects.value[0].id;
    }
  }
  await loadTasks();
  newTask.start_date = todayStr();
  newTask.end_date = todayStr(3);
  checkAutoSave();
  setInterval(checkAutoSave, 5 * 60 * 1000); // 轻提示轮询：每 5 分钟
}

/** 每日 17:30 自动保存的轻提示：每次保存仅提醒一次 */
async function checkAutoSave() {
  try {
    const st = await api.getAutoSaveStatus();
    if (st.saved && st.saved_at) {
      const ack = localStorage.getItem("og-autosave-ack");
      if (ack !== st.saved_at) {
        localStorage.setItem("og-autosave-ack", st.saved_at);
        const time = st.saved_at.slice(11, 16);
        toastRef.value?.showInfo(
          `📋 今日工作日志已自动保存（${st.saved_count} 人）· ${time}`
        );
      }
    }
  } catch {
    /* 状态获取失败不影响使用 */
  }
}

function onUnauthorized() {
  currentUser.value = null;
  projects.value = [];
  tasks.value = [];
}

onMounted(() => {
  window.addEventListener("og:unauthorized", onUnauthorized);
  window.addEventListener("keydown", onGlobalKeydown);
  window.addEventListener("click", onDailyDocClick);
  window.addEventListener("keydown", onDailyKeydown);
  (async () => {
    try {
      currentUser.value = await api.me();
      await bootstrapData();
      loadDailyTasks();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return; // 未登录 → 登录页
      fail(e);
    } finally {
      loading.value = false;
    }
  })();
});

onBeforeUnmount(() => {
  window.removeEventListener("og:unauthorized", onUnauthorized);
  window.removeEventListener("keydown", onGlobalKeydown);
  window.removeEventListener("click", onDailyDocClick);
  window.removeEventListener("keydown", onDailyKeydown);
});
</script>

<style scoped>
.page {
  max-width: 1280px;
  margin: 0 auto;
  padding: 18px 20px 48px;
  width: 100%;
}

.search-box {
  position: relative;
}

.search-box input {
  width: 240px;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.22);
  color: #fff;
  padding: 5px 12px;
  font-size: 13px;
}

.search-box input::placeholder {
  color: rgba(255, 255, 255, 0.55);
}

.search-box input:focus {
  background: rgba(255, 255, 255, 0.2);
  border-color: rgba(255, 255, 255, 0.5);
}

.search-results {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  width: 360px;
  max-height: 420px;
  overflow: auto;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 12px 32px rgba(15, 40, 70, 0.2);
  z-index: 200;
  color: var(--text);
}

.sr-group {
  padding: 7px 12px 3px;
  font-size: 11px;
  color: var(--muted);
  border-bottom: 1px solid #f0f3f8;
}

.sr-item {
  display: block;
  padding: 8px 12px;
  font-size: 13px;
  color: var(--text);
  text-decoration: none;
  cursor: pointer;
}

.sr-item:hover {
  background: #eef5fd;
}

.sr-item.static {
  cursor: default;
  color: var(--muted);
}

.sr-item small {
  display: block;
  color: var(--muted);
  font-size: 11.5px;
  margin-top: 1px;
}

.sr-tag {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--primary);
  font-size: 12px;
}

.filter-tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.filter-tabs button {
  padding: 4px 12px;
  font-size: 13px;
  border-radius: 999px;
}

.filter-tabs .ft-count {
  display: inline-block;
  min-width: 18px;
  text-align: center;
  background: rgba(118, 136, 158, 0.14);
  border-radius: 999px;
  font-size: 11px;
  padding: 0 5px;
  margin-left: 2px;
}

.filter-tabs button.primary .ft-count {
  background: rgba(255, 255, 255, 0.28);
}

.filter-tabs .ft-count {
  opacity: 0.7;
  font-size: 11.5px;
  margin-left: 3px;
}

.crumb {
  display: flex;
  gap: 8px;
  align-items: center;
  color: var(--muted);
  font-size: 13px;
  margin-bottom: 12px;
}

.crumb a {
  color: var(--primary);
  text-decoration: none;
}

.crumb b {
  color: var(--text);
}

.hero {
  position: relative;
  overflow: hidden;
  background: linear-gradient(120deg, #143d66 0%, #1b5286 55%, #1a6fb5 100%);
  border-radius: 14px;
  padding: 30px 32px;
  margin-bottom: 20px;
  color: #fff;
  box-shadow: 0 10px 30px rgba(15, 45, 80, 0.25);
}

.hero-pattern {
  position: absolute;
  inset: 0;
  background-image: radial-gradient(rgba(255, 255, 255, 0.09) 1.2px, transparent 1.2px);
  background-size: 22px 22px;
  pointer-events: none;
}

.hero-main {
  position: relative;
}

.hero h2 {
  margin: 0 0 8px;
  font-size: 24px;
  letter-spacing: 0.5px;
}

.hero p {
  margin: 0 0 20px;
  color: rgba(255, 255, 255, 0.78);
  font-size: 14px;
}

.hero-stats {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.hero-stats .stat {
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 10px;
  padding: 10px 20px;
  min-width: 104px;
  backdrop-filter: blur(3px);
}

.hero-stats .stat b {
  display: block;
  font-size: 22px;
  line-height: 1.2;
}

.hero-stats .stat span {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
}

.dept-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(248px, 1fr));
  gap: 14px;
}

.dept-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px;
  text-decoration: none;
  color: inherit;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.18s ease;
}

.dept-card:hover {
  border-color: var(--primary);
  box-shadow: 0 10px 26px rgba(20, 61, 102, 0.14);
  transform: translateY(-3px);
}

.dept-card:hover .dept-arrow {
  transform: translateX(3px);
  color: var(--primary);
}

.dept-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dept-icon {
  width: 42px;
  height: 42px;
  border-radius: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}

/* 部门六色图标（禅道蓝系衍生） */
.dept-icon.accent-0 { background: #e3edf8; }
.dept-icon.accent-1 { background: #fdf1e3; }
.dept-icon.accent-2 { background: #e8f5ee; }
.dept-icon.accent-3 { background: #f3ecfa; }
.dept-icon.accent-4 { background: #fdeaea; }
.dept-icon.accent-5 { background: #e9f4f6; }

.dept-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.dept-name {
  font-size: 15px;
}

.dept-members {
  color: var(--muted);
  font-size: 12px;
}

.dept-arrow {
  color: var(--muted);
  font-size: 16px;
  transition: all 0.18s ease;
}

.dept-desc {
  margin: 0;
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.6;
  flex: 1;
}

.dept-stats {
  display: flex;
  gap: 8px;
}

.dept-stats .pill {
  background: #f2f6fb;
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 12px;
  color: var(--muted);
}

.dept-stats .pill b {
  color: var(--primary);
  font-weight: 600;
}

@media (max-width: 768px) {
  .hero {
    padding: 22px 20px;
  }

  .hero h2 {
    font-size: 19px;
  }

  .hero-stats .stat {
    min-width: 84px;
    padding: 8px 14px;
  }

  .hero-stats .stat b {
    font-size: 18px;
  }

  .og-navbar .brand .sub {
    display: none;
  }

  .search-box input {
    width: 160px;
  }

  .view-modes button {
    padding: 5px 13px;
  }
}

@media (max-width: 480px) {
  .page {
    padding: 12px 12px 40px;
  }

  .hero {
    padding: 18px 16px;
  }

  .dept-grid {
    grid-template-columns: 1fr;
  }

  .hero-stats .stat {
    flex: 1 1 40%;
    min-width: 0;
  }
}

.dept-projects {
  margin-bottom: 16px;
}

.proj-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 10px;
}

/* 部门页功能大类导航 */
.dept-tabs {
  display: flex;
  gap: 8px;
  margin: 4px 0 14px;
  flex-wrap: wrap;
}

.dept-tabs button {
  font-size: 13.5px;
  padding: 7px 16px;
  border-radius: 8px;
}

/* 任务与进度页签内的可展开子项（交互样式与"项目进度文档"面板一致） */
.coll-section {
  margin-top: 18px;
}

.coll-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border-left: 4px solid var(--primary);
  border-radius: 0 8px 8px 0;
  margin: 0 0 10px;
  font-size: 15px;
  line-height: 1.3;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s ease;
}

/* 悬停反馈：整行高亮，明确"这一行可以点" */
.coll-head:hover {
  background: var(--primary-weak, rgba(47, 107, 255, 0.08));
}

.coll-head strong {
  font-weight: 600;
}

/* 圆形旋转箭头徽标：展开时旋转 90° 朝下并填充主题色 */
.coll-caret {
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

.coll-caret.open {
  transform: rotate(90deg);
  background: var(--primary);
  color: #fff;
}

.coll-head:hover .coll-caret {
  background: var(--primary);
  color: #fff;
}

.coll-sub {
  color: var(--muted);
  font-size: 12px;
}

.coll-count {
  color: var(--muted);
  font-size: 12px;
}

.coll-body {
  animation: collIn 0.15s ease-out;
}

@keyframes collIn {
  from { opacity: 0; transform: translateY(-3px); }
  to { opacity: 1; transform: none; }
}

.proj-card {
  text-align: left;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font: inherit;
  cursor: pointer;
}

.proj-card:hover {
  border-color: var(--primary);
}

.proj-card.active {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15);
}

.proj-name {
  font-size: 14px;
}

/* 项目优先级标识（列表卡片与详情头部共用） */
.prio-badge {
  display: inline-block;
  font-style: normal;
  font-size: 10.5px;
  line-height: 1;
  padding: 2px 6px;
  border-radius: 4px;
  margin-right: 6px;
  vertical-align: 1px;
}

.prio-badge.high {
  background: #fdecec;
  color: #a32d2d;
}

.prio-badge.medium {
  background: #faeeda;
  color: #854f0b;
}

.prio-badge.low {
  background: #f1efe8;
  color: #5f5e5a;
}

.prio-select {
  font-size: 12px;
  padding: 2px 4px;
  margin-left: 6px;
}

/* 负责人两级选择 */
.dept-entry {
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  font-size: 13px;
}

.dept-entry:hover {
  background: rgba(0, 0, 0, 0.05);
  border-radius: 6px;
}

.dept-entry .dep-name {
  flex: 1;
}

.dept-count {
  color: var(--muted);
  font-size: 12px;
}

.dept-checked {
  color: #597ef7;
  font-size: 12px;
  font-weight: 600;
}

.assignee-nav {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0;
}

.assignee-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--panel);
  font-size: 12px;
  padding: 2px 10px;
  margin: 0 4px 4px 0;
  cursor: pointer;
}

.assignee-chip:hover {
  border-color: #f5222d;
  color: #f5222d;
}

/* 文档中心标题与工具条（重排后） */
.docs-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.docs-title b {
  font-size: 17px;
}

.doc-toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 10px 14px;
}

.doc-toolbar-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.doc-toolbar-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  white-space: nowrap;
}

.doc-toolbar-divider {
  width: 1px;
  align-self: stretch;
  background: var(--border);
}

/* 文档中心日期筛选 */
.doc-bulk-bar {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-left: 10px;
  padding-left: 10px;
  border-left: 1px solid var(--border);
}

.dt-check {
  cursor: pointer;
  flex-shrink: 0;
}

.doc-date-filter {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: 12px;
  font-size: 12px;
}

.doc-date-filter input[type="date"] {
  font-size: 12px;
  padding: 2px 4px;
}

/* 项目信息里的可点击负责人（管理员改负责人入口） */
.owner-edit-link {
  background: none;
  border: none;
  border-bottom: 1px dashed var(--muted);
  padding: 0;
  font-size: inherit;
  color: inherit;
  cursor: pointer;
}

.owner-edit-link:hover {
  color: #597ef7;
  border-bottom-color: #597ef7;
}

/* 上传进度条（文档中心） */
.upload-progress {
  position: relative;
  width: 100%;
  height: 18px;
  margin-top: 6px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.25);
  overflow: hidden;
}

.upload-progress-bar {
  height: 100%;
  border-radius: 9px;
  background: linear-gradient(90deg, #36cfc9, #597ef7);
  transition: width 0.2s ease;
}

.upload-progress-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
}

/* 顶部工作状态选择器 */
.ws-select {
  font-size: 12px;
  padding: 2px 4px;
  margin: 0 4px;
}

/* 预计结束时间输入与自动恢复提示（顶栏 chip 内） */
.ws-until-input {
  font-size: 12px;
  padding: 2px 4px;
  margin: 0 4px;
  max-width: 178px;
}

.ws-until-tip {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.75);
  margin: 0 4px;
  white-space: nowrap;
}

.chip-link {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.85);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
}

.chip-link:hover {
  color: #fff;
  text-decoration: underline;
}

.pw-error {
  color: #a32d2d;
  font-size: 12.5px;
  margin: 4px 0 0;
}

/* 每日任务：任务清单同款表格 */
.daily-section {
  margin-top: 14px;
}

.daily-section .dt2-add {
  display: flex;
  gap: 6px;
  margin: 8px 0 10px;
}

.daily-section .dt2-add input {
  flex: 1;
  max-width: 460px;
}

.daily-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel);
}

.daily-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.daily-table th,
.daily-table td {
  border-bottom: 1px solid var(--border);
  padding: 6px 8px;
  text-align: left;
  vertical-align: middle;
}

.daily-table thead th {
  background: #f5f7fa;
  font-weight: 500;
  color: var(--muted);
  font-size: 12.5px;
  white-space: nowrap;
}

.daily-table tbody tr:last-child td {
  border-bottom: none;
}

.daily-table input:not([type="checkbox"]) {
  width: 100%;
}

.daily-table .dt2-date {
  color: var(--muted);
  font-size: 12.5px;
  white-space: nowrap;
}

/* 每日任务负责人多选面板（fixed，与任务清单同款交互） */
.daily-menu {
  position: fixed;
  z-index: 60;
  width: 200px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(15, 40, 70, 0.18);
  padding: 6px;
  max-height: 260px;
  overflow: auto;
}

.assignee-summary {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: none;
  border: none;
  cursor: pointer;
  color: inherit;
  font-size: 13px;
  padding: 3px 6px;
  border-radius: 4px;
}

.assignee-summary:hover {
  background: #eef5fd;
  color: var(--primary);
}

.assignee-text {
  color: var(--muted);
}

.assignee-option {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
}

.assignee-option:hover {
  background: #f0f5ff;
}

.assignee-option input {
  width: auto;
}

.assignee-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  border-top: 1px solid var(--border);
  margin-top: 4px;
  padding-top: 6px;
}

/* 进度文档树（部门 → 成员 → 文档） */
.doc-upload {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  padding: 10px 12px;
  margin-bottom: 12px;
}

.doc-upload select,
.doc-upload input {
  padding: 5px 8px;
}

.doc-tree {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel);
  padding: 6px;
}

.dt-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13.5px;
  transition: background 0.15s ease;
}

.dt-row:hover {
  background: #eef4fc;
}

.dt-check {
  margin: 0;
  cursor: pointer;
  flex-shrink: 0;
}

.dt-doc a {
  font-weight: 500;
}

.dt-l1 {
  font-size: 14px;
}

.dt-children {
  margin-left: 22px;
}

.dt-arrow {
  width: 14px;
  color: var(--muted);
  font-size: 11px;
}

.dt-row small {
  color: var(--muted);
}

.dt-doc {
  cursor: default;
}

.dt-doc a {
  color: var(--primary);
}

.dt-doc button {
  margin-left: auto;
}

.dt-empty {
  color: var(--muted);
  font-size: 12.5px;
  padding: 4px 8px 6px 30px;
}

.proj-meta {
  color: var(--muted);
  font-size: 12px;
}

.proj-flag {
  font-style: normal;
  font-size: 11px;
  color: var(--muted);
  align-self: flex-start;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 1px 8px;
}

.proj-flag.editable {
  color: var(--success);
  border-color: var(--success);
}

.task-section {
  margin-bottom: 14px;
}

.chart-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 14px;
}

/* 视图切换分段控件 + 回到今天 */
.chart-toolbar {
  display: flex;
  align-items: stretch;
  gap: 8px;
  flex-wrap: wrap;
}

.view-modes {
  display: inline-flex;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.view-modes button {
  border: none;
  border-radius: 0;
  border-right: 1px solid var(--border);
  background: transparent;
  padding: 5px 18px;
  font-size: 13px;
  color: var(--muted);
}

.view-modes button:last-child {
  border-right: none;
}

.view-modes button:hover {
  background: #eef5fd;
  color: var(--primary);
}

.view-modes button.primary {
  background: var(--primary);
  color: #fff;
  font-weight: 500;
}

.view-modes button.primary:hover {
  background: var(--primary-dark);
  color: #fff;
}

.today-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 5px 14px;
  font-size: 13px;
  font-weight: 500;
}

.today-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: #eef5fd;
}

.today-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--warning);
  box-shadow: 0 0 0 3px rgba(232, 162, 61, 0.2);
}

.readonly-tag {
  color: #b45309;
}

.state {
  text-align: center;
  color: var(--muted);
  padding: 40px 0;
  font-size: 14px;
}

.state.small {
  padding: 20px 0;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal {
  background: var(--panel);
  border-radius: 12px;
  padding: 20px;
  width: min(480px, calc(100vw - 32px));
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.2);
}

.modal h2 {
  margin: 0 0 4px;
  font-size: 16px;
}

.modal label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--muted);
}

.modal .row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--muted);
}

.field-label {
  font-size: 13px;
}

.dep-list {
  border: 1px solid var(--border);
  border-radius: 6px;
  max-height: 150px;
  overflow: auto;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.dep-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text);
}

.dep-item:hover {
  background: #f0f5ff;
}

.dep-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--primary);
  font-size: 12px;
  min-width: 26px;
}

.dep-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.modal-tip {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.modal footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}

.report-modal {
  width: min(720px, calc(100vw - 40px));
}

.report-pre {
  background: #f7f9fc;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  font-family: ui-monospace, SFMono-Regular, Menlo, "PingFang SC", monospace;
  font-size: 12.5px;
  line-height: 1.7;
  max-height: 46vh;
  overflow: auto;
  white-space: pre-wrap;
  margin: 0;
}

.decisions-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.decisions-box textarea {
  width: 100%;
  resize: vertical;
  font: inherit;
}

.decisions-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
