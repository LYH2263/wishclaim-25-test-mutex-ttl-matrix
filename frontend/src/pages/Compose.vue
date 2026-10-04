<template>
  <div class="wall">
    <h1 class="serif">发愿望</h1>
    <input v-model="title" placeholder="标题" />
    <textarea v-model="note" rows="4" placeholder="备注" />
    <button @click="submit">发布</button>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
const router = useRouter()
const title = ref('')
const note = ref('')
async function submit() {
  const r = await api('/wishes', { method: 'POST', body: JSON.stringify({ title: title.value, note: note.value }) })
  router.push('/wishes/' + r.id)
}
</script>
