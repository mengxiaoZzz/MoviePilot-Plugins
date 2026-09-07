import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,withCtx:_withCtx,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,renderList:_renderList,Fragment:_Fragment,createElementBlock:_createElementBlock,withKeys:_withKeys,unref:_unref,withModifiers:_withModifiers} = await importShared('vue');


const _hoisted_1 = { class: "mtl-page" };
const _hoisted_2 = { class: "mtl-body" };
const _hoisted_3 = { class: "text-caption" };
const _hoisted_4 = { class: "d-flex align-center ga-3" };
const _hoisted_5 = { class: "mtl-list-heading" };
const _hoisted_6 = { class: "text-caption text-medium-emphasis mb-2" };
const _hoisted_7 = { class: "mtl-diagnostic-list" };
const _hoisted_8 = { class: "d-flex align-center flex-wrap ga-2" };
const _hoisted_9 = { class: "text-caption text-medium-emphasis" };
const _hoisted_10 = { class: "text-body-2 mt-1" };
const _hoisted_11 = {
  key: 0,
  class: "text-caption"
};
const _hoisted_12 = {
  key: 1,
  class: "text-caption"
};
const _hoisted_13 = {
  key: 0,
  class: "text-body-2 text-medium-emphasis py-3"
};
const _hoisted_14 = { class: "mtl-list-heading" };
const _hoisted_15 = { class: "d-flex align-center ga-2" };
const _hoisted_16 = { class: "mtl-title" };
const _hoisted_17 = {
  key: 0,
  class: "text-caption text-warning"
};
const _hoisted_18 = {
  key: 1,
  class: "text-caption text-medium-emphasis"
};
const _hoisted_19 = { class: "d-flex ga-1" };
const _hoisted_20 = { class: "mtl-pagination" };
const _hoisted_21 = { class: "d-flex align-center ga-3" };
const _hoisted_22 = { class: "text-caption text-medium-emphasis" };
const _hoisted_23 = { class: "mtl-page-navigation" };
const _hoisted_24 = {
  class: "text-body-2",
  "aria-live": "polite"
};

const {computed,onBeforeUnmount,onMounted,reactive,ref} = await importShared('vue');


const frontendVersion = '1.0.7';
const frontendRevision = '20260907-pagination-diagnostics';


const _sfc_main = {
  __name: 'Page',
  props: {
  api: {
    type: Object,
    default: () => ({}),
  },
  pluginId: {
    type: String,
    default: 'MediaTitleLock',
  },
},
  emits: ['close'],
  setup(__props, { emit: __emit }) {

const props = __props;

const emit = __emit;
const sourceItems = [
  { title: 'TMDB', value: 'themoviedb' },
  { title: '豆瓣', value: 'douban' },
  { title: 'Bangumi', value: 'bangumi' },
  { title: 'AniList', value: 'anilist' },
];
const headers = [
  { title: '媒体身份', key: 'identity', sortable: false },
  { title: '固定标题', key: 'canonical_title' },
  { title: '年份', key: 'year' },
  { title: '分类', key: 'category' },
  { title: '来源', key: 'origin_text' },
  { title: '更新时间', key: 'updated_at' },
  { title: '操作', key: 'actions', sortable: false },
].map(header => ({ ...header, sortable: false }));

const enabled = ref(false);
const bindings = ref([]);
const categories = ref([]);
const total = ref(0);
const listLoading = ref(false);
const refreshing = ref(false);
const loading = computed(() => listLoading.value || refreshing.value);
const savingConfig = ref(false);
const submitting = ref(false);
const bindingDialog = ref(false);
const editing = ref(false);
const formError = ref('');
const page = ref(1);
const itemsPerPage = ref(25);
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / itemsPerPage.value)));
const backendVersion = ref('');
const backendRevision = ref('');
const versionChecked = ref(false);
const versionWarning = computed(() => {
  if (!versionChecked.value) return ''
  if (!backendVersion.value || !backendRevision.value) return '后端未提供完整版本信息，无法核对；请确认插件后端已更新。'
  if (backendVersion.value !== frontendVersion || backendRevision.value !== frontendRevision) {
    return '前后端版本或界面构建不一致，请更新插件、重启 MP 并强制刷新浏览器。'
  }
  return ''
});
const categoryError = ref('');
const diagnosticsOpen = ref(false);
const diagnosticsLoading = ref(false);
const diagnosticsError = ref('');
const diagnostics = ref({ items: [], last_applied_at: '' });
const notice = reactive({ text: '', type: 'info' });
const form = reactive({
  media_source: 'themoviedb',
  media_id: '',
  canonical_title: '',
  canonical_year: '',
  media_category: '',
});
const filters = reactive({ tmdbid: '', title: '' });
const appliedFilters = reactive({ tmdbid: '', title: '' });

