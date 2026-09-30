<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常；在履合同数与维保合同模块取同一口径。</p>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th><th v-if="hasPerforming">在履合同数</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
          <td v-if="hasPerforming">{{ row.performing ?? '—' }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type ModuleRow = {
  name: string
  created: number
  pending: number
  abnormal: number
  performing?: number
}
type Overview = {
  cards: { label: string; value: number }[]
  modules: ModuleRow[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<ModuleRow[]>([])

const hasPerforming = computed(() => moduleRows.value.some((row) => typeof row.performing === 'number'))

onMounted(async () => {
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
  } catch {
    cards.value = [{ label: '业务模块', value: 0 }, { label: '今日新增', value: 0 }]
    moduleRows.value = [{ name: '维保合同', created: 0, pending: 0, abnormal: 0, performing: 0 }]
  }
})
</script>
