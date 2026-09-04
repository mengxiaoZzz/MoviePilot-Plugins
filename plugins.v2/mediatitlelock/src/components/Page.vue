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

const sourceItems = [
  { title: 'TMDB', value: 'themoviedb' },
  { title: '豆瓣', value: 'douban' },
  { title: 'Bangumi', value: 'bangumi' },
  { title: 'AniList', value: 'anilist' },
]
const operationItems = [
  { title: '新增或修改', value: 'upsert' },
  { title: '删除', value: 'delete' },
]
const headers = [
  { title: '媒体身份', key: 'identity', sortable: false },
  { title: '固定标题', key: 'canonical_title' },
  { title: '年份', key: 'year' },
  { title: '媒体根目录', key: 'root' },
  { title: '来源', key: 'origin_text' },
  { title: '更新时间', key: 'updated_at' },
  { title: '操作', key: 'actions', sortable: false },
]

const enabled = ref(false)
const bindings = ref([])
const total = ref(0)
const loading = ref(false)
const savingConfig = ref(false)
const submitting = ref(false)
const notice = reactive({ text: '', type: 'info' })
const form = reactive({
  operation: 'upsert',
  media_source: 'themoviedb',
  media_id: '',
  canonical_title: '',
  canonical_year: '',
  media_root_name: '',
})

let noticeTimer
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
  form.operation = 'upsert'
  form.media_id = ''
  form.canonical_title = ''
  form.canonical_year = ''
  form.media_root_name = ''
}

async function loadConfig() {
  const result = unwrapResponse(await props.api.get(`${pluginBase.value}/config`))
  if (!result?.success) throw new Error(result?.message || '配置加载失败')
  enabled.value = Boolean(result.data?.enabled)
}

async function loadBindings() {
  const result = unwrapResponse(await props.api.get(`${pluginBase.value}/bindings`))
  if (!result?.success) throw new Error(result?.message || '绑定列表加载失败')
  const items = result.data?.items || []
  bindings.value = items.map(item => ({
    ...item,
    identity: `${item.media_source} / ${item.media_id}`,
    year: item.canonical_year || '-',
    root: item.media_root_name || '-',
    origin_text: originText(item.origin),
  }))
  total.value = Number(result.data?.total || 0)
}

async function refreshPage() {
  loading.value = true
  try {
    await Promise.all([loadConfig(), loadBindings()])
  } catch (error) {
    showMessage(error?.message || '页面加载失败', 'error')
  } finally {
    loading.value = false
  }
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
  const mediaId = String(form.media_id || '').trim()
  const canonicalTitle = String(form.canonical_title || '').trim()
  if (!mediaId) {
    showMessage('来源内 ID 不能为空', 'warning')
    return
  }
  if (form.operation === 'upsert' && !canonicalTitle) {
    showMessage('固定标题不能为空', 'warning')
    return
  }

  submitting.value = true
  try {
    const deleting = form.operation === 'delete'
    const path = deleting ? 'bindings/delete' : 'bindings'
    const payload = deleting
      ? { media_source: form.media_source, media_id: mediaId }
      : {
          media_source: form.media_source,
          media_id: mediaId,
          canonical_title: canonicalTitle,
          canonical_year: String(form.canonical_year || '').trim(),
          media_root_name: String(form.media_root_name || '').trim(),
        }
    const result = unwrapResponse(await props.api.post(`${pluginBase.value}/${path}`, payload))
    if (!result?.success) throw new Error(result?.message || '操作失败')
    resetBindingForm()
    await loadBindings()
    showMessage(result.message || '操作成功', 'success')
  } catch (error) {
    showMessage(error?.message || '操作失败', 'error')
  } finally {
    submitting.value = false
  }
}