let noticeTimer;
let bindingsRequestId = 0;
const pluginBase = computed(() => `plugin/${props.pluginId || 'MediaTitleLock'}`);

function unwrapResponse(response) {
  if (response && typeof response === 'object' && 'success' in response) return response
  if (response?.data && typeof response.data === 'object' && 'success' in response.data) return response.data
  return response
}

function showMessage(text, type = 'info') {
  clearTimeout(noticeTimer);
  notice.text = text;
  notice.type = type;
  noticeTimer = setTimeout(() => {
    if (notice.text === text) notice.text = '';
  }, 4000);
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
  formError.value = '';
  form.media_source = 'themoviedb';
  form.media_id = '';
  form.canonical_title = '';
  form.canonical_year = '';
  form.media_category = '';
}

function addBinding() {
  resetBindingForm();
  editing.value = false;
  bindingDialog.value = true;
}

async function loadConfig() {
  const result = unwrapResponse(await props.api.get(`${pluginBase.value}/config`));
  if (!result?.success) throw new Error(result?.message || '配置加载失败')
  enabled.value = Boolean(result.data?.enabled);
  backendVersion.value = result.data?.backend_version || '';
  backendRevision.value = result.data?.ui_revision || '';
  versionChecked.value = true;
}

async function loadBindings(targetPage = page.value, search = appliedFilters, pageSize = itemsPerPage.value) {
  const requestId = ++bindingsRequestId;
  listLoading.value = true;
  const query = new URLSearchParams();
  const tmdbid = String(search.tmdbid || '').trim();
  const title = String(search.title || '').trim();
  query.set('page', targetPage);
  query.set('page_size', pageSize);
  if (tmdbid) query.set('tmdbid', tmdbid);
  if (title) query.set('title', title);
  try {
    const result = unwrapResponse(await props.api.get(`${pluginBase.value}/bindings?${query}`));
    if (requestId !== bindingsRequestId) return
    if (!result?.success) throw new Error(result?.message || '绑定列表加载失败')
    if (!result.data?.page || !result.data?.page_size) throw new Error('后端尚不支持按页查询，请更新插件后端后重试')
    bindings.value = (result.data.items || []).map(item => ({
      ...item,
      identity: `${item.media_source} / ${item.media_id}`,
      year: item.canonical_year || '-',
      category: item.media_category || '待补充',
      origin_text: originText(item.origin),
    }));
    total.value = Number(result.data.total || 0);
    page.value = Number(result.data.page);
    itemsPerPage.value = Number(result.data.page_size);
    categoryError.value = result.data.category_error || '';
    Object.assign(appliedFilters, { tmdbid, title });
  } catch (error) {
    if (requestId === bindingsRequestId) throw error
  } finally {
    if (requestId === bindingsRequestId) listLoading.value = false;
  }
}

async function changePage(targetPage) {
  try {
    await loadBindings(targetPage);
  } catch (error) {
    showMessage(error?.message || '翻页失败，请重试', 'error');
  }
}

async function changePageSize(size) {
  try {
    await loadBindings(1, appliedFilters, size);
  } catch (error) {
    showMessage(error?.message || '切换每页条数失败', 'error');
  }
}

async function loadCategories() {
  const result = unwrapResponse(await props.api.get(`${pluginBase.value}/categories`));
  if (!result?.success) throw new Error(result?.message || '分类加载失败')
  categories.value = result.data?.items || [];
}

async function refreshPage() {
  refreshing.value = true;
  try {
    await Promise.all([loadConfig(), loadCategories(), loadBindings(), ...(diagnosticsOpen.value ? [loadDiagnostics()] : [])]);
  } catch (error) {
    showMessage(error?.message || '页面加载失败', 'error');
  } finally {
    refreshing.value = false;
  }
}

