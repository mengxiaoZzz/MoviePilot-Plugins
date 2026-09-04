import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,withCtx:_withCtx,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,withModifiers:_withModifiers,withKeys:_withKeys,createElementBlock:_createElementBlock} = await importShared('vue');


const _hoisted_1 = { class: "mtl-page" };
const _hoisted_2 = { class: "mtl-body" };
const _hoisted_3 = { class: "d-flex flex-wrap align-center ga-4" };
const _hoisted_4 = { class: "d-flex justify-end ga-2 mt-4" };
const _hoisted_5 = { class: "d-flex ga-1" };

const {computed,onBeforeUnmount,onMounted,reactive,ref} = await importShared('vue');



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
const operationItems = [
  { title: '新增或修改', value: 'upsert' },
  { title: '删除', value: 'delete' },
];
const headers = [
  { title: '媒体身份', key: 'identity', sortable: false },
  { title: '固定标题', key: 'canonical_title' },
  { title: '年份', key: 'year' },
  { title: '分类', key: 'category' },
  { title: '来源', key: 'origin_text' },
  { title: '更新时间', key: 'updated_at' },
  { title: '操作', key: 'actions', sortable: false },
];

const enabled = ref(false);
const bindings = ref([]);
const categories = ref([]);
const total = ref(0);
const loading = ref(false);
const savingConfig = ref(false);
const submitting = ref(false);
const notice = reactive({ text: '', type: 'info' });
const form = reactive({
  operation: 'upsert',
  media_source: 'themoviedb',
  media_id: '',
  canonical_title: '',
  canonical_year: '',
  media_category: '',
});
const filters = reactive({ tmdbid: '', title: '' });

let noticeTimer;
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
  form.operation = 'upsert';
  form.media_id = '';
  form.canonical_title = '';
  form.canonical_year = '';
  form.media_category = '';
}

async function loadConfig() {
  const result = unwrapResponse(await props.api.get(`${pluginBase.value}/config`));
  if (!result?.success) throw new Error(result?.message || '配置加载失败')
  enabled.value = Boolean(result.data?.enabled);
}

async function loadBindings() {
  const query = new URLSearchParams();
  const tmdbid = String(filters.tmdbid || '').trim();
  const title = String(filters.title || '').trim();
  if (tmdbid) query.set('tmdbid', tmdbid);
  if (title) query.set('title', title);
  const suffix = query.toString() ? `?${query.toString()}` : '';
  const result = unwrapResponse(await props.api.get(`${pluginBase.value}/bindings${suffix}`));
  if (!result?.success) throw new Error(result?.message || '绑定列表加载失败')
  const items = result.data?.items || [];
  bindings.value = items.map(item => ({
    ...item,
    identity: `${item.media_source} / ${item.media_id}`,
    year: item.canonical_year || '-',
    category: item.media_category || '待补充',
    origin_text: originText(item.origin),
  }));
  total.value = Number(result.data?.total || 0);
}

async function loadCategories() {
  const result = unwrapResponse(await props.api.get(`${pluginBase.value}/categories`));
  if (!result?.success) throw new Error(result?.message || '分类加载失败')
  categories.value = result.data?.items || [];
}

async function refreshPage() {
  loading.value = true;
  try {
    await Promise.all([loadConfig(), loadCategories(), loadBindings()]);
  } catch (error) {
    showMessage(error?.message || '页面加载失败', 'error');
  } finally {
    loading.value = false;
  }
}

async function applyFilters() {
  loading.value = true;
  try {
    await loadBindings();
  } catch (error) {
    showMessage(error?.message || '筛选失败', 'error');
  } finally {
    loading.value = false;
  }
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
  const mediaId = String(form.media_id || '').trim();
  const canonicalTitle = String(form.canonical_title || '').trim();
  const mediaCategory = String(form.media_category || '').trim();
  if (!mediaId) {
    showMessage('来源内 ID 不能为空', 'warning');
    return
  }
  if (form.operation === 'upsert' && !canonicalTitle) {
    showMessage('固定标题不能为空', 'warning');
    return
  }
  if (form.operation === 'upsert' && !mediaCategory) {
    showMessage('分类不能为空', 'warning');
    return
  }

  submitting.value = true;
  try {
    const deleting = form.operation === 'delete';
    const path = deleting ? 'bindings/delete' : 'bindings';
    const payload = deleting
      ? { media_source: form.media_source, media_id: mediaId }
      : {
          media_source: form.media_source,
          media_id: mediaId,
          canonical_title: canonicalTitle,
          canonical_year: String(form.canonical_year || '').trim(),
          media_category: mediaCategory,
        };
    const result = unwrapResponse(await props.api.post(`${pluginBase.value}/${path}`, payload));
    if (!result?.success) throw new Error(result?.message || '操作失败')
    resetBindingForm();
    await loadBindings();
    showMessage(result.message || '操作成功', 'success');
  } catch (error) {
    showMessage(error?.message || '操作失败', 'error');
  } finally {
    submitting.value = false;
  }
}

