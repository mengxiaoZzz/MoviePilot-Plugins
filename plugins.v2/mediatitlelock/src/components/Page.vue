<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

const props = defineProps({
  api: {
    type: Object,
    default: () => ({}),
  },
  pluginId: {
    type: String,
    default: 'MediaTitleLock',
  },
})

const emit = defineEmits(['close'])
const frontendVersion = '1.0.7'
const frontendRevision = '20260907-pagination-diagnostics'

const sourceItems = [
  { title: 'TMDB', value: 'themoviedb' },
  { title: '豆瓣', value: 'douban' },
  { title: 'Bangumi', value: 'bangumi' },
  { title: 'AniList', value: 'anilist' },
]
const headers = [
  { title: '媒体身份', key: 'identity', sortable: false },
  { title: '固定标题', key: 'canonical_title' },
  { title: '年份', key: 'year' },
  { title: '分类', key: 'category' },
  { title: '来源', key: 'origin_text' },
  { title: '更新时间', key: 'updated_at' },
  { title: '操作', key: 'actions', sortable: false },
].map(header => ({ ...header, sortable: false }))

const enabled = ref(false)
const bindings = ref([])
const categories = ref([])
const total = ref(0)
const listLoading = ref(false)
const refreshing = ref(false)
const loading = computed(() => listLoading.value || refreshing.value)
const savingConfig = ref(false)
const submitting = ref(false)
const bindingDialog = ref(false)
const editing = ref(false)
const formError = ref('')
const page = ref(1)
const itemsPerPage = ref(25)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / itemsPerPage.value)))
const backendVersion = ref('')
const backendRevision = ref('')
const versionChecked = ref(false)
const versionWarning = computed(() => {
  if (!versionChecked.value) return ''
  if (!backendVersion.value || !backendRevision.value) return '后端未提供完整版本信息，无法核对；请确认插件后端已更新。'
  if (backendVersion.value !== frontendVersion || backendRevision.value !== frontendRevision) {
    return '前后端版本或界面构建不一致，请更新插件、重启 MP 并强制刷新浏览器。'
  }
  return ''
})
const categoryError = ref('')
const diagnosticsOpen = ref(false)
const diagnosticsLoading = ref(false)
const diagnosticsError = ref('')
const diagnostics = ref({ items: [], last_applied_at: '' })
const notice = reactive({ text: '', type: 'info' })
const form = reactive({
  media_source: 'themoviedb',
  media_id: '',
  canonical_title: '',
  canonical_year: '',
  media_category: '',
})
const filters = reactive({ tmdbid: '', title: '' })
const appliedFilters = reactive({ tmdbid: '', title: '' })

let noticeTimer
let bindingsRequestId = 0
const pluginBase = computed(() => `plugin/${props.pluginId || 'MediaTitleLock'}`)

function unwrapResponse(response) {
  if (response && typeof response === 'object' && 'success' in response) return response
  if (response?.data && typeof response.data === 'object' && 'success' in response.data) return response.data
  return response
}

function showMessage(text, type = 'info') {
  clearTimeout(noticeTimer)
  notice.text = text
  notice.type = type
  noticeTimer = setTimeout(() => {
    if (notice.text === text) notice.text = ''
  }, 4000)
}

function originText(origin) {
  return {
    automatic: '首次整理',
    manual: '人工维护',
    emby: '历史导入',
  }[origin] || origin || '-'
}

function normalizeRow(item) {
  return item?.raw || item || {}
}

function resetBindingForm() {
  formError.value = ''
  form.media_source = 'themoviedb'
  form.media_id = ''
  form.canonical_title = ''
  form.canonical_year = ''
  form.media_category = ''
}

function addBinding() {
  resetBindingForm()
  editing.value = false
  bindingDialog.value = true
}

async function loadConfig() {
  const result = unwrapResponse(await props.api.get(`${pluginBase.value}/config`))
  if (!result?.success) throw new Error(result?.message || '配置加载失败')
  enabled.value = Boolean(result.data?.enabled)
  backendVersion.value = result.data?.backend_version || ''
  backendRevision.value = result.data?.ui_revision || ''
  versionChecked.value = true
}