async function applyFilters() {
  try {
    await loadBindings(1, filters);
  } catch (error) {
    showMessage(error?.message || '筛选失败', 'error');
  }
}

async function loadDiagnostics() {
  diagnosticsLoading.value = true;
  diagnosticsError.value = '';
  try {
    const result = unwrapResponse(await props.api.get(`${pluginBase.value}/diagnostics`));
    if (!result?.success) throw new Error(result?.message || '诊断加载失败')
    diagnostics.value = result.data || { items: [] };
  } catch (error) {
    diagnosticsError.value = error?.message || '诊断加载失败';
  } finally {
    diagnosticsLoading.value = false;
  }
}

async function toggleDiagnostics() {
  diagnosticsOpen.value = !diagnosticsOpen.value;
  if (diagnosticsOpen.value) await loadDiagnostics();
}

function stageText(stage) {
  return { download: '下载分类', rename: '标题渲染', transfer: '文件整理' }[stage] || stage
}

function statusColor(status) {
  return { applied: 'primary', success: 'success', fallback: 'warning', failed: 'error', error: 'error' }[status] || 'secondary'
}

async function clearFilters() {
  filters.tmdbid = '';
  filters.title = '';
  await applyFilters();
}

async function saveConfig() {
  savingConfig.value = true;
  try {
    const result = unwrapResponse(
      await props.api.post(`${pluginBase.value}/config`, { enabled: enabled.value }),
    );
    if (!result?.success) throw new Error(result?.message || '配置保存失败')
    enabled.value = Boolean(result.data?.enabled);
    showMessage(result.message || '配置已保存', 'success');
  } catch (error) {
    showMessage(error?.message || '配置保存失败', 'error');
  } finally {
    savingConfig.value = false;
  }
}

async function submitBinding() {
  formError.value = '';
  const mediaId = String(form.media_id || '').trim();
  const canonicalTitle = String(form.canonical_title || '').trim();
  const mediaCategory = String(form.media_category || '').trim();
  if (!mediaId) {
    formError.value = '来源内 ID 不能为空';
    return
  }
  if (!canonicalTitle) {
    formError.value = '固定标题不能为空';
    return
  }
  if (!mediaCategory) {
    formError.value = '分类不能为空';
    return
  }

  submitting.value = true;
  try {
    const payload = {
      media_source: form.media_source,
      media_id: mediaId,
      canonical_title: canonicalTitle,
      canonical_year: String(form.canonical_year || '').trim(),
      media_category: mediaCategory,
    };
    const result = unwrapResponse(await props.api.post(`${pluginBase.value}/bindings`, payload));
    if (!result?.success) throw new Error(result?.message || '操作失败')
    bindingDialog.value = false;
    resetBindingForm();
    showMessage(result.message || '标题绑定已保存', 'success');
    try {
      await loadBindings();
    } catch (error) {
      showMessage('绑定已保存，列表刷新失败，请点击刷新重试', 'warning');
    }
  } catch (error) {
    formError.value = error?.message || '保存失败';
  } finally {
    submitting.value = false;
  }
}

function editBinding(item) {
  const row = normalizeRow(item);
  formError.value = '';
  editing.value = true;
  form.media_source = row.media_source || 'themoviedb';
  form.media_id = row.media_id || '';
  form.canonical_title = row.canonical_title || '';
  form.canonical_year = row.canonical_year || '';
  form.media_category = row.media_category || '';
  bindingDialog.value = true;
}

async function deleteBinding(item) {
  const row = normalizeRow(item);
  if (!window.confirm(`确认删除 ${row.media_source} / ${row.media_id} 的标题绑定？`)) return
  submitting.value = true;
  try {
    const result = unwrapResponse(
      await props.api.post(`${pluginBase.value}/bindings/delete`, {
        media_source: row.media_source,
        media_id: row.media_id,
      }),
    );
    if (!result?.success) throw new Error(result?.message || '删除失败')
    await loadBindings();
    showMessage(result.message || '标题绑定已删除', 'success');
  } catch (error) {
    showMessage(error?.message || '删除失败', 'error');
  } finally {
    submitting.value = false;
  }
}

onMounted(refreshPage);
onBeforeUnmount(() => clearTimeout(noticeTimer));