function editBinding(item) {
  const row = normalizeRow(item)
  form.operation = 'upsert'
  form.media_source = row.media_source || 'themoviedb'
  form.media_id = row.media_id || ''
  form.canonical_title = row.canonical_title || ''
  form.canonical_year = row.canonical_year || ''
  form.media_root_name = row.media_root_name || ''
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

      <VCard variant="outlined" class="mb-4">
        <VCardTitle class="text-subtitle-1">运行设置</VCardTitle>
        <VCardText>
          <div class="d-flex flex-wrap align-center ga-4">
            <VSwitch
              v-model="enabled"
              label="启用标题固定"
              color="success"
              hide-details
            />
            <VBtn
              color="primary"
              variant="flat"
              prepend-icon="mdi-content-save"
              :loading="savingConfig"
              @click="saveConfig"
            >
              保存设置
            </VBtn>
          </div>
        </VCardText>
      </VCard>

      <VCard variant="outlined" class="mb-4">
        <VCardTitle class="text-subtitle-1">人工维护绑定</VCardTitle>
        <VCardText>
          <VAlert type="info" variant="tonal" density="compact" class="mb-4">
            绑定键为媒体来源 + 来源内 ID。新增或修改时需填写固定标题；删除时只需填写媒体来源和来源内 ID。
          </VAlert>
          <VForm @submit.prevent="submitBinding">
            <VRow dense>
              <VCol cols="12" md="3">
                <VSelect
                  v-model="form.operation"
                  :items="operationItems"
                  label="操作"
                  variant="outlined"
                  density="compact"
                  hide-details="auto"
                />
              </VCol>
              <VCol cols="12" md="3">
                <VSelect
                  v-model="form.media_source"
                  :items="sourceItems"
                  label="媒体来源"
                  variant="outlined"
                  density="compact"
                  hide-details="auto"
                />
              </VCol>
              <VCol cols="12" md="6">
                <VTextField
                  v-model="form.media_id"
                  label="来源内 ID"
                  variant="outlined"
                  density="compact"
                  hide-details="auto"
                />
              </VCol>
              <VCol v-if="form.operation === 'upsert'" cols="12" md="6">
                <VTextField
                  v-model="form.canonical_title"
                  label="固定标题"
                  variant="outlined"
                  density="compact"
                  hide-details="auto"
                />
              </VCol>
              <VCol v-if="form.operation === 'upsert'" cols="12" md="2">
                <VTextField
                  v-model="form.canonical_year"
                  label="固定年份"
                  variant="outlined"
                  density="compact"
                  hide-details="auto"
                />
              </VCol>
              <VCol v-if="form.operation === 'upsert'" cols="12" md="4">
                <VTextField
                  v-model="form.media_root_name"
                  label="现有媒体根目录名（可选）"
                  variant="outlined"
                  density="compact"
                  hide-details="auto"
                />
              </VCol>
            </VRow>
            <div class="d-flex justify-end ga-2 mt-4">
              <VBtn variant="text" :disabled="submitting" @click="resetBindingForm">清空</VBtn>
              <VBtn
                type="submit"
                :color="form.operation === 'delete' ? 'error' : 'primary'"
                variant="flat"
                :prepend-icon="form.operation === 'delete' ? 'mdi-delete' : 'mdi-content-save'"
                :loading="submitting"
              >
                {{ form.operation === 'delete' ? '删除绑定' : '保存绑定' }}
              </VBtn>
            </div>
          </VForm>
        </VCardText>
      </VCard>

      <VCard variant="outlined">
        <VCardTitle class="text-subtitle-1 d-flex align-center">
          标题绑定
          <VChip size="small" variant="tonal" color="primary" class="ms-2">{{ total }}</VChip>
        </VCardTitle>
        <VDataTable
          :headers="headers"
          :items="bindings"
          :loading="loading"
          :items-per-page="25"
          density="compact"
        >
          <template #item.actions="{ item }">
            <div class="d-flex ga-1">
              <VBtn icon="mdi-pencil" size="small" variant="text" title="编辑" @click="editBinding(item)" />
              <VBtn
                icon="mdi-delete"
                size="small"
                variant="text"
                color="error"
                title="删除"
                @click="deleteBinding(item)"
              />
            </div>
          </template>
        </VDataTable>
      </VCard>
    </div>
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
  padding: 16px;
}
</style>