function editBinding(item) {
  const row = normalizeRow(item);
  form.operation = 'upsert';
  form.media_source = row.media_source || 'themoviedb';
  form.media_id = row.media_id || '';
  form.canonical_title = row.canonical_title || '';
  form.canonical_year = row.canonical_year || '';
  form.media_category = row.media_category || '';
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
  const _component_VCardTitle = _resolveComponent("VCardTitle");
  const _component_VSwitch = _resolveComponent("VSwitch");
  const _component_VCardText = _resolveComponent("VCardText");
  const _component_VCard = _resolveComponent("VCard");
  const _component_VSelect = _resolveComponent("VSelect");
  const _component_VCol = _resolveComponent("VCol");
  const _component_VTextField = _resolveComponent("VTextField");
  const _component_VRow = _resolveComponent("VRow");
  const _component_VForm = _resolveComponent("VForm");
  const _component_VChip = _resolveComponent("VChip");
  const _component_VDataTable = _resolveComponent("VDataTable");

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
        _cache[10] || (_cache[10] = _createElementVNode("div", { class: "text-h6" }, "媒体标题固定", -1)),
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
      _createVNode(_component_VCard, {
        variant: "outlined",
        class: "mb-4"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
            default: _withCtx(() => [...(_cache[11] || (_cache[11] = [
              _createTextVNode("运行设置", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VCardText, null, {
            default: _withCtx(() => [
              _createElementVNode("div", _hoisted_3, [
                _createVNode(_component_VSwitch, {
                  modelValue: enabled.value,
                  "onUpdate:modelValue": _cache[1] || (_cache[1] = $event => ((enabled).value = $event)),
                  label: "启用标题固定",
                  color: "success",
                  "hide-details": ""
                }, null, 8, ["modelValue"]),
                _createVNode(_component_VBtn, {
                  color: "primary",
                  variant: "flat",
                  "prepend-icon": "mdi-content-save",
                  loading: savingConfig.value,
                  onClick: saveConfig
                }, {
                  default: _withCtx(() => [...(_cache[12] || (_cache[12] = [
                    _createTextVNode(" 保存设置 ", -1)
                  ]))]),
                  _: 1
                }, 8, ["loading"])
              ])
            ]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VCard, {
        variant: "outlined",
        class: "mb-4"
      }, {
        default: _withCtx(() => [
          _createVNode(_component_VCardTitle, { class: "text-subtitle-1" }, {
            default: _withCtx(() => [...(_cache[13] || (_cache[13] = [
              _createTextVNode("人工维护绑定", -1)
            ]))]),
            _: 1
          }),
          _createVNode(_component_VCardText, null, {
            default: _withCtx(() => [
              _createVNode(_component_VAlert, {
                type: "info",
                variant: "tonal",
                density: "compact",
                class: "mb-4"
              }, {
                default: _withCtx(() => [...(_cache[14] || (_cache[14] = [
                  _createTextVNode(" 绑定键为媒体来源 + 来源内 ID。新增或修改时需填写固定标题并选择分类；自动下载首次整理成功后会自动补充记录。 ", -1)
                ]))]),
                _: 1
              }),
              _createVNode(_component_VForm, {
                onSubmit: _withModifiers(submitBinding, ["prevent"])
              }, {
                default: _withCtx(() => [
                  _createVNode(_component_VRow, { dense: "" }, {
                    default: _withCtx(() => [
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "3"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSelect, {
                            modelValue: form.operation,
                            "onUpdate:modelValue": _cache[2] || (_cache[2] = $event => ((form.operation) = $event)),
                            items: operationItems,
                            label: "操作",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      _createVNode(_component_VCol, {
                        cols: "12",
                        md: "3"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VSelect, {
                            modelValue: form.media_source,
                            "onUpdate:modelValue": _cache[3] || (_cache[3] = $event => ((form.media_source) = $event)),
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
                        md: "6"
                      }, {
                        default: _withCtx(() => [
                          _createVNode(_component_VTextField, {
                            modelValue: form.media_id,
                            "onUpdate:modelValue": _cache[4] || (_cache[4] = $event => ((form.media_id) = $event)),
                            label: "来源内 ID",
                            variant: "outlined",
                            density: "compact",
                            "hide-details": "auto"
                          }, null, 8, ["modelValue"])
                        ]),
                        _: 1
                      }),
                      (form.operation === 'upsert')
                        ? (_openBlock(), _createBlock(_component_VCol, {
                            key: 0,
                            cols: "12",
                            md: "6"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_VTextField, {
                                modelValue: form.canonical_title,
                                "onUpdate:modelValue": _cache[5] || (_cache[5] = $event => ((form.canonical_title) = $event)),
                                label: "固定标题",
                                variant: "outlined",
                                density: "compact",
                                "hide-details": "auto"
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          }))
                        : _createCommentVNode("", true),
                      (form.operation === 'upsert')
                        ? (_openBlock(), _createBlock(_component_VCol, {
                            key: 1,
                            cols: "12",
                            md: "2"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_VTextField, {
                                modelValue: form.canonical_year,
                                "onUpdate:modelValue": _cache[6] || (_cache[6] = $event => ((form.canonical_year) = $event)),
                                label: "固定年份",
                                variant: "outlined",
                                density: "compact",
                                "hide-details": "auto"
                              }, null, 8, ["modelValue"])
                            ]),
                            _: 1
                          }))
                        : _createCommentVNode("", true),
                      (form.operation === 'upsert')
                        ? (_openBlock(), _createBlock(_component_VCol, {
                            key: 2,
                            cols: "12",
                            md: "4"
                          }, {
                            default: _withCtx(() => [
                              _createVNode(_component_VSelect, {
                                modelValue: form.media_category,
                                "onUpdate:modelValue": _cache[7] || (_cache[7] = $event => ((form.media_category) = $event)),
                                items: categories.value,
                                label: "分类 *",
                                variant: "outlined",
                                density: "compact",
                                "hide-details": "auto",
                                "no-data-text": "MoviePilot 暂无可用分类"
                              }, null, 8, ["modelValue", "items"])
                            ]),
                            _: 1
                          }))
                        : _createCommentVNode("", true)
                    ]),
                    _: 1
                  }),
                  _createElementVNode("div", _hoisted_4, [
                    _createVNode(_component_VBtn, {
                      variant: "text",
                      disabled: submitting.value,
                      onClick: resetBindingForm
                    }, {
                      default: _withCtx(() => [...(_cache[15] || (_cache[15] = [
                        _createTextVNode("清空", -1)
                      ]))]),
                      _: 1
                    }, 8, ["disabled"]),
                    _createVNode(_component_VBtn, {
                      type: "submit",
                      color: form.operation === 'delete' ? 'error' : 'primary',
                      variant: "flat",
                      "prepend-icon": form.operation === 'delete' ? 'mdi-delete' : 'mdi-content-save',
                      loading: submitting.value
                    }, {
                      default: _withCtx(() => [
                        _createTextVNode(_toDisplayString(form.operation === 'delete' ? '删除绑定' : '保存绑定'), 1)
                      ]),
                      _: 1
                    }, 8, ["color", "prepend-icon", "loading"])
                  ])
                ]),
                _: 1
              })
            ]),
            _: 1
          })
        ]),
        _: 1
      }),
      _createVNode(_component_VCard, { variant: "outlined" }, {
        default: _withCtx(() => [
          _createVNode(_component_VCardTitle, { class: "text-subtitle-1 d-flex align-center" }, {
            default: _withCtx(() => [
              _cache[16] || (_cache[16] = _createTextVNode(" 标题绑定 ", -1)),
              _createVNode(_component_VChip, {
                size: "small",
                variant: "tonal",
                color: "primary",
                class: "ms-2"
              }, {
                default: _withCtx(() => [
                  _createTextVNode(_toDisplayString(total.value), 1)
                ]),
                _: 1
              })
            ]),
            _: 1
          }),
          _createVNode(_component_VCardText, { class: "pb-0" }, {
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
                        "onUpdate:modelValue": _cache[8] || (_cache[8] = $event => ((filters.tmdbid) = $event)),
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
                        "onUpdate:modelValue": _cache[9] || (_cache[9] = $event => ((filters.title) = $event)),
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
                        default: _withCtx(() => [...(_cache[17] || (_cache[17] = [
                          _createTextVNode(" 筛选 ", -1)
                        ]))]),
                        _: 1
                      }, 8, ["loading"]),
                      _createVNode(_component_VBtn, {
                        variant: "text",
                        disabled: loading.value,
                        onClick: clearFilters
                      }, {
                        default: _withCtx(() => [...(_cache[18] || (_cache[18] = [
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
          _createVNode(_component_VDataTable, {
            headers: headers,
            items: bindings.value,
            loading: loading.value,
            "items-per-page": 25,
            density: "compact"
          }, {
            "item.actions": _withCtx(({ item }) => [
              _createElementVNode("div", _hoisted_5, [
                _createVNode(_component_VBtn, {
                  icon: "mdi-pencil",
                  size: "small",
                  variant: "text",
                  title: "编辑",
                  onClick: $event => (editBinding(item))
                }, null, 8, ["onClick"]),
                _createVNode(_component_VBtn, {
                  icon: "mdi-delete",
                  size: "small",
                  variant: "text",
                  color: "error",
                  title: "删除",
                  onClick: $event => (deleteBinding(item))
                }, null, 8, ["onClick"])
              ])
            ]),
            _: 1
          }, 8, ["items", "loading"])
        ]),
        _: 1
      })
    ])
  ]))
}
}

};
const Page = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-b03efe8e"]]);

export { Page as default };
