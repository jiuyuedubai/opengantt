<template>
  <LoginView v-if="!currentUser" @logged-in="onLoggedIn" />

  <div v-else class="page">
    <header class="og-navbar">
      <div class="brand">
        <img src="/favicon.svg" alt="logo" width="26" height="26" />
        <div>
          <h1>OpenGantt 管理后台</h1>
          <p class="sub">员工账号 · 部门管理 · 系统概览</p>
        </div>
      </div>
      <div class="nav-actions">
        <a class="og-nav-link" href="/">← 返回项目管理</a>
        <span class="og-user-chip">
          <b>{{ currentUser.display_name }}</b>
          <i>管理员</i>
          <button @click="doLogout">退出</button>
        </span>
      </div>
    </header>

    <p v-if="!isAdmin" class="state">此页面仅对管理员开放。当前账号角色：{{ currentUser.role }}。</p>

    <template v-else>
      <nav class="tabs">
        <button v-for="t in tabs" :key="t.key" :class="{ primary: tab === t.key }" @click="tab = t.key">
          {{ t.label }}
        </button>
      </nav>

      <!-- 系统概览 -->
      <section v-if="tab === 'overview'" class="panel">
        <div class="stat-cards" v-if="stats">
          <div class="stat-card"><b>{{ stats.user_count }}</b><span>账号总数</span></div>
          <div class="stat-card"><b>{{ stats.active_user_count }}</b><span>启用中</span></div>
          <div class="stat-card"><b>{{ stats.department_count }}</b><span>部门数</span></div>
          <div class="stat-card"><b>{{ stats.project_count }}</b><span>项目数</span></div>
          <div class="stat-card"><b>{{ stats.task_count }}</b><span>任务数</span></div>
          <div class="stat-card"><b>{{ stats.document_count }}</b><span>进度文档</span></div>
        </div>
        <table v-if="stats" class="data-table">
          <thead><tr><th>部门</th><th>账号数</th><th>项目数</th><th>任务数</th></tr></thead>
          <tbody>
            <tr v-for="d in stats.by_department" :key="d.id">
              <td>{{ d.name }}</td><td>{{ d.user_count }}</td><td>{{ d.project_count }}</td><td>{{ d.task_count }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 员工账号 -->
      <section v-if="tab === 'users'" class="panel">
        <form class="inline-form" @submit.prevent="createUser">
          <input v-model="userForm.username" placeholder="用户名（登录用）" required />
          <input v-model="userForm.password" type="password" placeholder="初始密码（≥6位）" required />
          <input v-model="userForm.display_name" placeholder="姓名" />
          <input v-model="userForm.wecom_mobile" placeholder="企微手机号（选填，@提醒用）" />
          <select v-model="userForm.role">
            <option value="employee">普通员工</option>
            <option value="supervisor">部门主管</option>
            <option value="admin">管理员</option>
          </select>
          <select v-model.number="userForm.department_id" title="主部门（首个部门），可在列表中追加多部门">
            <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
          <button class="primary" type="submit">＋ 创建账号</button>
        </form>

        <!-- 分组展示工具栏：部门筛选 + 角色筛选 + 搜索 -->
        <div class="users-toolbar">
          <select v-model="userDeptFilter" title="按部门筛选（成员所属任一部门命中即显示）">
            <option value="all">全部部门</option>
            <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
            <option value="none">未分配部门</option>
          </select>
          <select v-model="userRoleFilter" title="按职级筛选">
            <option value="all">全部职级</option>
            <option value="admin">管理员</option>
            <option value="supervisor">主管</option>
            <option value="employee">普通员工</option>
          </select>
          <input
            v-model="userSearch"
            class="users-search"
            placeholder="🔍 搜索姓名 / 用户名 / 手机号"
          />
          <span class="users-count">共 {{ totalShown }} 人</span>
        </div>

        <table class="data-table">
          <thead>
            <tr><th>用户名</th><th>姓名</th><th>角色</th><th>工作状态</th><th style="width: 150px">预计恢复</th><th>部门</th><th>企微手机号</th><th>状态</th><th style="width: 240px">操作</th></tr>
          </thead>
          <tbody>
            <template v-for="group in groupedUsers" :key="group.deptName">
              <tr class="group-row">
                <td :colspan="9">
                  <span class="group-name">🗂 {{ group.deptName }}</span>
                  <span class="group-meta">{{ group.list.length }} 人</span>
                  <span v-if="group.inactive" class="group-meta warn">含停用 {{ group.inactive }} 人</span>
                </td>
              </tr>
              <tr v-for="u in group.list" :key="u.id" :class="{ inactive: !u.is_active }">
                <td>{{ u.username }}</td>
                <td>{{ u.display_name }}</td>
                <td>
                  <select :value="u.role" @change="changeRole(u, $event.target.value)">
                    <option value="employee">普通员工</option>
                    <option value="supervisor">部门主管</option>
                    <option value="admin">管理员</option>
                  </select>
                </td>
                <td>
                  <select :value="u.work_status" title="每日日志统计仅计入「在岗」" @change="changeWorkStatus(u, $event.target.value)">
                    <option value="working">🟢 在岗</option>
                    <option value="leave">🟠 请假</option>
                    <option value="vacation">🔵 休假</option>
                    <option value="trip">🟣 出差</option>
                  </select>
                </td>
                <td class="mono">{{ u.work_status_until ? fmtWsUntil(u.work_status_until) : "—" }}</td>
                <td>
                  <div class="dept-picker" @click.stop>
                    <button
                      type="button"
                      class="assignee-summary"
                      title="所属部门（点击选择，可多选）"
                      @click="openDeptPicker($event, u)"
                    >{{ (u.departments || []).join("、") || "（未分配）" }}</button>
                    <div v-if="deptPicker?.uid === u.id" class="assignee-menu" :style="deptMenuStyle">
                      <label v-for="d in departments" :key="d.id" class="assignee-option">
                        <input
                          type="checkbox"
                          :checked="deptPicker.ids.includes(d.id)"
                          @change="toggleDeptDraft(d.id, $event.target.checked)"
                        />
                        <span class="assignee-name">{{ d.name }}</span>
                      </label>
                      <div class="assignee-actions">
                        <button type="button" class="mini" @click="deptPicker = null">取消</button>
                        <button type="button" class="mini primary" @click="confirmDeptPicker(u)">保存</button>
                      </div>
                    </div>
                  </div>
                </td>
                <td>
                  <input
                    :value="u.wecom_mobile || ''"
                    placeholder="选填，@提醒用"
                    title="企业微信登录手机号；配置后任务提醒可在群里 @ 该成员"
                    @change="changeMobile(u, $event.target.value)"
                  />
                </td>
                <td>{{ u.is_active ? "启用" : "停用" }}</td>
                <td class="ops">
                  <button class="mini" @click="toggleActive(u)">{{ u.is_active ? "停用" : "启用" }}</button>
                  <button class="mini" @click="resetPw(u)">重置密码</button>
                  <button class="mini danger" @click="removeUser(u)">删除</button>
                </td>
              </tr>
            </template>
            <tr v-if="!groupedUsers.length">
              <td :colspan="9" class="empty-row">没有符合条件的账号（试试调整部门/职级筛选或搜索关键词）</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 工作日志导出 -->
      <section v-if="tab === 'reports'" class="panel">
        <div class="report-controls">
          <label>
            员工
            <select v-model.number="reportUserId">
              <option v-for="u in users" :key="u.id" :value="u.id">{{ u.display_name }}（{{ u.username }}）</option>
            </select>
          </label>
          <label>
            日期
            <input type="date" v-model="reportDay" />
          </label>
          <button class="primary" :disabled="reportBusy || !reportUserId" @click="viewUserReport('day')">查看当日日志</button>
          <button :disabled="reportBusy || !reportUserId" @click="downloadUserReport('day')">下载当日 .md</button>
          <button :disabled="wecomBusy" title="把全员当日日志经 AI 整理成简报，推送到企业微信群" @click="pushWecom(false)">推送企微简报</button>
          <button :disabled="reportBusy || !reportUserId" @click="viewUserReport('history')">查看全部历史</button>
          <button :disabled="reportBusy || !reportUserId" @click="downloadUserReport('history')">导出全部历史 .md</button>
        </div>
        <p class="report-hint">
          当日日志 = 任务进度快照 + 进度说明 + 关键决策，按公司工作日志模板生成；全部历史 = 该用户所有有记录日期的日志合并（最近在前）。
        </p>
        <pre v-if="reportText" class="report-pre">{{ reportText }}</pre>
      </section>

      <!-- 投入度分析 -->
      <section v-if="tab === 'activity'" class="panel">
        <div class="report-controls">
          <label>
            统计窗口
            <select v-model.number="activityDays" @change="loadActivity">
              <option :value="7">近 7 天</option>
              <option :value="14">近 14 天</option>
              <option :value="30">近 30 天</option>
            </select>
          </label>
          <p class="report-hint">
            🚩 = 名下有任务但窗口内零进度更新。指标仅作参考，请结合请假/跨项目支援等实际情况判断。
          </p>
        </div>
        <table class="data-table og-zebra">
          <thead>
            <tr>
              <th>员工</th><th>部门</th><th>名下任务</th><th>进度更新</th>
              <th>说明填写率</th><th>平均停滞天数</th><th>最后活跃</th><th>最后登录</th><th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in activity" :key="u.user_id" :class="{ flagged: u.flag }">
              <td>{{ u.name }} <small class="muted">@{{ u.username }}</small></td>
              <td>{{ u.department || "—" }}</td>
              <td>{{ u.task_count }}</td>
              <td>{{ u.updates }}</td>
              <td>{{ u.note_rate }}%</td>
              <td>{{ u.avg_stall_days }}</td>
              <td>{{ u.last_active || "—" }}</td>
              <td>{{ u.last_login || "—" }}</td>
              <td>
                <span v-if="u.flag" class="flag-badge">🚩 未投入</span>
                <span v-else class="ok-badge">正常</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 部门管理 -->
      <section v-if="tab === 'departments'" class="panel">
        <form class="inline-form" @submit.prevent="createDept">
          <input v-model="deptForm.name" placeholder="部门名称" required />
          <input v-model="deptForm.description" placeholder="部门说明（选填）" />
          <button class="primary" type="submit">＋ 新建部门</button>
        </form>
        <table class="data-table">
          <thead>
            <tr><th>部门名称</th><th>说明</th><th>账号数</th><th>项目数</th><th style="width: 160px">操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="d in departments" :key="d.id">
              <td>{{ d.name }}</td>
              <td>{{ d.description || "—" }}</td>
              <td>{{ d.user_count }}</td>
              <td>{{ d.project_count }}</td>
              <td class="ops">
                <button class="mini" @click="renameDept(d)">改名</button>
                <button class="mini danger" @click="removeDept(d)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
      <!-- 操作日志（审计） -->
      <section v-if="tab === 'audit'" class="panel">
        <div class="report-controls">
          <label>
            操作人
            <select v-model.number="auditFilter.user_id" @change="queryAudit(1)">
              <option :value="0">全部人员</option>
              <option v-for="u in users" :key="u.id" :value="u.id">{{ u.display_name }}（{{ u.username }}）</option>
            </select>
          </label>
          <label>
            操作类型
            <select v-model="auditFilter.action" @change="queryAudit(1)">
              <option value="">全部类型</option>
              <option v-for="a in auditActions" :key="a.value" :value="a.value">{{ a.label }}</option>
            </select>
          </label>
          <label>
            开始日期
            <input type="date" v-model="auditFilter.start_date" @change="queryAudit(1)" />
          </label>
          <label>
            结束日期
            <input type="date" v-model="auditFilter.end_date" @change="queryAudit(1)" />
          </label>
          <button @click="resetAuditFilter">重置</button>
        </div>
        <table class="data-table og-zebra">
          <thead>
            <tr>
              <th style="width: 150px">操作时间</th>
              <th style="width: 130px">操作人</th>
              <th style="width: 110px">操作类型</th>
              <th style="width: 170px">操作对象</th>
              <th>详情</th>
              <th style="width: 110px">IP 地址</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!audit.items.length">
              <td colspan="6" class="empty-tip">当前筛选条件下暂无日志</td>
            </tr>
            <tr v-for="r in audit.items" :key="r.id">
              <td class="mono">{{ formatAuditTime(r.created_at) }}</td>
              <td>{{ r.operator }} <small class="muted" v-if="r.user_id">@{{ r.username }}</small></td>
              <td>
                <span class="action-badge" :class="{ sensitive: r.sensitive }">{{ r.action_label }}</span>
              </td>
              <td class="obj-cell" :title="r.object_name">{{ r.object_name || (r.object_type ? "#" + r.object_id : "—") }}</td>
              <td class="detail-cell" :title="r.detail">{{ r.detail || "—" }}</td>
              <td class="mono">{{ r.ip || "—" }}</td>
            </tr>
          </tbody>
        </table>
        <div class="pager" v-if="audit.total">
          <span class="muted">共 {{ audit.total }} 条 · 第 {{ audit.page }}/{{ totalPages }} 页</span>
          <button class="mini" :disabled="audit.page <= 1" @click="queryAudit(audit.page - 1)">上一页</button>
          <button class="mini" :disabled="audit.page >= totalPages" @click="queryAudit(audit.page + 1)">下一页</button>
        </div>
      </section>

      <!-- 数据备份与回退 -->
      <section v-if="tab === 'backup'" class="panel">
        <div class="report-controls">
          <button class="primary" :disabled="backupBusy" @click="createBackupNow">
            {{ backupBusy ? "备份中…" : "⬇ 立即备份" }}
          </button>
          <button :disabled="backupBusy" @click="loadBackups">刷新列表</button>
          <button
            class="danger"
            :disabled="backupBusy || !selectedFilenames.length"
            @click="deleteSelected"
          >🗑 删除选中{{ selectedFilenames.length ? `（${selectedFilenames.length}）` : "" }}</button>
          <p class="report-hint">
            每日 17:30 归档后自动备份一次（保留最近 30 份）；也可随时手动备份。
            回退会<b>覆盖当前全部数据</b>——回退前系统会自动生成一份「回退前快照」防反悔，请谨慎操作。
          </p>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 36px">
                <input
                  type="checkbox"
                  :checked="allBackupsSelected"
                  title="全选/取消全选"
                  @change="toggleSelectAll($event.target.checked)"
                />
              </th>
              <th style="width: 80px">版本号</th>
              <th style="width: 170px">备份时间</th>
              <th style="width: 110px">大小</th>
              <th style="width: 110px">方式</th>
              <th style="width: 220px">文件名</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!backups.length">
              <td colspan="7" class="empty-tip">暂无备份，点击上方「立即备份」或等待每日自动备份</td>
            </tr>
            <tr v-for="b in backups" :key="b.filename" :class="{ inactive: b.trigger === 'pre_restore' }">
              <td>
                <input v-model="selectedFilenames" type="checkbox" :value="b.filename" />
              </td>
              <td class="mono">v{{ b.version }}</td>
              <td class="mono">{{ b.created_at }}</td>
              <td>{{ (b.size / 1024).toFixed(1) }} KB</td>
              <td>
                <span class="action-badge">{{ backupTriggerLabel(b.trigger) }}</span>
              </td>
              <td class="mono" :title="b.filename">{{ b.filename }}</td>
              <td>
                <button class="mini danger" :disabled="backupBusy" @click="restoreBackup(b)">回退到此版本</button>
                <button class="mini danger" :disabled="backupBusy" @click="deleteBackupOne(b)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 绩效考核 -->
      <section v-if="tab === 'perf'" class="panel">
        <h3 class="section-title">① 考核表模板库（每员工预存一份，生成考核时直接调用）</h3>
        <div class="report-controls">
          <select v-model.number="perfTplUser">
            <option :value="null" disabled>选择员工…</option>
            <option v-for="u in perfUsers" :key="u.id" :value="u.id">{{ u.display_name }}（{{ u.username }}）</option>
          </select>
          <input ref="perfFileInput" type="file" accept=".doc,.docx,.pdf,.xlsx,.xls" />
          <button class="primary" :disabled="perfBusy || !perfTplUser" @click="uploadPerfTpl">上传/替换考核表</button>
          <p class="report-hint">支持 doc/docx/pdf/xls/xlsx，单份 ≤ 20MB；同一员工重复上传将替换旧表。</p>
        </div>
        <table class="data-table">
          <thead><tr><th>员工</th><th>文件名</th><th>大小</th><th>上传时间</th><th style="width: 150px">操作</th></tr></thead>
          <tbody>
            <tr v-if="!perfTemplates.length"><td colspan="5" class="empty-tip">暂无考核表模板</td></tr>
            <tr v-for="t in perfTemplates" :key="t.id">
              <td>{{ t.user_name }}</td>
              <td class="mono" :title="t.original_name">{{ t.original_name }}</td>
              <td>{{ (t.size / 1024).toFixed(1) }} KB</td>
              <td class="mono">{{ t.uploaded_at }}</td>
              <td>
                <a class="mini" :href="`/api/admin/performance/templates/${t.id}/download`">下载</a>
                <button class="mini danger" @click="removePerfTpl(t)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>

        <h3 class="section-title">② 生成考核结果（勾选员工 → 自动聚合任务/日志数据 → 存档）</h3>
        <div class="report-controls">
          <input v-model="perfSearch" placeholder="🔍 搜索姓名 / 用户名" />
          <label>考核周期 <input type="month" v-model="perfPeriod" /></label>
          <button class="primary" :disabled="perfBusy || !perfSelected.length" @click="generatePerf">
            ⚙️ 生成考核结果{{ perfSelected.length ? `（${perfSelected.length} 人）` : "" }}
          </button>
          <button :disabled="perfBusy" @click="exportPerfZip">📦 打包下载（{{ perfPeriod }}）</button>
          <p class="report-hint">
            自动汇总每位员工名下任务完成率、平均进度、逾期数、日志与每日任务提交天数，并<b>扫描其上传的全部文档</b>（含压缩包解压文件）；
            同一员工同一周期重复生成将覆盖旧结果。综合评价默认留人工填写；
            如需 AI 建议评分，直接在 WorkBuddy 对话中说「处理绩效 AI 评分」，由 WorkBuddy 助手远程扫描数据与文档后写回。
          </p>
        </div>
        <div class="perf-pick">
          <label v-for="u in perfPickUsers" :key="u.id" class="assignee-option">
            <input type="checkbox" :value="u.id" v-model="perfSelected" />
            <span>{{ u.display_name }}（{{ u.username }}）</span>
          </label>
        </div>

        <h3 class="section-title">③ 考核结果存档</h3>
        <table class="data-table">
          <thead><tr><th>周期</th><th>员工</th><th>任务总数</th><th>已完成</th><th>逾期</th><th>平均进度</th><th>日志天数</th><th>生成时间</th><th style="width: 110px">操作</th></tr></thead>
          <tbody>
            <tr v-if="!perfResults.length"><td colspan="9" class="empty-tip">暂无考核结果</td></tr>
            <tr v-for="r in perfResults" :key="r.id">
              <td class="mono">{{ r.period }}</td>
              <td>{{ r.user_name }}</td>
              <td>{{ r.metrics.task_total ?? 0 }}</td>
              <td>{{ r.metrics.task_done ?? 0 }}</td>
              <td :class="{ 'perf-overdue': (r.metrics.task_overdue ?? 0) > 0 }">{{ r.metrics.task_overdue ?? 0 }}</td>
              <td>{{ r.metrics.avg_progress ?? 0 }}%</td>
              <td>{{ r.metrics.log_days ?? 0 }}</td>
              <td class="mono">{{ r.created_at }}</td>
              <td><a class="mini" :href="`/api/admin/performance/results/${r.id}/download`">下载摘要</a></td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 文档权限：跨部门查询授权 -->
      <section v-if="tab === 'docaccess'" class="panel">
        <h3 class="section-title">① 直接授权（跳过申请流程，立即生效）</h3>
        <div class="report-controls">
          <select v-model.number="daGrantUser">
            <option :value="null" disabled>选择员工…</option>
            <option v-for="u in perfUsers" :key="u.id" :value="u.id">{{ u.display_name }}（{{ u.username }}）</option>
          </select>
          <select v-model.number="daGrantDept">
            <option :value="null" disabled>目标部门…</option>
            <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
          <label>有效期至 <input type="datetime-local" v-model="daGrantUntil" /></label>
          <button class="primary" :disabled="daBusy || !daGrantUser || !daGrantDept || !daGrantUntil" @click="doGrant">授权</button>
          <p class="report-hint">到期自动失效（查询时动态判断，无需人工清理）；单次授权最长 365 天。</p>
        </div>
        <h3 class="section-title">② 员工申请与授权记录</h3>
        <table class="data-table">
          <thead><tr><th>申请人</th><th>目标部门</th><th>状态</th><th>有效期至</th><th>说明</th><th style="width: 180px">操作</th></tr></thead>
          <tbody>
            <tr v-if="!docGrants.length"><td colspan="6" class="empty-tip">暂无申请与授权记录</td></tr>
            <tr v-for="g in docGrants" :key="g.id" :class="{ inactive: g.status === 'revoked' || g.expired }">
              <td>{{ g.user_name }}</td>
              <td>{{ g.department_name }}</td>
              <td>
                <span class="action-badge" :class="{ sensitive: g.status === 'pending' }">
                  {{ g.status === "approved" && g.expired ? "已过期" : g.status_label }}
                </span>
              </td>
              <td class="mono">{{ g.expires_at }}</td>
              <td :title="g.note">{{ g.note || "—" }}</td>
              <td>
                <template v-if="g.status === 'pending'">
                  <button class="mini primary" :disabled="daBusy" @click="decideGrant(g, 'approve')">批准</button>
                  <button class="mini danger" :disabled="daBusy" @click="decideGrant(g, 'revoke')">拒绝</button>
                </template>
                <template v-else-if="g.status === 'approved' && !g.expired">
                  <button class="mini danger" :disabled="daBusy" @click="decideGrant(g, 'revoke')">撤销</button>
                </template>
                <span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="report-hint">
          权限逻辑：授权生效 = 状态「生效中」且未到期（到期自动失效）；员工在首页「进度文档」中可自助申请，
          批准后其文档中心即可浏览目标部门的文档（下载同受控）；撤销即时失效。
        </p>

        <h3 class="section-title">③ 批量删除（按上传人 / 上传日期）</h3>
        <div class="report-controls">
          <select v-model.number="bdUserId">
            <option :value="null">全部上传人</option>
            <option v-for="u in perfUsers" :key="u.id" :value="u.id">{{ u.display_name }}（{{ u.username }}）</option>
          </select>
          <label>上传日期 <input type="date" v-model="bdDate" /></label>
          <button class="primary" :disabled="bdBusy || (!bdUserId && !bdDate)" @click="queryBulk">🔍 查询将删除的文档</button>
        </div>
        <div v-if="bdStats" class="report-controls" style="flex-direction: column; align-items: flex-start">
          <p class="report-hint" style="margin: 0">
            匹配 <b>{{ bdStats.count }}</b> 份文档，共 <b>{{ (bdStats.total_size / 1024 / 1024).toFixed(1) }} MB</b>
            （上传人：{{ bdStats.user_name }}；日期：{{ bdStats.date }}）
          </p>
          <ul class="muted" style="margin: 4px 0 0; padding-left: 18px; font-size: 12px">
            <li v-for="s in bdStats.samples" :key="s">{{ s }}</li>
            <li v-if="bdStats.count > bdStats.samples.length">…等共 {{ bdStats.count }} 份</li>
          </ul>
          <button class="danger" :disabled="bdBusy || !bdStats.count" @click="doBulkDelete">
            🗑 删除以上 {{ bdStats.count }} 份文档
          </button>
        </div>
      </section>

    </template>

    <ToastHost ref="toastRef" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from "vue";
import { api, ApiError } from "./api/client.js";
import LoginView from "./components/LoginView.vue";
import ToastHost from "./components/ToastHost.vue";

const currentUser = ref(null);
const tab = ref("overview");
const tabs = [
  { key: "overview", label: "系统概览" },
  { key: "users", label: "员工账号" },
  { key: "departments", label: "部门管理" },
  { key: "reports", label: "工作日志" },
  { key: "activity", label: "投入度分析" },
  { key: "audit", label: "操作日志" },
  { key: "backup", label: "数据备份" },
  { key: "perf", label: "绩效考核" },
  { key: "docaccess", label: "文档权限" },
];
const stats = ref(null);
const users = ref([]);
const departments = ref([]);

// ---------- 员工账号：部门分组展示 + 部门/角色筛选 + 搜索（仅展示结构，行内功能不变） ----------
const userSearch = ref("");
const userDeptFilter = ref("all"); // "all" | 部门 id | "none"（未分配）
const userRoleFilter = ref("all"); // "all" | admin | supervisor | employee
const ROLE_ORDER = { admin: 0, supervisor: 1, employee: 2 };
const ROLE_CN = { admin: "管理员", supervisor: "主管", employee: "普通员工" };

const filteredUsers = computed(() => {
  const kw = userSearch.value.trim().toLowerCase();
  return users.value.filter((u) => {
    if (userDeptFilter.value !== "all") {
      const ids = u.department_ids || [];
      if (userDeptFilter.value === "none") {
        if (ids.length) return false;
      } else if (!ids.includes(userDeptFilter.value)) {
        return false;
      }
    }
    if (userRoleFilter.value !== "all" && u.role !== userRoleFilter.value) return false;
    if (kw) {
      const hay = `${u.display_name} ${u.username} ${u.wecom_mobile || ""}`.toLowerCase();
      if (!hay.includes(kw)) return false;
    }
    return true;
  });
});

const groupedUsers = computed(() => {
  const order = new Map(departments.value.map((d, i) => [d.name, i]));
  const groups = new Map();
  for (const u of filteredUsers.value) {
    const mainDept = (u.departments || [])[0] || "未分配部门";
    if (!groups.has(mainDept)) groups.set(mainDept, []);
    groups.get(mainDept).push(u);
  }
  const result = [...groups.entries()].map(([deptName, list]) => ({
    deptName,
    list: [...list].sort(
      (a, b) =>
        (ROLE_ORDER[a.role] ?? 9) - (ROLE_ORDER[b.role] ?? 9) ||
        (a.display_name || "").localeCompare(b.display_name || "", "zh-Hans-CN")
    ),
    inactive: list.filter((u) => !u.is_active).length,
  }));
  // 组按部门管理列表的顺序排列，未分配部门固定在最后
  result.sort(
    (a, b) =>
      (order.has(a.deptName) ? order.get(a.deptName) : 999) -
      (order.has(b.deptName) ? order.get(b.deptName) : 999)
  );
  return result;
});

const totalShown = computed(() => filteredUsers.value.length);
const activity = ref([]);
const activityDays = ref(14);
const toastRef = ref(null);
const userForm = reactive({ username: "", password: "", display_name: "", wecom_mobile: "", role: "employee", department_id: null });
const deptForm = reactive({ name: "", description: "" });

async function loadActivity() {
  try {
    activity.value = await api.stats.userActivity(activityDays.value);
  } catch (e) {
    fail(e);
  }
}

// 工作日志导出
const reportUserId = ref(null);
// 响应式日期：必须是 ref，否则 v-model 写不进来，请求永远带页面加载时的初始日期（今天）
const reportDay = ref(new Date().toISOString().slice(0, 10));
const reportText = ref("");
const reportBusy = ref(false);
const reportMode = ref("day");

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

// ---------- 企微简报推送 ----------
const wecomBusy = ref(false);

async function pushWecom(forceFallback) {
  wecomBusy.value = true;
  try {
    const r = await api.admin.wecomTestPush({ force_fallback: !!forceFallback });
    if (r.ok) {
      toastRef.value?.showInfo(`已推送到企业微信群（${r.mode === "ai" ? "AI 简报" : "模板汇总"}），请到群里查看`);
    } else {
      toastRef.value?.showError(r.reason || r.wecom?.resp?.errmsg || r.error || "推送失败");
    }
  } catch (e) {
    fail(e);
  } finally {
    wecomBusy.value = false;
  }
}

// ---------- 数据备份与回退 ----------
const backups = ref([]);
const backupBusy = ref(false);
const selectedFilenames = ref([]); // 多选删除：以文件名标识

const allBackupsSelected = computed(
  () => backups.value.length > 0 && selectedFilenames.value.length === backups.value.length
);

function toggleSelectAll(checked) {
  selectedFilenames.value = checked ? backups.value.map((b) => b.filename) : [];
}

function backupTriggerLabel(t) {
  return { auto: "每日自动", manual: "手动", pre_restore: "回退前快照" }[t] || t;
}

/** 预计恢复时间显示（MM-DD HH:mm） */
function fmtWsUntil(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function loadBackups() {
  try {
    backups.value = await api.admin.listBackups();
    selectedFilenames.value = []; // 列表刷新后清空选中，避免与文件错位
  } catch (e) {
    fail(e);
  }
}

/** 删除结果的统一提示与刷新：成功份数 + 释放空间 + 失败清单 */
function notifyDeleteResult(result) {
  const kb = (result.freed / 1024).toFixed(1);
  if (result.failed.length) {
    const first = result.failed[0];
    toastRef.value?.showError(
      `已删除 ${result.deleted.length} 份、释放 ${kb} KB；${result.failed.length} 份失败（如：${first.filename}）`
    );
  } else {
    toastRef.value?.showInfo(`已删除 ${result.deleted.length} 份备份，释放磁盘空间 ${kb} KB`);
  }
  return loadBackups();
}

async function createBackupNow() {
  backupBusy.value = true;
  try {
    const info = await api.admin.createBackup();
    toastRef.value?.showInfo(`备份完成：v${info.version}（${(info.size / 1024).toFixed(1)} KB）`);
    await loadBackups();
  } catch (e) {
    fail(e);
  } finally {
    backupBusy.value = false;
  }
}

async function restoreBackup(b) {
  const okToGo = window.confirm(
    `⚠️ 确认回退到 v${b.version}（${b.created_at}）？\n\n` +
      "回退将覆盖当前全部数据（账号/项目/任务/日志等）。\n" +
      "系统会先自动生成一份「回退前快照」，回退失误时可再次回退找回。"
  );
  if (!okToGo) return;
  backupBusy.value = true;
  try {
    const r = await api.admin.restoreBackup(b.filename);
    toastRef.value?.showInfo(`已回退到 v${r.version}；回退前快照：${r.pre_restore_backup}`);
    await loadBackups();
  } catch (e) {
    fail(e);
  } finally {
    backupBusy.value = false;
  }
}

async function deleteBackupOne(b) {
  if (!window.confirm(`确定删除备份 v${b.version}（${b.created_at}）？\n删除后该版本不可再用于回退，无法恢复！`)) return;
  backupBusy.value = true;
  try {
    const result = await api.admin.deleteBackups([b.filename]);
    await notifyDeleteResult(result);
  } catch (e) {
    fail(e);
  } finally {
    backupBusy.value = false;
  }
}

async function deleteSelected() {
  const n = selectedFilenames.value.length;
  if (!n) return;
  if (!window.confirm(`确定删除选中的 ${n} 份备份？\n删除后这些版本不可再用于回退，无法恢复！`)) return;
  backupBusy.value = true;
  try {
    const result = await api.admin.deleteBackups([...selectedFilenames.value]);
    await notifyDeleteResult(result);
  } catch (e) {
    fail(e);
  } finally {
    backupBusy.value = false;
  }
}

watch(tab, (t) => {
  if (t === "backup" && !backups.value.length) loadBackups();
  if (t === "perf") loadPerf();
  if (t === "docaccess") loadDocGrants();
});

// ---------- 绩效考核 ----------
const perfTemplates = ref([]);
const perfResults = ref([]);
const perfBusy = ref(false);
const perfTplUser = ref(null);
const perfFileInput = ref(null);
const perfSearch = ref("");
const perfSelected = ref([]);
const perfPeriod = ref(new Date().toISOString().slice(0, 7));

const perfUsers = computed(() => users.value.filter((u) => u.is_active));
const perfPickUsers = computed(() => {
  const kw = perfSearch.value.trim().toLowerCase();
  return perfUsers.value.filter(
    (u) => !kw || `${u.display_name} ${u.username}`.toLowerCase().includes(kw)
  );
});

async function loadPerf() {
  try {
    perfTemplates.value = await api.admin.listPerfTemplates();
    perfResults.value = await api.admin.listPerfResults();
  } catch (e) {
    fail(e);
  }
}

async function uploadPerfTpl() {
  const file = perfFileInput.value?.files?.[0];
  if (!file) {
    toastRef.value?.showError("请先选择考核表文件");
    return;
  }
  perfBusy.value = true;
  try {
    const info = await api.admin.uploadPerfTemplate(perfTplUser.value, file);
    toastRef.value?.showInfo(`已上传 ${info.user_name} 的考核表：${info.original_name}`);
    if (perfFileInput.value) perfFileInput.value.value = "";
    await loadPerf();
  } catch (e) {
    fail(e);
  } finally {
    perfBusy.value = false;
  }
}

async function removePerfTpl(t) {
  if (!window.confirm(`确定删除 ${t.user_name} 的考核表模板「${t.original_name}」？`)) return;
  try {
    await api.admin.deletePerfTemplate(t.id);
    toastRef.value?.showInfo("考核表模板已删除");
    await loadPerf();
  } catch (e) {
    fail(e);
  }
}

async function generatePerf() {
  if (!perfSelected.value.length) return;
  if (!window.confirm(`确认为选中的 ${perfSelected.value.length} 名员工生成 ${perfPeriod.value} 的考核结果？\n同一员工同一周期重复生成会覆盖旧结果。`)) return;
  perfBusy.value = true;
  try {
    const list = await api.admin.generatePerf(perfSelected.value, perfPeriod.value);
    toastRef.value?.showInfo(`已生成 ${list.length} 名员工的考核结果（${perfPeriod.value}）`);
    perfSelected.value = [];
    await loadPerf();
  } catch (e) {
    fail(e);
  } finally {
    perfBusy.value = false;
  }
}

function exportPerfZip() {
  window.open(`/api/admin/performance/results/export?period=${encodeURIComponent(perfPeriod.value)}`, "_blank");
}

// ---------- 跨部门文档查询授权（管理员） ----------
const docGrants = ref([]);
const daBusy = ref(false);
const daGrantUser = ref(null);
const daGrantDept = ref(null);
const daGrantUntil = ref("");

async function loadDocGrants() {
  try {
    docGrants.value = await api.admin.listDocAccess();
  } catch (e) {
    fail(e);
  }
}

async function doGrant() {
  if (!window.confirm(`确认为该员工授权跨部门文档查询？\n有效期至 ${daGrantUntil.value}，到期自动失效。`)) return;
  daBusy.value = true;
  try {
    await api.admin.grantDocAccess(daGrantUser.value, daGrantDept.value, daGrantUntil.value);
    toastRef.value?.showInfo("授权成功，立即生效");
    daGrantUser.value = null;
    daGrantDept.value = null;
    daGrantUntil.value = "";
    await loadDocGrants();
  } catch (e) {
    fail(e);
  } finally {
    daBusy.value = false;
  }
}

async function decideGrant(g, action) {
  const isApprove = action === "approve";
  const msg = isApprove
    ? `批准 ${g.user_name} 查询「${g.department_name}」文档？\n有效期至 ${g.expires_at}（可接受该员工期望时长，之后可在下方撤销）。`
    : `${isApprove ? "批准" : "拒绝/撤销"} ${g.user_name} 对「${g.department_name}」的查询申请？`;
  if (!window.confirm(msg)) return;
  daBusy.value = true;
  try {
    await api.admin.decideDocAccess(g.id, action, isApprove ? g.expires_at : null);
    toastRef.value?.showInfo(isApprove ? "已批准并生效" : "已拒绝/撤销");
    await loadDocGrants();
  } catch (e) {
    fail(e);
  } finally {
    daBusy.value = false;
  }
}

// ---------- 文档批量删除（按上传人/日期） ----------
const bdUserId = ref(null);
const bdDate = ref("");
const bdStats = ref(null);
const bdBusy = ref(false);

async function queryBulk() {
  if (!bdUserId.value && !bdDate.value) {
    toastRef.value?.showError("请先选择上传人或上传日期");
    return;
  }
  bdBusy.value = true;
  try {
    bdStats.value = await api.admin.docBulkStats(bdUserId.value, bdDate.value);
  } catch (e) {
    fail(e);
  } finally {
    bdBusy.value = false;
  }
}

async function doBulkDelete() {
  if (!bdStats.value?.count) return;
  if (
    !window.confirm(
      `⚠️ 确认删除 ${bdStats.user_name} 在 ${bdStats.date} 上传的 ${bdStats.count} 份文档？\n` +
        `共 ${(bdStats.total_size / 1024 / 1024).toFixed(1)} MB，删除后不可恢复（员工需重新上传）。`
    )
  )
    return;
  bdBusy.value = true;
  try {
    const r = await api.admin.docBulkDelete(bdUserId.value, bdDate.value);
    toastRef.value?.showInfo(`已删除 ${r.deleted} 份文档，释放 ${r.freed_mb} MB`);
    bdStats.value = null;
    await loadDocGrants();
  } catch (e) {
    fail(e);
  } finally {
    bdBusy.value = false;
  }
}

async function fetchUserReport(mode) {
  reportBusy.value = true;
  try {
    if (mode === "history") {
      return await api.adminUserHistory(reportUserId.value);
    }
    const url =
      `/api/reports/daily?date=${encodeURIComponent(reportDay.value || todayStr())}` +
      `&user_id=${reportUserId.value}`;
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`获取失败（${resp.status}）`);
    return await resp.text();
  } finally {
    reportBusy.value = false;
  }
}

async function viewUserReport(mode) {
  reportMode.value = mode;
  try {
    reportText.value = await fetchUserReport(mode);
  } catch (e) {
    fail(e);
  }
}

function downloadText(filename, text) {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function downloadUserReport(mode) {
  try {
    const text = await fetchUserReport(mode);
    const u = users.value.find((x) => x.id === reportUserId.value);
    const name = u ? u.display_name || u.username : reportUserId.value;
    if (mode === "history") {
      downloadText(`工作日志汇总-${name}.md`, text);
    } else {
      downloadText(`工作日志-${reportDay.value || todayStr()}-${name}.md`, text);
    }
  } catch (e) {
    fail(e);
  }
}

const isAdmin = () => currentUser.value?.role === "admin";

function fail(e) {
  if (e instanceof ApiError && e.status === 401) return;
  toastRef.value?.showError(e.message || "操作失败");
}

async function loadAll() {
  stats.value = await api.admin.stats();
  users.value = await api.admin.listUsers();
  departments.value = await api.admin.listDepartments();
}
async function onLoggedIn(user) {
  currentUser.value = user;
  try {
    await loadAll();
    await loadActivity();
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) {
      toastRef.value?.showError("该账号不是管理员，无权访问管理后台");
    } else {
      fail(e);
    }
  }
}

function doLogout() {
  api.logout().catch(() => {}).finally(() => {
    currentUser.value = null;
  });
}

async function createUser() {
  try {
    await api.admin.createUser({ ...userForm, department_id: userForm.department_id || null });
    userForm.username = "";
    userForm.password = "";
    userForm.display_name = "";
    userForm.wecom_mobile = "";
    await loadAll();
  } catch (e) {
    fail(e);
  }
}

// ---------- 多部门分配（一人多部门，与负责人多选同款交互） ----------
const deptPicker = ref(null); // { uid: 用户ID, ids: 草稿部门集合 }
const deptMenuStyle = ref({});

function openDeptPicker(e, u) {
  const nameToId = new Map(departments.value.map(d => [d.name, d.id]));
  deptPicker.value = {
    uid: u.id,
    ids: (u.departments || []).map(n => nameToId.get(n)).filter(x => x != null),
  };
  const rect = e.currentTarget.getBoundingClientRect();
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - 240));
  const top = Math.min(rect.bottom + 4, window.innerHeight - 300);
  deptMenuStyle.value = { left: `${left}px`, top: `${top}px` };
}

