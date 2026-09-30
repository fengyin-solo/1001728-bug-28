import { defineStore } from 'pinia'

/** 维保合同列表的查询条件：点进详情再返回时，仍保留上一次的筛选与排序。 */
export interface ContractListQuery {
  keyword: string
  serviceUnit: string
  status: string
  expiring: boolean
  sortMode: 'none' | 'asc' | 'desc'
  page: number
}

const STORAGE_KEY = 'contract:list-query'

const DEFAULT_QUERY: ContractListQuery = {
  keyword: '',
  serviceUnit: '',
  status: '',
  expiring: false,
  sortMode: 'none',
  page: 1,
}

function load(): ContractListQuery {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_QUERY }
    return { ...DEFAULT_QUERY, ...(JSON.parse(raw) as Partial<ContractListQuery>) }
  } catch {
    return { ...DEFAULT_QUERY }
  }
}

export const useContractStore = defineStore('contract', {
  state: () => ({
    query: load(),
  }),
  actions: {
    save(query: ContractListQuery) {
      this.query = { ...query }
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(this.query))
      } catch {
        // 隐私模式等场景写不进 sessionStorage 时，内存里仍能保留本次条件。
      }
    },
    reset() {
      this.save({ ...DEFAULT_QUERY })
    },
  },
})
