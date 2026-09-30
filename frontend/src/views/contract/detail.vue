<template>
  <section class="page" data-module="contract-detail">
    <header class="page-head">
      <div>
        <h2>维保合同详情</h2>
        <p class="page-desc">履约状态与到期判定均取自后端落库结论，与列表页保持同一份口径。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="goBack">返回列表</button>
      </div>
    </header>

    <article v-if="entry" class="detail-card">
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">当前履约状态</span>
          <strong class="stat-value">{{ entry['合同状态'] ?? entry.status }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">到期判定结果</span>
          <strong class="stat-value">{{ entry['到期判定']?.['判定结果'] ?? '尚未判定' }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">到期判定日期</span>
          <strong class="stat-value">{{ entry['到期判定']?.['判定时间'] ?? '—' }}</strong>
        </article>
      </div>

      <table class="data-table">
        <tbody>
          <tr v-for="column in columns" :key="column">
            <th>{{ column }}</th>
            <td>{{ entry[column] ?? '—' }}</td>
          </tr>
          <tr>
            <th>判定依据日期</th>
            <td>{{ entry['到期判定']?.['判定依据日期'] ?? '—' }}</td>
          </tr>
          <tr>
            <th>判定来源</th>
            <td>{{ entry['到期判定']?.['来源'] ?? '—' }}</td>
          </tr>
        </tbody>
      </table>

      <div class="row-actions detail-actions">
        <button
          v-for="action in availableActions"
          :key="action.name"
          class="btn"
          :class="{ primary: action.name === '确认签订' }"
          type="button"
          :disabled="action.disabled"
          :title="action.disabled ? `当前为「${entry.status}」，不能${action.name}` : ''"
          @click="runAction(action.name)"
        >
          {{ action.name }}
        </button>
      </div>
      <p v-if="message" class="error-text">{{ message }}</p>
    </article>

    <p v-else-if="message" class="error-text">{{ message }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Entry = Record<string, string | number | null> & {
  status?: string
  到期判定?: { 判定结果: string; 判定依据日期: string; 判定时间: string; 来源: string }
}

const ENDPOINT = '/api/contract'
const LIST_PATH = '/contract'
// 详情只展示合同原始字段；合同金额与到期日期只读，动作不会改动它们。
const columns = ['合同编号', '服务单位', '维保设备', '合同金额', '服务期限', '签订人员', '到期日期', '合同状态']
const FORWARD_RULES: Record<string, string[]> = {
  待签订: ['确认签订'],
  履行中: ['标记到期', '终止合同'],
  已到期: [],
  已终止: [],
}

const route = useRoute()
const router = useRouter()
const entry = ref<Entry | null>(null)
const message = ref('')

const availableActions = computed(() => {
  const current = entry.value?.status ?? ''
  const allowed = new Set(FORWARD_RULES[current] ?? [])
  return ['确认签订', '标记到期', '终止合同'].map((name) => ({
    name,
    disabled: !allowed.has(name),
  }))
})

async function load() {
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/${route.params.id}`)
    if (response.status === 404) {
      message.value = `维保合同 ${route.params.id} 不存在或已归档`
      return
    }
    if (!response.ok) {
      throw new Error('维保合同详情读取失败')
    }
    entry.value = await response.json()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '维保合同详情读取失败'
  }
}

async function runAction(action: string) {
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/${route.params.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    message.value = payload.message ?? (response.ok ? '操作已生效' : '操作未生效')
    if (response.ok && payload.entry) {
      entry.value = payload.entry
    }
  } catch (error) {
    message.value = error instanceof Error ? error.message : '维保合同操作失败'
  }
}

function goBack() {
  // 返回时带上列表存下来的查询条件，回到上次过滤排序后的结果集。
  const query = (route.query.back as string) || sessionStorage.getItem('contract-list-query') || ''
  router.push(query ? `${LIST_PATH}?${query}` : LIST_PATH)
}

onMounted(load)
</script>