function toggleDeptDraft(deptId, checked) {
  const ids = new Set(deptPicker.value.ids);
  if (checked) ids.add(deptId);
  else ids.delete(deptId);
  deptPicker.value.ids = [...ids];
}

async function confirmDeptPicker(u) {
  try {
    await api.admin.updateUser(u.id, { department_ids: [...deptPicker.value.ids] });
    deptPicker.value = null;
    await loadAll();
    toastRef.value?.showError(`已更新 ${u.display_name || u.username} 的所属部门`);
  } catch (e) {
    fail(e);
    await loadAll();
  }
}

function onDeptDocClick(e) {
  if (deptPicker.value && !e.target.closest(".dept-picker")) deptPicker.value = null;
}

function onDeptKeydown(e) {
  if (e.key === "Escape") deptPicker.value = null;
}

async function changeRole(u, role) {
  try {
    await api.admin.updateUser(u.id, { role });
    await loadAll();
  } catch (e) {
    fail(e);
    await loadAll();
  }
}

async function changeMobile(u, value) {
  try {
    await api.admin.updateUser(u.id, { wecom_mobile: value.trim() });
    toastRef.value?.showError(`已保存 ${u.display_name || u.username} 的企微手机号`);
  } catch (e) {
    fail(e);
    await loadAll();
  }
}

