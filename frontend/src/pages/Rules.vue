<template>
  <div class="wall">
    <h1 class="serif">规则</h1>
    <ul>
      <li v-for="(v,k) in rules" :key="k"><strong>{{ k }}</strong>：{{ v }}</li>
    </ul>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const rules = ref({})
onMounted(async () => { rules.value = await api('/rules') })
</script>