async function loadBindings(targetPage = page.value, search = appliedFilters, pageSize = itemsPerPage.value) {
  const requestId = ++bindingsRequestId
  listLoading.value = true
  const query = new URLSearchParams()
  const tmdbid = String(search.tmdbid || '').trim()
  const title = String(search.title || '').trim()
  query.set('page', targetPage)
  query.set('page_size', pageSize)
  if (tmdbid) query.set('tmdbid', tmdbid)
  if (title) query.set('title', title)
  try {
    const result = unwrapResponse(await props.api.get(`${pluginBase.value}/bindings?${query}`))
    if (requestId !== bindingsRequestId) return
    if (!result?.success) throw new Error(result?.message || '绑定列表加载失败')
    if (!result.data?.page || !result.data?.page_size) throw new Error('后端尚不支持按页查询，请更新插件后端后重试')
    bindings.value = (result.data.items || []).map(item => ({
      ...item,
      identity: `${item.media_source} / ${item.media_id}`,
      year: item.canonical_year || '-',
      category: item.media_category || '待补充',
      origin_text: originText(item.origin),
    }))
    total.value = Number(result.data.total || 0)
    page.value = Number(result.data.page)
    itemsPerPage.value = Number(result.data.page_size)
    categoryError.value = result.data.category_error || ''
    Object.assign(appliedFilters, { tmdbid, title })
  } catch (error) {
    if (requestId === bindingsRequestId) throw error
  } finally {
    if (requestId === bindingsRequestId) listLoading.value = false
  }
}

async function changePage(targetPage) {
  try {
    await loadBindings(targetPage)
  } catch (error) {
    showMessage(error?.message || '翻页失败，请重试', 'error')
  }
}

async function changePageSize(size) {
  try {
    await loadBindings(1, appliedFilters, size)
  } catch (error) {
    showMessage(error?.message || '切换每页条数失败', 'error')
  }
}

async function loadCategories() {
  const result = unwrapResponse(await props.api.get(`${pluginBase.value}/categories`))
  if (!result?.success) throw new Error(result?.message || '分类加载失败')
  categories.value = result.data?.items || []
}

async function refreshPage() {
  refreshing.value = true
  try {
    await Promise.all([loadConfig(), loadCategories(), loadBindings(), ...(diagnosticsOpen.value ? [loadDiagnostics()] : [])])
  } catch (error) {
    showMessage(error?.message || '页面加载失败', 'error')
  } finally {
    refreshing.value = false
  }
}

async function applyFilters() {
  try {
    await loadBindings(1, filters)
  } catch (error) {
    showMessage(error?.message || '筛选失败', 'error')
  }
}

async function loadDiagnostics() {
  diagnosticsLoading.value = true
  diagnosticsError.value = ''
  try {
    const result = unwrapResponse(await props.api.get(`${pluginBase.value}/diagnostics`))
    if (!result?.success) throw new Error(result?.message || '诊断加载失败')
    diagnostics.value = result.data || { items: [] }
  } catch (error) {
    diagnosticsError.value = error?.message || '诊断加载失败'
  } finally {
    diagnosticsLoading.value = false
  }
}

async function toggleDiagnostics() {
  diagnosticsOpen.value = !diagnosticsOpen.value
  if (diagnosticsOpen.value) await loadDiagnostics()
}

function stageText(stage) {
  return { download: '下载分类', rename: '标题渲染', transfer: '文件整理' }[stage] || stage
}

function statusColor(status) {
  return { applied: 'primary', success: 'success', fallback: 'warning', failed: 'error', error: 'error' }[status] || 'secondary'
}

async function clearFilters() {
  filters.tmdbid = ''
  filters.title = ''
  await applyFilters()
}