async function changeWorkStatus(u, workStatus) {
  const labels = { working: "在岗", leave: "请假", vacation: "休假", trip: "出差" };
  try {
    await api.admin.updateUser(u.id, { work_status: workStatus });
    await loadAll();
    toastRef.value?.showError(`已将 ${u.display_name || u.username} 设为：${labels[workStatus]}`);
  } catch (e) {
    fail(e);
    await loadAll();
  }
}

// changeDept 已由多部门 picker（openDeptPicker/confirmDeptPicker）替代

async function toggleActive(u) {
  try {
    await api.admin.updateUser(u.id, { is_active: !u.is_active });
    await loadAll();
  } catch (e) {
    fail(e);
    await loadAll();
  }
}

async function resetPw(u) {
  const pw = window.prompt(`为「${u.display_name}」设置新密码（≥6 位）：`);
  if (!pw) return;
  try {
    await api.admin.resetPassword(u.id, pw);
    toastRef.value?.showError(`已重置 ${u.username} 的密码`);
  } catch (e) {
    fail(e);
  }
}

async function removeUser(u) {
  if (!window.confirm(`确定删除账号「${u.username}」？`)) return;
  try {
    await api.admin.deleteUser(u.id);
    await loadAll();
  } catch (e) {
    fail(e);
  }
}

