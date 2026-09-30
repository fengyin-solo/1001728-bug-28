<template>
  <section class="page" data-module="contract">
    <header class="page-head">
      <div>
        <h2>维保合同管理</h2>
        <p class="page-desc">围绕合同编号、服务单位、履约状态做登记、筛选与状态流转；筛选、排序与履约状态均以后端返回的命中集为准。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记维保合同</button>
        <button class="btn" type="button" @click="exportRows">导出维保合同清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="submitSearch">
      <label class="filter-item">
        <span>合同编号</span>
        <input v-model="query.keyword" placeholder="按合同编号检索" />
      </label>
      <label class="filter-item">
        <span>服务单位</span>
        <input v-model="query.serviceUnit" placeholder="按服务单位过滤" />
      </label>
      <label class="filter-item">
        <span>履约状态</span>
        <select v-model="query.status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <label class="filter-item filter-check">
        <input v-model="query.expiring" type="checkbox" />
        <span>仅看30天内到期</span>
      </label>
      <label class="filter-item">
        <span>到期日期排序</span>
        <select v-model="query.sortMode">
          <option value="none">默认排序</option>
          <option value="asc">到期日期升序</option>
          <option value="desc">到期日期降序</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <RouterLink v-if="column === '合同编号'" class="link" :to="{ name: 'contract-detail', params: { id: row.id } }">
              {{ row[column] ?? '—' }}
            </RouterLink>
            <span v-else :class="{ 'status-tag': column === '合同状态' }">{{ row[column] ?? '—' }}</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">当前条件下没有维保合同记录，请调整筛选条件</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条维保合同记录，第 {{ query.page }} / {{ pageCount }} 页</span>
      <span class="pager">
        <button class="btn" type="button" :disabled="query.page <= 1" @click="gotoPage(query.page - 1)">上一页</button>
        <button class="btn" type="button" :disabled="query.page >= pageCount" @click="gotoPage(query.page + 1)">下一页</button>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useContractStore, type ContractListQuery } from '@/stores/contract'

type Row = Record<string, string | number | null>
type Summary = { performingCount: number; upcomingCount: number; totalAmount: number }

const ENDPOINT = '/api/contract'
const PAGE_SIZE = 20
const columns = ['合同编号', '服务单位', '维保设备', '合同金额', '服务期限', '签订人员', '到期日期', '合同状态']
const statuses = ['待签订', '履行中', '已到期', '已终止']

const store = useContractStore()
// 进入页面即恢复上次离开时的条件（含从详情返回）。
const query = ref<ContractListQuery>({ ...store.query })

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const summary = ref<Summary>({ performingCount: 0, upcomingCount: 0, totalAmount: 0 })

const stats = computed(() => [
  { label: '在履合同', value: summary.value.performingCount },
  { label: '30天内到期合同', value: summary.value.upcomingCount },
  { label: '合同总金额（万元）', value: summary.value.totalAmount },
])

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

/** 按当前履约状态只给出能推进的动作，非法推进一律由后端再挡一次并回传原因。 */
function availableActions(row: Row): string[] {
  switch (row['合同状态']) {
    case '待签订':
      return ['确认签订', '终止合同']
    case '履行中':
      return ['标记到期', '终止合同']
    default:
      return []
  }
}

function persistQuery() {
  store.save(query.value)
}

function buildParams(includePage = true): URLSearchParams {
  const params = new URLSearchParams()
  if (query.value.keyword.trim()) params.set('keyword', query.value.keyword.trim())
  if (query.value.serviceUnit.trim()) params.set('service_unit', query.value.serviceUnit.trim())
  if (query.value.status) params.set('status', query.value.status)
  if (query.value.expiring) params.set('expiring', 'true')
  if (query.value.sortMode !== 'none') {
    params.set('sort_expiry', 'true')
    params.set('order', query.value.sortMode)
  }
  if (includePage) {
    params.set('page', String(query.value.page))
    params.set('size', String(PAGE_SIZE))
  }
  return params
}

function submitSearch() {
  query.value.page = 1
  void reload()
}

function resetFilters() {
  query.value = { keyword: '', serviceUnit: '', status: '', expiring: false, sortMode: 'none', page: 1 }
  void reload()
}

function gotoPage(page: number) {
  query.value.page = Math.min(Math.max(1, page), pageCount.value)
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export?${buildParams(false).toString()}`, '_blank')
}

function openCreate() {
  errorMessage.value = '维保合同登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      // 回退/跳档等被后端挡下时，直接展示后端给出的当前状态说明。
      throw new Error(payload.message || '维保合同动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '维保合同操作失败'
  }
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (response.ok) {
      summary.value = await response.json()
    }
  } catch {
    // 指标加载失败不影响列表，页脚另有错误提示通道。
  }
}

async function reload() {
  errorMessage.value = ''
  persistQuery()
  try {
    const response = await request(`${ENDPOINT}?${buildParams().toString()}`)
    if (!response.ok) {
      throw new Error('维保合同列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (query.value.page > pageCount.value) {
      query.value.page = pageCount.value
      persistQuery()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '维保合同列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>

<style scoped>
.filter-check {
  display: flex;
  align-items: center;
  gap: 6px;
}
.filter-check input {
  margin: 0;
}
.pager {
  display: flex;
  gap: 8px;
}
.pager .btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.status-tag {
  white-space: nowrap;
}
</style>
