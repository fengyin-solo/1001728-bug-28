<template>
  <section class="page" data-module="contract-detail">
    <header class="page-head">
      <div>
        <h2>维保合同详情</h2>
        <p class="page-desc">详情与列表取自后端同一份履约状态与到期判定，返回列表时保留上次筛选条件。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" :to="{ name: 'contract' }">返回列表</RouterLink>
      </div>
    </header>

    <p v-if="errorMessage" class="error-text detail-error">{{ errorMessage }}</p>

    <template v-if="entry">
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">当前履约状态</span>
          <strong class="stat-value">{{ statusText }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">在履合同数（全平台）</span>
          <strong class="stat-value">{{ summary.performingCount }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">到期判定时间</span>
          <strong class="stat-value stat-small">{{ entry.到期判定?.判定时间 ?? '尚未判定' }}</strong>
        </article>
      </div>

      <table class="data-table detail-table">
        <tbody>
          <tr v-for="field in detailFields" :key="field">
            <th>{{ field }}</th>
            <td>{{ entry[field] ?? '—' }}</td>
          </tr>
          <tr>
            <th>到期判定来源</th>
            <td>{{ entry.到期判定?.来源 ?? '—' }}{{ entry.到期判定?.备注 ? `（${entry.到期判定.备注}）` : '' }}</td>
          </tr>
        </tbody>
      </table>

      <div class="detail-actions">
        <button
          v-for="action in availableActions"
          :key="action"
          class="btn"
          :class="{ primary: action !== '终止合同' }"
          type="button"
          @click="runAction(action)"
        >
          {{ action }}
        </button>
        <span v-if="actionMessage" :class="actionOk ? '' : 'error-text'">{{ actionMessage }}</span>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { request } from '@/api/client'

type Entry = Record<string, string | number | null> & {
  合同状态?: string
  到期判定?: { 到期日期: string | null; 判定时间: string; 来源: string; 备注: string } | null
}
type Summary = { performingCount: number; upcomingCount: number; totalAmount: number }

const route = useRoute()
const ENDPOINT = `/api/contract/${String(route.params.id)}`

const detailFields = ['合同编号', '服务单位', '维保设备', '合同金额', '服务期限', '签订人员', '到期日期', '合同状态']

const entry = ref<Entry | null>(null)
const summary = ref<Summary>({ performingCount: 0, upcomingCount: 0, totalAmount: 0 })
const errorMessage = ref('')
const actionMessage = ref('')
const actionOk = ref(true)

const statusText = computed(() => entry.value?.['合同状态'] ?? '—')
const availableActions = computed<string[]>(() => {
  switch (entry.value?.['合同状态']) {
    case '待签订':
      return ['确认签订', '终止合同']
    case '履行中':
      return ['标记到期', '终止合同']
    default:
      return []
  }
})

async function loadSummary() {
  try {
    const response = await request('/api/contract/summary')
    if (response.ok) {
      summary.value = await response.json()
    }
  } catch {
    // 指标缺失不阻塞详情阅读。
  }
}

async function loadEntry() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT)
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new Error(payload?.detail || '维保合同详情读取失败')
    }
    entry.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '维保合同详情读取失败'
  }
}

async function runAction(action: string) {
  actionMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      actionOk.value = false
      actionMessage.value = payload.message || '维保合同动作未生效，请稍后重试'
      return
    }
    actionOk.value = true
    actionMessage.value = payload.message
    await Promise.all([loadEntry(), loadSummary()])
  } catch (error) {
    actionOk.value = false
    actionMessage.value = error instanceof Error ? error.message : '维保合同操作失败'
  }
}

onMounted(() => {
  void loadEntry()
  void loadSummary()
})
</script>

<style scoped>
.detail-error {
  margin: 8px 0;
}
.detail-table th {
  width: 160px;
  background: #f8fafc;
}
.stat-small {
  font-size: 14px;
}
.detail-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 14px;
  font-size: 13px;
}
</style>