async function createDept() {
  try {
    await api.admin.createDepartment({ name: deptForm.name.trim(), description: deptForm.description.trim() });
    deptForm.name = "";
    deptForm.description = "";
    await loadAll();
  } catch (e) {
    fail(e);
  }
}

async function renameDept(d) {
  const name = window.prompt("新的部门名称：", d.name);
  if (!name || name === d.name) return;
  try {
    await api.admin.updateDepartment(d.id, { name: name.trim() });
    await loadAll();
  } catch (e) {
    fail(e);
  }
}

async function removeDept(d) {
  if (!window.confirm(`确定删除部门「${d.name}」？`)) return;
  try {
    await api.admin.deleteDepartment(d.id);
    await loadAll();
  } catch (e) {
    fail(e);
  }
}

function onUnauthorized() {
  currentUser.value = null;
}

// ---------- 操作日志（审计） ----------
const audit = reactive({ items: [], total: 0, page: 1, page_size: 20 });
const auditActions = ref([]);
const auditFilter = reactive({ user_id: 0, action: "", start_date: "", end_date: "" });
const auditLoaded = ref(false);
const totalPages = computed(() => Math.max(1, Math.ceil(audit.total / audit.page_size)));

async function queryAudit(page = 1) {
  try {
    const res = await api.admin.auditLogs({
      user_id: auditFilter.user_id || 0,
      action: auditFilter.action,
      start_date: auditFilter.start_date,
      end_date: auditFilter.end_date,
      page,
      page_size: 20,
    });
    audit.items = res.items;
    audit.total = res.total;
    audit.page = res.page;
    audit.page_size = res.page_size;
    auditLoaded.value = true;
  } catch (e) {
    fail(e);
  }
}

