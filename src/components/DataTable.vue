<script setup lang="ts">
import type { Entity } from '../api/client'
defineProps<{
  rows: Entity[]
  columns: { key: string; label: string }[]
  loading?: boolean
  empty?: string
}>()
</script>
<template>
  <div class="table-wrap" :aria-busy="loading">
    <table>
      <thead>
        <tr>
          <th v-for="c in columns" :key="c.key">{{ c.label }}</th>
          <th v-if="$slots.actions" class="actions-head">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(r, i) in rows" :key="r.id || i">
          <td v-for="c in columns" :key="c.key">
            <slot :name="c.key" :row="r">{{ r[c.key] ?? '—' }}</slot>
          </td>
          <td v-if="$slots.actions">
            <div class="row-actions"><slot name="actions" :row="r" /></div>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-if="loading" class="empty">正在读取数据…</div>
    <div v-else-if="!rows.length" class="empty">
      <span class="empty-symbol">◇</span>{{ empty || '暂无记录，点击新增开始配置' }}
    </div>
  </div>
</template>
