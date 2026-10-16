<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
const props = defineProps<{ open: boolean; title: string; wide?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>()
const sync = () => {
  if (props.open && !dialog.value?.open) dialog.value?.showModal()
  else if (!props.open && dialog.value?.open) dialog.value.close()
}
watch(() => props.open, sync)
onMounted(sync)
onUnmounted(() => dialog.value?.close())
</script>
<template>
  <dialog ref="dialog" :class="{ wide }" @cancel.prevent="emit('close')">
    <div class="modal-head">
      <h2>{{ title }}</h2>
      <button class="icon-button" aria-label="关闭" @click="emit('close')">×</button>
    </div>
    <slot />
  </dialog>
</template>