function resetAuditFilter() {
  auditFilter.user_id = 0;
  auditFilter.action = "";
  auditFilter.start_date = "";
  auditFilter.end_date = "";
  queryAudit(1);
}

function formatAuditTime(iso) {
  if (!iso) return "—";
  // 后端 UTC（Z 标记）→ 本地时间显示
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

watch(tab, (t) => {
  if (t === "audit" && !auditLoaded.value) {
    api.admin
      .auditActions()
      .then((list) => (auditActions.value = list))
      .catch(() => {});
    queryAudit(1);
  }
});

onMounted(async () => {
  window.addEventListener("og:unauthorized", onUnauthorized);
  window.addEventListener("click", onDeptDocClick);
  window.addEventListener("keydown", onDeptKeydown);
  try {
    const me = await api.me();
    if (me.role === "admin") {
      currentUser.value = me;
      await loadAll();
      await loadActivity(); // 进入页面即按默认统计窗口加载投入度数据
    }
  } catch {
    /* 未登录 → 登录页 */
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("og:unauthorized", onUnauthorized);
  window.removeEventListener("click", onDeptDocClick);
  window.removeEventListener("keydown", onDeptKeydown);
});
</script>

<style scoped>
.page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px;
}

.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 14px;
}

.brand .sub {
  margin: 2px 0 0;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.62);
}

