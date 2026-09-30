<template>
  <section class="page" data-module="contract">
    <header class="page-head">
      <div>
        <h2>维保合同管理</h2>
        <p class="page-desc">筛选、排序与履约状态全部以后端返回的命中集为准，列表、详情与运营概览同一份口径。</p>
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

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>合同编号</span>
        <input v-model="filters.keyword" placeholder="按合同编号检索" />
      </label>
      <label class="filter-item">
        <span>服务单位</span>
        <input v-model="filters.unit" placeholder="按服务单位检索" />
      </label>
      <label class="filter-item">
        <span>维保设备</span>
        <input v-model="filters.device" placeholder="按维保设备检索" />
      </label>
      <label class="filter-item">
        <span>合同状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="option in statuses" :key="option" :value="option">{{ option }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>排序字段</span>
        <select v-model="filters.sortBy">
          <option value="">默认顺序</option>
          <option value="到期日期">到期日期</option>
          <option value="合同金额">合同金额</option>
        </select>
      </label>
      <label class="filter-item">
        <span>排序方向</span>
        <select v-model="filters.order">
          <option value="asc">升序</option>
          <option value="desc">降序</option>
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
            <button
              v-if="column === '合同编号'"
              class="link"
              type="button"
              :title="`查看 ${row[column]} 详情`"
              @click="openDetail(row)"
            >
              {{ row[column] ?? '—' }}
            </button>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <template v-if="actionsFor(row).length">
              <button
                v-for="action in actionsFor(row)"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="muted-text">无可推进动作</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">当前条件下没有命中的维保合同</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条维保合同记录（与筛选命中数一致）</span>
      <span class="pager">
        <button class="btn ghost" type="button" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
        第 {{ page }} 页 / 每页 {{ size }} 条
        <button
          class="btn ghost"
          type="button"
          :disabled="page * size >= total"
          @click="changePage(page + 1)"
        >下一页</button>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null> & { status?: string }

type Filters = {
  keyword: string
  unit: string
  device: string
  status: string
  sortBy: string
  order: string
}

const ENDPOINT = '/api/contract'
const columns = ['合同编号', '服务单位', '维保设备', '合同金额', '服务期限', '签订人员', '到期日期', '合同状态']
const statuses = ['待签订', '履行中', '已到期', '已终止']
// 履约状态单向推进：每个当前状态只暴露允许的动作，回退、跳档在按钮层即不可点。
const FORWARD_RULES: Record<string, string[]> = {
  待签订: ['确认签订'],
  履行中: ['标记到期', '终止合同'],
  已到期: [],
  已终止: [],
}
const DEFAULT_STATS = [
  { label: '履行中合同', value: 0 },
  { label: '即将到期合同', value: 0 },
  { label: '合同总金额', value: 0 },
]

const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const size = 20
const errorMessage = ref('')
const stats = ref(DEFAULT_STATS)
const filters = ref<Filters>({
  keyword: '',
  unit: '',
  device: '',
  status: '',
  sortBy: '',
  order: 'asc',
})

function actionsFor(row: Row): string[] {
  return FORWARD_RULES[row.status ?? ''] ?? []
}

// 把页面条件收敛成一份既用于请求后端、又用于地址栏/本地留存的查询串，三处同源。
function buildQuery(includePage = true): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.value.keyword.trim()) params.set('keyword', filters.value.keyword.trim())
  if (filters.value.unit.trim()) params.set('unit', filters.value.unit.trim())
  if (filters.value.device.trim()) params.set('device', filters.value.device.trim())
  if (filters.value.status) params.set('status', filters.value.status)
  if (filters.value.sortBy) {
    params.set('sort_by', filters.value.sortBy)
    params.set('order', filters.value.order || 'asc')
  }
  if (includePage) {
    params.set('page', String(page.value))
    params.set('size', String(size))
  }
  return params
}

function restoreFromRoute() {
  // 从详情返回时用地址栏里的条件还原；直接进入时兼容上一次会话留存的条件。
  const source = route.fullPath.includes('?')
    ? new URLSearchParams(route.fullPath.split('?')[1])
    : new URLSearchParams(sessionStorage.getItem('contract-list-query') || '')
  filters.value = {
    keyword: source.get('keyword') ?? '',
    unit: source.get('unit') ?? '',
    device: source.get('device') ?? '',
    status: source.get('status') ?? '',
    sortBy: source.get('sort_by') ?? '',
    order: source.get('order') ?? 'asc',
  }
  const restoredPage = Number(source.get('page'))
  page.value = Number.isFinite(restoredPage) && restoredPage > 0 ? restoredPage : 1
}

function persistQuery() {
  const queryString = buildQuery().toString()
  sessionStorage.setItem('contract-list-query', queryString)
  // replace 而不是 push：查询动作不堆积历史，返回详情时仍能拿到完整条件。
  void router.replace({ path: route.path, query: Object.fromEntries(buildQuery()) })
}

function applyFilters() {
  page.value = 1
  void reload()
}

function changePage(next: number) {
  page.value = next
  void reload()
}

function resetFilters() {
  filters.value = { keyword: '', unit: '', device: '', status: '', sortBy: '', order: 'asc' }
  page.value = 1
  void reload()
}

function exportRows() {
  const query = buildQuery(false).toString()
  window.open(`${ENDPOINT}/export${query ? `?${query}` : ''}`, '_blank')
}

function openCreate() {
  errorMessage.value = '维保合同登记入口尚未接入审批流'
}

function openDetail(row: Row) {
  // 把当前条件编码进 back，详情返回时原样还原过滤、排序与分页。
  const back = encodeURIComponent(buildQuery().toString())
  void router.push(`/contract/${row.id}?back=${back}`)
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      // 回退/跳档/重复下发被后端挡下时，直接展示后端说明的当前状态原因。
      errorMessage.value = payload.message || '维保合同动作未生效'
      return
    }
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '维保合同操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  persistQuery()
  try {
    const response = await request(`${ENDPOINT}?${buildQuery().toString()}`)
    if (!response.ok) {
      throw new Error('维保合同列表读取失败')
    }
    const payload = await response.json()
    // 命中集与命中数都以后端为准，前端不再自行过滤或推算履约状态。
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '维保合同列表读取失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats/summary`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    stats.value = [
      { label: '履行中合同', value: payload.active ?? 0 },
      { label: '即将到期合同', value: payload.upcoming ?? 0 },
      { label: '合同总金额', value: payload.total_amount ?? 0 },
    ]
  } catch {
    // 统计卡片不影响列表主流程，失败时保留初始 0 值。
  }
}

onMounted(() => {
  restoreFromRoute()
  void reload()
  void loadStats()
})
</script>
