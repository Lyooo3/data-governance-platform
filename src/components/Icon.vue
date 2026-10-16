<script setup lang="ts">
defineProps<{ name: string; size?: number }>()
const shapes: Record<string, string> = {
  home: 'M3 10 12 3l9 7v11h-6v-7H9v7H3Z',
  standard: 'M5 3h14v18H5ZM8 7h8M8 11h8M8 15h5',
  access: 'M7 3v6m10-6v6M4 9h16v5a8 8 0 0 1-16 0ZM12 22v-5',
  flow: 'M3 3h6v6H3ZM15 15h6v6h-6ZM6 9v9h9M15 3h6v6h-6ZM9 6h6',
  quality: 'M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6ZM7 12l3 3 7-7',
  asset: 'm12 2 10 6-10 6L2 8Zm-10 10 10 6 10-6M2 16l10 6 10-6',
  service:
    'm10 14 4-4M8 16l-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0M16 8l2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0',
  settings:
    'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2',
  plus: 'M12 4v16M4 12h16',
  search: 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14m5 12 6 6',
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  play: 'm6 3 15 9-15 9Z',
  refresh: 'M20 8A9 9 0 1 0 21 15M20 2v6h-6',
  check: 'm4 12 5 5L20 6',
  close: 'm5 5 14 14M19 5 5 19',
  user: 'M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8M4 21v-2a8 8 0 0 1 16 0v2',
  bell: 'M5 17h14l-2-4V8a5 5 0 0 0-10 0v5ZM10 21h4',
  clock: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20m0 4v6l4 2',
  database: 'M3 6a9 4 0 1 0 18 0A9 4 0 1 0 3 6m0 0v12a9 4 0 0 0 18 0V6M3 12a9 4 0 0 0 18 0',
}
</script>
<template>
  <svg
    :width="size || 18"
    :height="size || 18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path :d="shapes[name] || shapes.standard" />
  </svg>
</template>
