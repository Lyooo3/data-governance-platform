<script setup lang="ts">
import { useRoute } from 'vue-router'
import LocalAnalysisView from './LocalAnalysisView.vue'
import LocalRecordsView from './LocalRecordsView.vue'
import LocalReviewView from './LocalReviewView.vue'
import LocalGraphView from './LocalGraphView.vue'
import LocalChainView from './LocalChainView.vue'
import LocalDeliveryView from './LocalDeliveryView.vue'
import LocalContractView from './LocalContractView.vue'
const route = useRoute()
const managers: Record<string, string> = {
  '/develop/schedules': 'schedules',
  '/service/views': 'views',
  '/service/apps': 'apps',
  '/service/external': 'adapters',
  '/service/subscribe': 'subscriptions',
}
const analysis = [
  '/standard/benchmark',
  '/standard/code-benchmark',
  '/quality/timeliness',
  '/analysis/relations',
  '/analysis/funds',
  '/service/operations',
]
const reviews = [
  '/standard/approval',
  '/asset/approval',
  '/service/approval',
  '/service/view-audit',
  '/service/applications',
  '/service/authorized',
]
</script>
<template>
  <LocalAnalysisView v-if="analysis.includes(route.path)" /><LocalRecordsView
    v-else-if="managers[route.path]"
    :kind="managers[route.path]!"
  /><LocalReviewView v-else-if="reviews.includes(route.path)" /><LocalGraphView
    v-else-if="['/asset/map', '/asset/lineage'].includes(route.path)"
  /><LocalChainView v-else-if="route.path === '/quality/chain'" /><LocalDeliveryView
    v-else-if="route.path === '/service/push'"
  /><LocalContractView v-else-if="route.path === '/service/contracts'" />
</template>