.state {
  text-align: center;
  color: var(--muted);
  padding: 60px 0;
}

.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* ---------- 员工账号：分组展示工具栏与分组标题行 ---------- */
.users-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.users-toolbar select,
.users-toolbar .users-search {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel, #fff);
  font: inherit;
  font-size: 13px;
}

.users-toolbar .users-search {
  min-width: 220px;
}

.users-toolbar .users-count {
  color: var(--muted);
  font-size: 12.5px;
  margin-left: auto;
}

tr.group-row td {
  background: var(--primary-weak, rgba(47, 107, 255, 0.08));
  border-left: 4px solid var(--primary);
  padding: 8px 12px;
  font-weight: 600;
}

tr.group-row .group-name {
  margin-right: 10px;
}

tr.group-row .group-meta {
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
  margin-right: 8px;
}

tr.group-row .group-meta.warn {
  color: #b25e00;
}

td.empty-row {
  text-align: center;
  color: var(--muted);
  padding: 24px 0;
}

/* 绩效考核 */
.section-title {
  margin: 6px 0 0;
  font-size: 14px;
}

.perf-pick {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  max-height: 180px;
  overflow-y: auto;
}

.perf-pick .assignee-option {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  cursor: pointer;
}

.perf-overdue {
  color: #b00020;
  font-weight: 600;
}