async function saveConfig() {
  savingConfig.value = true
  try {
    const result = unwrapResponse(
      await props.api.post(`${pluginBase.value}/config`, { enabled: enabled.value }),
    )
    if (!result?.success) throw new Error(result?.message || '配置保存失败')
    enabled.value = Boolean(result.data?.enabled)
    showMessage(result.message || '配置已保存', 'success')
  } catch (error) {
    showMessage(error?.message || '配置保存失败', 'error')
  } finally {
    savingConfig.value = false
  }
}

async function submitBinding() {
  formError.value = ''
  const mediaId = String(form.media_id || '').trim()
  const canonicalTitle = String(form.canonical_title || '').trim()
  const mediaCategory = String(form.media_category || '').trim()
  if (!mediaId) {
    formError.value = '来源内 ID 不能为空'
    return
  }
  if (!canonicalTitle) {
    formError.value = '固定标题不能为空'
    return
  }
  if (!mediaCategory) {
    formError.value = '分类不能为空'
    return
  }

  submitting.value = true
  try {
    const payload = {
      media_source: form.media_source,
      media_id: mediaId,
      canonical_title: canonicalTitle,
      canonical_year: String(form.canonical_year || '').trim(),
      media_category: mediaCategory,
    }
    const result = unwrapResponse(await props.api.post(`${pluginBase.value}/bindings`, payload))
    if (!result?.success) throw new Error(result?.message || '操作失败')
    bindingDialog.value = false
    resetBindingForm()
    showMessage(result.message || '标题绑定已保存', 'success')
    try {
      await loadBindings()
    } catch (error) {
      showMessage('绑定已保存，列表刷新失败，请点击刷新重试', 'warning')
    }
  } catch (error) {
    formError.value = error?.message || '保存失败'
  } finally {
    submitting.value = false
  }
}

function editBinding(item) {
  const row = normalizeRow(item)
  formError.value = ''
  editing.value = true
  form.media_source = row.media_source || 'themoviedb'
  form.media_id = row.media_id || ''
  form.canonical_title = row.canonical_title || ''
  form.canonical_year = row.canonical_year || ''
  form.media_category = row.media_category || ''
  bindingDialog.value = true
}

async function deleteBinding(item) {
  const row = normalizeRow(item)
  if (!window.confirm(`确认删除 ${row.media_source} / ${row.media_id} 的标题绑定？`)) return
  submitting.value = true
  try {
    const result = unwrapResponse(
      await props.api.post(`${pluginBase.value}/bindings/delete`, {
        media_source: row.media_source,
        media_id: row.media_id,
      }),
    )
    if (!result?.success) throw new Error(result?.message || '删除失败')
    await loadBindings()
    showMessage(result.message || '标题绑定已删除', 'success')
  } catch (error) {
    showMessage(error?.message || '删除失败', 'error')
  } finally {
    submitting.value = false
  }
}

onMounted(refreshPage)
onBeforeUnmount(() => clearTimeout(noticeTimer))
</script>

