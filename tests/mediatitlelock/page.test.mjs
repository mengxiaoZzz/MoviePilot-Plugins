import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { test } from 'node:test'

const require = createRequire(new URL('../../plugins.v2/mediatitlelock/package.json', import.meta.url))
const Vue = require('vue')
const { parse, compileScript } = require('@vue/compiler-sfc')
const source = readFileSync(new URL('../../plugins.v2/mediatitlelock/src/components/Page.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const script = compileScript(descriptor, { id: 'page-test' }).content
const component = new Function('Vue', script
  .replace(/import \{([^}]+)\} from 'vue'/, 'const {$1} = Vue')
  .replace('export default', 'return'))(Vue)

async function mountPage(t) {
  const data = {
    items: Array.from({ length: 126 }, (_, i) => ({
      media_source: 'themoviedb', media_id: String(i + 1),
      canonical_title: `测试标题 ${i + 1}`, canonical_year: '2026', media_category: '日韩剧',
    })),
    posts: [], gets: [], failSave: false,
    backendVersion: '1.0.7', uiRevision: '20260907-pagination-diagnostics', failList: false,
    holdNextList: null,
  }
  const api = {
    async get(path) {
      data.gets.push(path)
      if (path.endsWith('/config')) return { success: true, data: {
        enabled: true, backend_version: data.backendVersion, ui_revision: data.uiRevision,
      } }
      if (path.endsWith('/categories')) return { success: true, data: { items: ['日韩剧'] } }
      if (path.endsWith('/diagnostics')) return { success: true, data: {
        items: [{ timestamp: '2026-09-07 10:00:00', stage: 'download', status: 'fallback', message: '分类失效，沿用识别分类' }],
        emby_status: 'not_checked',
      } }
      if (data.failList) throw new Error('列表读取失败')
      if (data.holdNextList) {
        const hold = data.holdNextList
        data.holdNextList = null
        return hold
      }
      const query = new URL(path, 'http://localhost/').searchParams
      const size = Number(query.get('page_size') || 25)
      const pages = Math.max(1, Math.ceil(data.items.length / size))
      const page = Math.min(Number(query.get('page') || 1), pages)
      return { success: true, data: {
        items: data.items.slice((page - 1) * size, page * size), total: data.items.length,
        page, page_size: size, page_count: pages,
      } }
    },
    async post(path, payload) {
      data.posts.push({ path, payload })
      return { success: !data.failSave, message: data.failSave ? '保存失败' : '保存成功' }
    },
  }
  // Mount the real setup function so Vue runs its lifecycle and pagination watchers.
  const renderer = Vue.createRenderer({
    createComment: () => ({}), insert() {}, remove() {}, parentNode() {}, nextSibling() {},
  })
  const app = renderer.createApp({ ...component, render: () => null }, { api })
  const vm = app.mount({})
  t.after(() => app.unmount())
  await new Promise(resolve => setImmediate(resolve))
  return { state: vm.$.setupState, data }
}

test('126 records have six pages; changing page size returns to page one', async t => {
  const { state } = await mountPage(t)
  await state.changePage(5)
  assert.equal(state.pageCount, 6)
  assert.equal(state.page, 5)
  await state.changePageSize(50)
  assert.equal(state.page, 1)
  assert.equal(state.pageCount, 3)
})

test('removing the last record on the last page clamps the current page', async t => {
  const { state, data } = await mountPage(t)
  await state.changePage(6)
  data.items.pop()
  await state.loadBindings()
  await Vue.nextTick()
  assert.equal(state.pageCount, 5)
  assert.equal(state.page, 5)
})

test('filtering resets to page one even if the result count does not change', async t => {
  const { state, data } = await mountPage(t)
  await state.changePage(5)
  state.filters.title = '测试标题'
  await state.applyFilters()
  assert.equal(state.page, 1)
  assert.equal(new URL(data.gets.at(-1), 'http://localhost/').searchParams.get('title'), '测试标题')
  data.items = []
  await state.applyFilters()
  assert.equal(state.page, 1)
  assert.equal(state.pageCount, 1)
})

test('server pagination reaches records beyond 500 and does not load the whole list', async t => {
  const { state, data } = await mountPage(t)
  data.items = Array.from({ length: 626 }, (_, i) => ({ media_id: String(i + 1) }))
  await state.loadBindings()
  assert.equal(state.total, 626)
  assert.equal(state.bindings.length, 25)
  assert.equal(state.pageCount, 26)
  await state.changePage(26)
  assert.equal(state.bindings.length, 1)
  assert.equal(state.bindings[0].media_id, '626')
  assert.equal(new URL(data.gets.at(-1), 'http://localhost/').searchParams.get('page'), '26')
})

test('unsubmitted filter edits do not affect paging; applying them starts at page one', async t => {
  const { state, data } = await mountPage(t)
  state.filters.title = '尚未筛选'
  await state.changePage(2)
  assert.equal(new URL(data.gets.at(-1), 'http://localhost/').searchParams.get('title'), null)
  await state.applyFilters()
  assert.equal(state.page, 1)
  assert.equal(new URL(data.gets.at(-1), 'http://localhost/').searchParams.get('title'), '尚未筛选')
})

test('version mismatch is persistent and diagnostics open only on demand', async t => {
  const { state, data } = await mountPage(t)
  assert.equal(state.versionWarning, '')
  assert.equal(data.gets.some(path => path.endsWith('/diagnostics')), false)
  data.uiRevision = 'old-ui'
  await state.loadConfig()
  assert.match(state.versionWarning, /不一致/)
  await state.toggleDiagnostics()
  assert.equal(state.diagnosticsOpen, true)
  assert.equal(state.diagnostics.items[0].status, 'fallback')
  assert.equal(state.diagnostics.emby_status, 'not_checked')
  data.backendVersion = ''
  await state.loadConfig()
  assert.match(state.versionWarning, /无法核对/)
})

test('failed page-size changes preserve displayed rows and pagination', async t => {
  const { state, data } = await mountPage(t)
  await state.changePage(5)
  const firstId = state.bindings[0].media_id
  data.failList = true
  await state.changePageSize(100)
  assert.equal(state.page, 5)
  assert.equal(state.itemsPerPage, 25)
  assert.equal(state.bindings[0].media_id, firstId)
  assert.equal(state.notice.type, 'error')
  assert.equal(state.loading, false)
})

test('late requests cannot overwrite a newer page result', async t => {
  const { state, data } = await mountPage(t)
  let release
  data.holdNextList = new Promise(resolve => { release = resolve })
  const previous = state.loadBindings(2)
  await state.changePage(6)
  release({ success: true, data: { items: [], total: 0, page: 1, page_size: 25 } })
  await previous
  assert.equal(state.page, 6)
  assert.equal(state.total, 126)
  assert.equal(state.bindings[0].media_id, '126')
})

test('editor starts closed, fills an edited row, and clears it for a new binding', async t => {
  const { state, data } = await mountPage(t)
  assert.equal(state.bindingDialog, false)
  state.editBinding({ raw: data.items[0] })
  assert.equal(state.bindingDialog, true)
  assert.equal(state.editing, true)
  assert.equal(state.form.media_id, '1')
  assert.equal(state.form.media_category, '日韩剧')
  state.bindingDialog = false
  state.addBinding()
  assert.equal(state.bindingDialog, true)
  assert.equal(state.editing, false)
  assert.equal(state.form.media_id, '')
  assert.equal(state.form.canonical_title, '')
  assert.equal(state.form.media_category, '')
})

test('missing category keeps the editor open and prevents a save', async t => {
  const { state, data } = await mountPage(t)
  state.editBinding(data.items[0])
  state.form.media_category = ''
  await state.submitBinding()
  assert.equal(state.bindingDialog, true)
  assert.equal(state.formError, '分类不能为空')
  assert.equal(data.posts.length, 0)
})

test('saving uses the binding endpoint and closes the editor only on success', async t => {
  const { state, data } = await mountPage(t)
  state.editBinding(data.items[0])
  data.failSave = true
  await state.submitBinding()
  assert.equal(state.bindingDialog, true)
  assert.equal(state.formError, '保存失败')
  assert.equal(state.form.canonical_title, '测试标题 1')
  data.failSave = false
  state.form.canonical_title = ' 修改标题 '
  await state.submitBinding()
  assert.equal(data.posts.at(-1).path, 'plugin/MediaTitleLock/bindings')
  assert.equal(data.posts.at(-1).payload.canonical_title, '修改标题')
  assert.equal(state.bindingDialog, false)
})