a.mini {
  text-decoration: none;
  margin-right: 4px;
}

.stat-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
}

.stat-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
  text-align: center;
}

.stat-card b {
  display: block;
  font-size: 24px;
  color: var(--primary);
}

.stat-card span {
  color: var(--muted);
  font-size: 12px;
}

.inline-form {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.inline-form input,
.inline-form select {
  padding: 7px 10px;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 13px;
  overflow: hidden;
}

.data-table th {
  text-align: left;
  padding: 9px 10px;
  background: #eef2f7;
  border-bottom: 1px solid var(--border);
  font-weight: 500;
}

.data-table td {
  padding: 7px 10px;
  border-bottom: 1px solid #eef2f7;
}

.data-table tr.inactive td {
  color: var(--muted);
  text-decoration: line-through;
}

.data-table select {
  padding: 3px 6px;
}

.ops {
  display: flex;
  gap: 6px;
}

.flag-badge {
  background: #fdeaea;
  color: var(--danger);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  white-space: nowrap;
}

.ok-badge {
  background: #e5f5ec;
  color: var(--success);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
}

tr.flagged td {
  background: #fff7f7;
}

.muted {
  color: var(--muted);
  font-size: 11px;
}

.report-controls {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  flex-wrap: wrap;
}

.report-controls label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--muted);
}