<template>
  <div class="mtl-page">
    <VToolbar density="comfortable" color="transparent">
      <VIcon icon="mdi-lock-outline" color="primary" class="ms-3 me-2" />
      <div class="text-h6">媒体标题固定</div>
      <VSpacer />
      <VBtn
        icon="mdi-refresh"
        variant="text"
        :loading="loading"
        title="刷新"
        @click="refreshPage"
      />
      <VBtn icon="mdi-close" variant="text" title="关闭" @click="emit('close')" />
    </VToolbar>
    <VDivider />

    <div class="mtl-body">
      <VAlert
        v-if="notice.text"
        :type="notice.type"
        variant="tonal"
        density="compact"
        closable
        class="mb-3"
      >
        {{ notice.text }}
      </VAlert>
      <VAlert v-if="versionWarning" type="warning" variant="tonal" density="compact" class="mb-3">
        {{ versionWarning }}
        <div class="text-caption">前端 {{ frontendVersion }} / {{ frontendRevision }}；后端 {{ backendVersion || '未知' }} / {{ backendRevision || '未知' }}</div>
      </VAlert>

      <VCard variant="outlined" class="mtl-settings mb-4">
        <VCardText class="mtl-settings-content">
          <div>
            <div class="text-subtitle-1 font-weight-medium">标题与分类固定</div>
            <div class="text-caption text-medium-emphasis">首次整理成功后自动记录，后续整理沿用绑定。</div>
          </div>
          <div class="d-flex align-center ga-3">
            <VSwitch
              v-model="enabled"
              label="启用"
              color="success"
              density="compact"
              hide-details
            />
            <VBtn
              color="primary"
              variant="tonal"
              size="small"
              :loading="savingConfig"
              @click="saveConfig"
            >
              保存设置
            </VBtn>
            <VBtn variant="text" size="small" prepend-icon="mdi-information-outline" :aria-expanded="diagnosticsOpen" @click="toggleDiagnostics">
              {{ diagnosticsOpen ? '收起诊断' : '运行诊断' }}
            </VBtn>
          </div>
        </VCardText>
      </VCard>

      <VCard v-if="diagnosticsOpen" variant="outlined" class="mtl-diagnostics mb-4">
        <div class="mtl-list-heading">
          <span class="text-subtitle-1 font-weight-medium">运行诊断</span>
          <VBtn variant="text" size="small" prepend-icon="mdi-refresh" :loading="diagnosticsLoading" @click="loadDiagnostics">刷新诊断</VBtn>
        </div>
        <VCardText class="pt-0">
          <div class="text-caption text-medium-emphasis mb-2">
            前端 {{ frontendVersion }} / {{ frontendRevision }}<br>
            后端 {{ backendVersion || '未知' }} / {{ backendRevision || '未知' }}<br>
            最近应用（含预览）：{{ diagnostics.last_applied_at || '本次运行暂无记录' }} · Emby 识别：未检测
          </div>
          <VAlert type="info" variant="tonal" density="compact" class="mb-3">
            分类固定及失效回退仅对新下载任务生效，不追溯修改旧下载任务或手动整理。
            文件整理成功不代表 Emby 已识别，本插件不查询 Emby 状态。
          </VAlert>
          <VAlert v-if="diagnosticsError" type="error" variant="tonal" density="compact" class="mb-3">{{ diagnosticsError }}</VAlert>
          <div class="text-caption text-medium-emphasis mb-2">本次运行最近 100 条，重载后清空；标题渲染记录可能来自预览。</div>
          <div class="mtl-diagnostic-list">
            <div v-for="(record, index) in diagnostics.items" :key="index" class="mtl-diagnostic-entry">
              <div class="d-flex align-center flex-wrap ga-2">
                <VChip size="x-small" variant="tonal" :color="statusColor(record.status)">{{ stageText(record.stage) }}</VChip>
                <span class="text-caption text-medium-emphasis">{{ record.timestamp }} · {{ record.media_source || '-' }} / {{ record.media_id || '-' }}</span>
              </div>
              <div class="text-body-2 mt-1">{{ record.message }}</div>
              <div v-if="record.original_title || record.effective_title" class="text-caption">标题：{{ record.original_title || '未提供' }} → {{ record.effective_title || '未提供' }}</div>
              <div v-if="record.original_category || record.effective_category" class="text-caption">分类：{{ record.original_category || '未提供' }} → {{ record.effective_category || '未识别分类，交由 MP 处理' }}</div>
            </div>
            <div v-if="!diagnostics.items?.length" class="text-body-2 text-medium-emphasis py-3">暂无执行记录</div>
          </div>
        </VCardText>
      </VCard>

      <VCard variant="outlined" class="mtl-bindings">
        <div class="mtl-list-heading">
          <div class="d-flex align-center ga-2">
            <span class="text-subtitle-1 font-weight-medium">标题绑定</span>
            <VChip size="small" variant="tonal" color="primary">{{ total }} 条</VChip>
          </div>
          <VBtn color="primary" variant="flat" prepend-icon="mdi-plus" :disabled="loading || submitting" @click="addBinding">
            新增绑定
          </VBtn>
        </div>
        <VCardText class="mtl-filters">
          <VRow dense align="center">
            <VCol cols="12" sm="4">
              <VTextField
                v-model="filters.tmdbid"
                label="TMDB ID"
                variant="outlined"
                density="compact"
                clearable
                hide-details
                @keyup.enter="applyFilters"
              />
            </VCol>
            <VCol cols="12" sm="4">
              <VTextField
                v-model="filters.title"
                label="标题"
                variant="outlined"
                density="compact"
                clearable
                hide-details
                @keyup.enter="applyFilters"
              />
            </VCol>
            <VCol cols="12" sm="4" class="d-flex ga-2">
              <VBtn color="primary" variant="tonal" :loading="loading" @click="applyFilters">
                筛选
              </VBtn>
              <VBtn variant="text" :disabled="loading" @click="clearFilters">重置</VBtn>
            </VCol>
          </VRow>
        </VCardText>
        <VAlert v-if="categoryError" type="warning" variant="tonal" density="compact" class="mx-5 mb-3">{{ categoryError }}</VAlert>
        <VDataTable
          :items-per-page="-1"
          :headers="headers"
          :items="bindings"
          :loading="loading"
          density="compact"
          fixed-header
          class="mtl-table"
          no-data-text="暂无匹配的绑定记录"
          loading-text="正在加载绑定记录…"
        >
          <template #item.canonical_title="{ item }">
            <span class="mtl-title">{{ normalizeRow(item).canonical_title }}</span>
          </template>
          <template #item.category="{ item }">
            <VChip size="small" variant="tonal" :color="normalizeRow(item).category_status === 'valid' ? 'primary' : 'warning'">
              {{ normalizeRow(item).category }}
            </VChip>
            <div v-if="normalizeRow(item).category_status === 'invalid'" class="text-caption text-warning">已失效 · 新下载沿用识别分类</div>
            <div v-else-if="normalizeRow(item).category_status === 'unknown'" class="text-caption text-medium-emphasis">暂无法校验</div>
          </template>
          <template #item.actions="{ item }">
            <div class="d-flex ga-1">
              <VBtn icon="mdi-pencil-outline" size="small" variant="text" color="primary" title="编辑" aria-label="编辑" :disabled="submitting" @click="editBinding(item)" />
              <VBtn
                icon="mdi-delete-outline"
                size="small"
                variant="text"
                color="error"
                title="删除"
                aria-label="删除"
                :disabled="submitting"
                @click="deleteBinding(item)"
              />
            </div>
          </template>
          <template #bottom>
            <div class="mtl-pagination">
              <div class="d-flex align-center ga-3">
                <span class="text-caption text-medium-emphasis">每页</span>
                <VSelect
                  :model-value="itemsPerPage"
                  :disabled="loading"
                  :items="[10, 25, 50, 100]"
                  aria-label="每页条数"
                  variant="outlined"
                  density="compact"
                  hide-details
                  class="mtl-page-size"
                  @update:model-value="changePageSize"
                />
                <span class="text-caption text-medium-emphasis">共 {{ total }} 条</span>
              </div>
              <div class="mtl-page-navigation">
                <span class="text-body-2" aria-live="polite">第 {{ page }} 页 / 共 {{ pageCount }} 页</span>
                <VPagination
                  :model-value="page"
                  :length="pageCount"
                  :total-visible="5"
                  :disabled="loading || bindings.length === 0"
                  density="compact"
                  rounded="lg"
                  active-color="primary"
                  aria-label="绑定列表分页"
                  previous-aria-label="上一页"
                  next-aria-label="下一页"
                  page-aria-label="第 {0} 页"
                  current-page-aria-label="第 {0} 页，当前页"
                  @update:model-value="changePage"
                />
              </div>
            </div>
          </template>
        </VDataTable>
      </VCard>
    </div>

    <VDialog v-model="bindingDialog" max-width="680" :persistent="submitting" scrollable>
      <VCard class="mtl-editor">
        <VCardTitle class="d-flex align-center justify-space-between">
          <span>{{ editing ? '编辑绑定' : '新增绑定' }}</span>
          <VBtn icon="mdi-close" variant="text" size="small" aria-label="关闭表单" :disabled="submitting" @click="bindingDialog = false" />
        </VCardTitle>
        <VDivider />
        <VCardText>
          <p class="text-body-2 text-medium-emphasis mb-5">按媒体来源与 ID 固定标题和分类。标记 * 的为必填项。</p>
          <VAlert v-if="formError" type="error" variant="tonal" density="compact" class="mb-4">{{ formError }}</VAlert>
          <VForm id="mtl-binding-form" :disabled="submitting" @submit.prevent="submitBinding">
            <VRow dense>
              <VCol cols="12" sm="4">
                <VSelect v-model="form.media_source" :items="sourceItems" label="媒体来源" variant="outlined" density="compact" hide-details="auto" />
              </VCol>
              <VCol cols="12" sm="8">
                <VTextField v-model="form.media_id" label="来源内 ID *" variant="outlined" density="compact" hide-details="auto" />
              </VCol>
              <VCol cols="12">
                <VTextField v-model="form.canonical_title" label="固定标题 *" variant="outlined" density="compact" hide-details="auto" />
              </VCol>
              <VCol cols="12" sm="4">
                <VTextField v-model="form.canonical_year" label="固定年份" placeholder="可不填" variant="outlined" density="compact" hide-details="auto" />
              </VCol>
              <VCol cols="12" sm="8">
                <VSelect
                  v-model="form.media_category"
                  :items="categories"
                  label="分类 *"
                  variant="outlined"
                  density="compact"
                  hide-details="auto"
                  no-data-text="MoviePilot 暂无可用分类"
                />
              </VCol>
            </VRow>
          </VForm>
        </VCardText>
        <VDivider />
        <VCardActions class="px-6 py-4">
          <VSpacer />
          <VBtn variant="text" :disabled="submitting" @click="bindingDialog = false">取消</VBtn>
          <VBtn type="submit" form="mtl-binding-form" color="primary" variant="flat" :loading="submitting">保存绑定</VBtn>
        </VCardActions>
      </VCard>
    </VDialog>
  </div>
