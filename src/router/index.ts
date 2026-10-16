import { createRouter, createWebHistory } from 'vue-router'
import { pages } from './pages'
import type { PageType } from './pages'

const views: Record<PageType, () => Promise<any>> = {
  home: () => import('../views/HomeView.vue'),
  overview: () => import('../views/OverviewView.vue'),
  entity: () => import('../views/EntityView.vue'),
  flow: () => import('../views/FlowView.vue'),
  runs: () => import('../views/RunsView.vue'),
  data: () => import('../views/DataView.vue'),
  alerts: () => import('../views/AlertsView.vue'),
  accounts: () => import('../views/AccountsView.vue'),
  audit: () => import('../views/AuditView.vue'),
  local: () => import('../views/LocalWorkbench.vue'),
  sources: () => import('../views/SourcesView.vue'),
  raw: () => import('../views/RawView.vue'),
}
export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/zt-zymh/:pathMatch(.*)*', redirect: '/portal/resources' },
    { path: '/zt-ztgl/:pathMatch(.*)*', redirect: '/system/users' },
    { path: '/', redirect: '/home' },
    { path: '/workbench', redirect: '/develop/flows' },
    { path: '/zt-sjzl/:pathMatch(.*)*', redirect: '/quality/overview' },
    { path: '/zt-sjbz/:pathMatch(.*)*', redirect: '/standard/overview' },
    { path: '/zt-sjjr/:pathMatch(.*)*', redirect: '/access/sources' },
    { path: '/zt-sjcl/:pathMatch(.*)*', redirect: '/develop/flows' },
    { path: '/zt-sjzc/:pathMatch(.*)*', redirect: '/asset/resources' },
    { path: '/zt-sjfw/:pathMatch(.*)*', redirect: '/service/overview' },
    ...pages.map((p) => ({
      path: p.path,
      component: views[p.type],
      meta: { page: p, title: p.title },
    })),
    { path: '/:pathMatch(.*)*', redirect: '/home' },
  ],
})