.report-hint {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

.report-pre {
  background: #f7f9fc;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  font-family: ui-monospace, SFMono-Regular, Menlo, "PingFang SC", monospace;
  font-size: 12.5px;
  line-height: 1.7;
  max-height: 55vh;
  overflow: auto;
  white-space: pre-wrap;
  margin: 0;
}

button.mini.danger:hover {
  border-color: var(--danger);
  color: var(--danger);
}

/* 操作日志页签 */
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, "PingFang SC", monospace;
  font-size: 12px;
  white-space: nowrap;
}

.action-badge {
  display: inline-block;
  background: #e8f1fb;
  color: var(--primary);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  white-space: nowrap;
}

.action-badge.sensitive {
  background: #fdeaea;
  color: var(--danger);
  font-weight: 600;
}

.obj-cell,
.detail-cell {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-cell {
  color: var(--muted);
  font-size: 12.5px;
}

.pager {
  display: flex;
  align-items: center;
  gap: 10px;
}

.empty-tip {
  text-align: center;
  color: var(--muted);
  padding: 24px;
}

/* 部门多选 picker（与负责人多选同款交互） */
.dept-picker {
  position: relative;
  font-size: 12.5px;
}

.dept-picker .assignee-summary {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: none;
  border: none;
  cursor: pointer;
  color: inherit;
  padding: 3px 6px;
  border-radius: 4px;
}

.dept-picker .assignee-summary:hover {
  background: #eef5fd;
  color: var(--primary);
}

.assignee-menu {
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
</style>