</template>

<style scoped>
.mtl-page {
  display: flex;
  flex-direction: column;
  max-height: 82vh;
}

.mtl-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 20px;
}

.mtl-settings,
.mtl-bindings,
.mtl-diagnostics,
.mtl-editor {
  border-radius: 12px;
  border-color: rgba(var(--v-border-color), var(--v-border-opacity));
  background: rgb(var(--v-theme-surface));
}

.mtl-diagnostic-list {
  max-height: 280px;
  overflow-y: auto;
}

.mtl-diagnostic-entry {
  padding: 10px 0;
  border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  overflow-wrap: anywhere;
}

.mtl-settings-content,
.mtl-list-heading,
.mtl-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  padding: 16px 20px;
}

.mtl-filters {
  padding: 0 20px 20px;
}

.mtl-table :deep(th) {
  background: rgba(var(--v-theme-on-surface), 0.03);
  white-space: nowrap;
}

.mtl-table :deep(.v-table__wrapper) {
  max-height: 44vh;
}

.mtl-table :deep(td) {
  padding-block: 8px !important;
}

.mtl-title {
  font-weight: 500;
  overflow-wrap: anywhere;
}

.mtl-pagination {
  border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
}

.mtl-page-size {
  flex: 0 0 88px;
  width: 88px;
}

.mtl-page-navigation {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.mtl-editor :deep(.v-col) {
  padding-bottom: 12px;
}

@media (max-width: 600px) {
  .mtl-body {
    padding: 12px;
  }

  .mtl-settings-content,
  .mtl-list-heading,
  .mtl-pagination {
    padding: 12px;
  }

  .mtl-filters {
    padding: 0 12px 16px;
  }

  .mtl-page-navigation {
    width: 100%;
    justify-content: center;
    gap: 4px;
  }
}
</style>