return (_ctx, _cache) => {
  const _component_VIcon = _resolveComponent("VIcon");
  const _component_VSpacer = _resolveComponent("VSpacer");
  const _component_VBtn = _resolveComponent("VBtn");
  const _component_VToolbar = _resolveComponent("VToolbar");
  const _component_VDivider = _resolveComponent("VDivider");
  const _component_VAlert = _resolveComponent("VAlert");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VPagination = _resolveComponent("VPagination");
  const _component_VDataTable = _resolveComponent("VDataTable");
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VForm = _resolveComponent("VForm");
  const _component_VCardActions = _resolveComponent("VCardActions");
  const _component_VDialog = _resolveComponent("VDialog");

  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createVNode(_component_VToolbar, {
      density: "comfortable",
      color: "transparent"
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VIcon, {
          icon: "mdi-lock-outline",
          color: "primary",
          class: "ms-3 me-2"
        }),
        _cache[12] || (_cache[12] = _createElementVNode("div", { class: "text-h6" }, "媒体标题固定", -1)),
        _createVNode(_component_VSpacer),
        _createVNode(_component_VBtn, {
          icon: "mdi-refresh",
          variant: "text",
          loading: loading.value,
          title: "刷新",
          onClick: refreshPage
        }, null, 8, ["loading"]),
        _createVNode(_component_VBtn, {
          icon: "mdi-close",
          variant: "text",
          title: "关闭",
          onClick: _cache[0] || (_cache[0] = $event => (emit('close')))
        })
      ]),
      _: 1
    }),
    _createVNode(_component_VDivider),
    _createElementVNode("div", _hoisted_2, [
      (notice.text)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 0,
            type: notice.type,
            variant: "tonal",
            density: "compact",
            closable: "",
            class: "mb-3"
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(notice.text), 1)
            ]),
            _: 1
          }, 8, ["type"]))
        : _createCommentVNode("", true),
      (versionWarning.value)
        ? (_openBlock(), _createBlock(_component_VAlert, {
            key: 1,
            type: "warning",
            variant: "tonal",
            density: "compact",
            class: "mb-3"
          }, {
            default: _withCtx(() => [
              _createTextVNode(_toDisplayString(versionWarning.value) + " ", 1),
              _createElementVNode("div", _hoisted_3, "前端 " + _toDisplayString(frontendVersion) + " / " + _toDisplayString(frontendRevision) + "；后端 " + _toDisplayString(backendVersion.value || '未知') + " / " + _toDisplayString(backendRevision.value || '未知'), 1)
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      _createVNode(_component_VCard, {
        variant: "outlined",
        class: "mtl-settings mb-4"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VCardText, { class: "mtl-settings-content" }, {
            default: _withCtx(() => [
              _cache[14] || (_cache[14] = _createElementVNode("div", null, [
                _createElementVNode("div", { class: "text-subtitle-1 font-weight-medium" }, "标题与分类固定"),
                _createElementVNode("div", { class: "text-caption text-medium-emphasis" }, "首次整理成功后自动记录，后续整理沿用绑定。")
              ], -1)),
              _createElementVNode("div", _hoisted_4, [
                _createVNode(_component_VSwitch, {
                  modelValue: enabled.value,
                  "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((enabled).value = $event)),
                  label: "启用",
                  color: "success",
                  density: "compact",
                  "hide-details": ""
                }, null, 8, ["modelValue"]),
                _createVNode(_component_VBtn, {
                  color: "primary",
                  variant: "tonal",
                  size: "small",
                  loading: savingConfig.value,
                  onClick: saveConfig
                }, {
                  default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
                    _createTextVNode(" 保存设置 ", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading"]),
                _createVNode(_component_VBtn, {
                  variant: "text",
                  size: "small",
                  "prepend-icon": "mdi-information-outline",
                  "aria-expanded": diagnosticsOpen.value,
                  onClick: toggleDiagnostics
                }, {
                  default: _withCtx(() => [
                    _createTextVNode(_toDisplayString(diagnosticsOpen.value ? '收起诊断' : '运行诊断'), 1)
                  ]),
                  _: 1
                }, 8, ["aria-expanded"])
              ])
            ]),
            _: 1
          })
        ]),
        _: 1
      }),
      (diagnosticsOpen.value)
        ? (_openBlock(), _createBlock(_component_VCard, {
            key: 2,
            variant: "outlined",
            class: "mtl-diagnostics mb-4"
          }, {
            default: _withCtx(() => [
              _createElementVNode("div", _hoisted_5, [
                _cache[16] || (_cache[16] = _createElementVNode("span", { class: "text-subtitle-1 font-weight-medium" }, "运行诊断", -1)),
                _createVNode(_component_VBtn, {
                  variant: "text",
                  size: "small",
                  "prepend-icon": "mdi-refresh",
                  loading: diagnosticsLoading.value,
                  onClick: loadDiagnostics
                }, {
                  default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                    _createTextVNode("刷新诊断", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading"])
              ]),
              _createVNode(_component_VCardText, { class: "pt-0" }, {
                default: _withCtx(() => [
                  _createElementVNode("div", _hoisted_6, [
                    _createTextVNode(" 前端 " + _toDisplayString(frontendVersion) + " / " + _toDisplayString(frontendRevision)),
                    _cache[17] || (_cache[17] = _createElementVNode("br", null, null, -1)),
                    _createTextVNode(" 后端 " + _toDisplayString(backendVersion.value || '未知') + " / " + _toDisplayString(backendRevision.value || '未知'), 1),
                    _cache[18] || (_cache[18] = _createElementVNode("br", null, null, -1)),
                    _createTextVNode(" 最近应用（含预览）：" + _toDisplayString(diagnostics.value.last_applied_at || '本次运行暂无记录') + " · Emby 识别：未检测 ", 1)
                  ]),
                  _createVNode(_component_VAlert, {
                    type: "info",
                    variant: "tonal",
                    density: "compact",
                    class: "mb-3"
                  }, {
                    default: _withCtx(() => [...(_cache[19] || (_cache[19] = [
                      _createTextVNode(" 分类固定及失效回退仅对新下载任务生效，不追溯修改旧下载任务或手动整理。 文件整理成功不代表 Emby 已识别，本插件不查询 Emby 状态。 ", -1)
                    ]))]),
                    _: 1
                  }),
                  (diagnosticsError.value)
                    ? (_openBlock(), _createBlock(_component_VAlert, {
                        key: 0,
                        type: "error",
                        variant: "tonal",
                        density: "compact",
                        class: "mb-3"
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(diagnosticsError.value), 1)
                        ]),
                        _: 1
                      }))
                    : _createCommentVNode("", true),
                  _cache[20] || (_cache[20] = _createElementVNode("div", { class: "text-caption text-medium-emphasis mb-2" }, "本次运行最近 100 条，重载后清空；标题渲染记录可能来自预览。", -1)),
                  _createElementVNode("div", _hoisted_7, [
                    (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(diagnostics.value.items, (record, index) => {
                      return (_openBlock(), _createElementBlock("div", {
                        key: index,
                        class: "mtl-diagnostic-entry"
                      }, [
                        _createElementVNode("div", _hoisted_8, [
                          _createVNode(_component_VChip, {
                            size: "x-small",
                            variant: "tonal",
                            color: statusColor(record.status)
                          }, {
                            default: _withCtx(() => [
                              _createTextVNode(_toDisplayString(stageText(record.stage)), 1)
                            ]),
                            _: 2
                          }, 1032, ["color"]),
                          _createElementVNode("span", _hoisted_9, _toDisplayString(record.timestamp) + " · " + _toDisplayString(record.media_source || '-') + " / " + _toDisplayString(record.media_id || '-'), 1)
                        ]),
                        _createElementVNode("div", _hoisted_10, _toDisplayString(record.message), 1),
                        (record.original_title || record.effective_title)
                          ? (_openBlock(), _createElementBlock("div", _hoisted_11, "标题：" + _toDisplayString(record.original_title || '未提供') + " → " + _toDisplayString(record.effective_title || '未提供'), 1))
                          : _createCommentVNode("", true),
                        (record.original_category || record.effective_category)
                          ? (_openBlock(), _createElementBlock("div", _hoisted_12, "分类：" + _toDisplayString(record.original_category || '未提供') + " → " + _toDisplayString(record.effective_category || '未识别分类，交由 MP 处理'), 1))
                          : _createCommentVNode("", true)
                      ]))
                    }), 128)),
                    (!diagnostics.value.items?.length)
                      ? (_openBlock(), _createElementBlock("div", _hoisted_13, "暂无执行记录"))
                      : _createCommentVNode("", true)
                  ])
                ]),
                _: 1
              })
            ]),
            _: 1
          }))
        : _createCommentVNode("", true),
      _createVNode(_component_VCard, {
        variant: "outlined",
        class: "mtl-bindings"
      }, {
        default: _withCtx(() => [
          _createElementVNode("div", _hoisted_14, [
            _createElementVNode("div", _hoisted_15, [
              _cache[21] || (_cache[21] = _createElementVNode("span", { class: "text-subtitle-1 font-weight-medium" }, "标题绑定", -1)),
              _createVNode(_component_VChip, {
                size: "small",
                variant: "tonal",
                color: "primary"
              }, {
                default: _withCtx(() => [
                  _createTextVNode(_toDisplayString(total.value) + " 条", 1)
                ]),
                _: 1
              })
            ]),
            _createVNode(_component_VBtn, {
              color: "primary",
              variant: "flat",
              "prepend-icon": "mdi-plus",
              disabled: loading.value || submitting.value,
              onClick: addBinding
            }, {
              default: _withCtx(() => [...(_cache[22] || (_cache[22] = [
                _createTextVNode(" 新增绑定 ", -1)
              ]))]),
              _: 1
            }, 8, ["disabled"])
          ]),
          _createVNode(_component_VCardText, { class: "mtl-filters" }, {
            default: _withCtx(() => [
              _createVNode(_component_VRow, {
                dense: "",
                align: "center"
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VCol, {
                    cols: "12",
                    sm: "4"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VTextField, {
                        modelValue: filters.tmdbid,
                        "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((filters.tmdbid) = $event)),
                        label: "TMDB ID",
                        variant: "outlined",
                        density: "compact",
                        clearable: "",
                        "hide-details": "",
                        onKeyup: _withKeys(applyFilters, ["enter"])
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_VCol, {
                    cols: "12",
                    sm: "4"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VTextField, {
                        modelValue: filters.title,
                        "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((filters.title) = $event)),
                        label: "标题",
                        variant: "outlined",
                        density: "compact",
                        clearable: "",
                        "hide-details": "",
                        onKeyup: _withKeys(applyFilters, ["enter"])
                      }, null, 8, ["modelValue"])
                    ]),
                    _: 1
                  }),
                  _createVNode(_component_VCol, {
                    cols: "12",
                    sm: "4",
                    class: "d-flex ga-2"
                  }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VBtn, {
                        color: "primary",
                        variant: "tonal",
                        loading: loading.value,
                        onClick: applyFilters
                      }, {
                        default: _withCtx(() => [...(_cache[23] || (_cache[23] = [
                          _createTextVNode(" 筛选 ", -1)
                        ]))]),
                        _: 1
                      }, 8, ["loading"]),
                      _createVNode(_component_VBtn, {
                        variant: "text",
                        disabled: loading.value,
                        onClick: clearFilters
                      }, {
                        default: _withCtx(() => [...(_cache[24] || (_cache[24] = [
                          _createTextVNode("重置", -1)
                        ]))]),
                        _: 1
                      }, 8, ["disabled"])
                    ]),
                    _: 1
                  })
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          (categoryError.value)
            ? (_openBlock(), _createBlock(_component_VAlert, {
                key: 0,
                type: "warning",
                variant: "tonal",
                density: "compact",
                class: "mx-5 mb-3"
              }, {
                default: _withCtx(() => [
                  _createTextVNode(_toDisplayString(categoryError.value), 1)
                ]),
                _: 1
              }))
            : _createCommentVNode("", true),
          _createVNode(_component_VDataTable, {
            "items-per-page": -1,
            headers: _unref(headers),
            items: bindings.value,
            loading: loading.value,
            density: "compact",
            "fixed-header": "",
            class: "mtl-table",
            "no-data-text": "暂无匹配的绑定记录",
            "loading-text": "正在加载绑定记录…"
          }, {
            "item.canonical_title": _withCtx(({ item }) => [
              _createElementVNode("span", _hoisted_16, _toDisplayString(normalizeRow(item).canonical_title), 1)
            ]),
            "item.category": _withCtx(({ item }) => [
              _createVNode(_component_VChip, {
                size: "small",
                variant: "tonal",
                color: normalizeRow(item).category_status === 'valid' ? 'primary' : 'warning'
              }, {
                default: _withCtx(() => [
                  _createTextVNode(_toDisplayString(normalizeRow(item).category), 1)
                ]),
                _: 2
              }, 1032, ["color"]),
              (normalizeRow(item).category_status === 'invalid')
                ? (_openBlock(), _createElementBlock("div", _hoisted_17, "已失效 · 新下载沿用识别分类"))
                : (normalizeRow(item).category_status === 'unknown')
                  ? (_openBlock(), _createElementBlock("div", _hoisted_18, "暂无法校验"))
                  : _createCommentVNode("", true)
            ]),
            "item.actions": _withCtx(({ item }) => [
              _createElementVNode("div", _hoisted_19, [
                _createVNode(_component_VBtn, {
                  icon: "mdi-pencil-outline",
                  size: "small",
                  variant: "text",
                  color: "primary",
                  title: "编辑",
                  "aria-label": "编辑",
                  disabled: submitting.value,
                  onClick: $event => (editBinding(item))
                }, null, 8, ["disabled", "onClick"]),
                _createVNode(_component_VBtn, {
                  icon: "mdi-delete-outline",
                  size: "small",
                  variant: "text",
                  color: "error",
                  title: "删除",
                  "aria-label": "删除",
                  disabled: submitting.value,
                  onClick: $event => (deleteBinding(item))
                }, null, 8, ["disabled", "onClick"])
              ])
            ]),
            bottom: _withCtx(() => [
              _createElementVNode("div", _hoisted_20, [
                _createElementVNode("div", _hoisted_21, [
                  _cache[25] || (_cache[25] = _createElementVNode("span", { class: "text-caption text-medium-emphasis" }, "每页", -1)),
                  _createVNode(_component_VSelect, {
                    "model-value": itemsPerPage.value,
                    disabled: loading.value,
                    items: [10, 25, 50, 100],
                    "aria-label": "每页条数",
                    variant: "outlined",
                    density: "compact",
                    "hide-details": "",
                    class: "mtl-page-size",
                    "onUpdate:modelValue": changePageSize
                  }, null, 8, ["model-value", "disabled"]),
                  _createElementVNode("span", _hoisted_22, "共 " + _toDisplayString(total.value) + " 条", 1)
                ]),
                _createElementVNode("div", _hoisted_23, [
                  _createElementVNode("span", _hoisted_24, "第 " + _toDisplayString(page.value) + " 页 / 共 " + _toDisplayString(pageCount.value) + " 页", 1),
                  _createVNode(_component_VPagination, {
                    "model-value": page.value,
                    length: pageCount.value,
                    "total-visible": 5,
                    disabled: loading.value || bindings.value.length === 0,
                    density: "compact",
                    rounded: "lg",
                    "active-color": "primary",
                    "aria-label": "绑定列表分页",
                    "previous-aria-label": "上一页",
                    "next-aria-label": "下一页",
                    "page-aria-label": "第 {0} 页",
                    "current-page-aria-label": "第 {0} 页，当前页",
                    "onUpdate:modelValue": changePage
                  }, null, 8, ["model-value", "length", "disabled"])
                ])
              ])
            ]),
            _: 1
          }, 8, ["headers", "items", "loading"])
        ]),
        _: 1
      })
    ]),
    _createVNode(_component_VDialog, {
      modelValue: bindingDialog.value,
      "onUpdate:modelValue": _cache[11] || (_cache[11] = $event => ((bindingDialog).value = $event)),
      "max-width": "680",
      persistent: submitting.value,
      scrollable: ""
    }, {
      default: _withCtx(() => [
        _createVNode(_component_VCard, { class: "mtl-editor" }, {
          default: _withCtx(() => [
            _createVNode(_component_VCardTitle, { class: "d-flex align-center justify-space-between" }, {
              default: _withCtx(() => [
                _createElementVNode("span", null, _toDisplayString(editing.value ? '编辑绑定' : '新增绑定'), 1),
                _createVNode(_component_VBtn, {
                  icon: "mdi-close",
                  variant: "text",
                  size: "small",
                  "aria-label": "关闭表单",
                  disabled: submitting.value,
                  onClick: _cache[4] || (_cache[4] = $event => (bindingDialog.value = false))
                }, null, 8, ["disabled"])
              ]),
              _: 1
            }),
            _createVNode(_component_VDivider),
            _createVNode(_component_VCardText, null, {
              default: _withCtx(() => [
                _cache[26] || (_cache[26] = _createElementVNode("p", { class: "text-body-2 text-medium-emphasis mb-5" }, "按媒体来源与 ID 固定标题和分类。标记 * 的为必填项。", -1)),
                (formError.value)
                  ? (_openBlock(), _createBlock(_component_VAlert, {
                      key: 0,
                      type: "error",
                      variant: "tonal",
                      density: "compact",
                      class: "mb-4"
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(formError.value), 1)
                      ]),
                      _: 1
                    }))
                  : _createCommentVNode("", true),
                _createVNode(_component_VForm, {
                  id: "mtl-binding-form",
                  disabled: submitting.value,
                  onSubmit: _withModifiers(submitBinding, ["prevent"])
                }, {
                  default: _withCtx(() => [
                    _createVNode(_component_VRow, { dense: "" }, {
                      default: _withCtx(() => [
                        _createVNode(_component_VCol, {
                          cols: "12",
                          sm: "4"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_VSelect, {
                              modelValue: form.media_source,
                              "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((form.media_source) = $event)),
                              items: sourceItems,
                              label: "媒体来源",
                              variant: "outlined",
                              density: "compact",
                              "hide-details": "auto"
                            }, null, 8, ["modelValue"])
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_VCol, {
                          cols: "12",
                          sm: "8"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_VTextField, {
                              modelValue: form.media_id,
                              "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((form.media_id) = $event)),
                              label: "来源内 ID *",
                              variant: "outlined",
                              density: "compact",
                              "hide-details": "auto"
                            }, null, 8, ["modelValue"])
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_VCol, { cols: "12" }, {
                          default: _withCtx(() => [
                            _createVNode(_component_VTextField, {
                              modelValue: form.canonical_title,
                              "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((form.canonical_title) = $event)),
                              label: "固定标题 *",
                              variant: "outlined",
                              density: "compact",
                              "hide-details": "auto"
                            }, null, 8, ["modelValue"])
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_VCol, {
                          cols: "12",
                          sm: "4"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_VTextField, {
                              modelValue: form.canonical_year,
                              "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((form.canonical_year) = $event)),
                              label: "固定年份",
                              placeholder: "可不填",
                              variant: "outlined",
                              density: "compact",
                              "hide-details": "auto"
                            }, null, 8, ["modelValue"])
                          ]),
                          _: 1
                        }),
                        _createVNode(_component_VCol, {
                          cols: "12",
                          sm: "8"
                        }, {
                          default: _withCtx(() => [
                            _createVNode(_component_VSelect, {
                              modelValue: form.media_category,
                              "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((form.media_category) = $event)),
                              items: categories.value,
                              label: "分类 *",
                              variant: "outlined",
                              density: "compact",
                              "hide-details": "auto",
                              "no-data-text": "MoviePilot 暂无可用分类"
                            }, null, 8, ["modelValue", "items"])
                          ]),
                          _: 1
                        })
                      ]),
                      _: 1
                    })
                  ]),
                  _: 1
                }, 8, ["disabled"])
              ]),
              _: 1
            }),
            _createVNode(_component_VDivider),
            _createVNode(_component_VCardActions, { class: "px-6 py-4" }, {
              default: _withCtx(() => [
                _createVNode(_component_VSpacer),
                _createVNode(_component_VBtn, {
                  variant: "text",
                  disabled: submitting.value,
                  onClick: _cache[10] || (_cache[10] = $event => (bindingDialog.value = false))
                }, {
                  default: _withCtx(() => [...(_cache[27] || (_cache[27] = [
                    _createTextVNode("取消", -1)
                  ]))]),
                  _: 1
                }, 8, ["disabled"]),
                _createVNode(_component_VBtn, {
                  type: "submit",
                  form: "mtl-binding-form",
                  color: "primary",
                  variant: "flat",
                  loading: submitting.value
                }, {
                  default: _withCtx(() => [...(_cache[28] || (_cache[28] = [
                    _createTextVNode("保存绑定", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading"])
              ]),
              _: 1
            })
          ]),
          _: 1
        })
      ]),
      _: 1
    }, 8, ["modelValue", "persistent"])
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-d6cc415e"]]);

export { Page as default };
