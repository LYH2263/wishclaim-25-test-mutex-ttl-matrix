<template>
  <div>
    <button class="menu-btn ghost" @click="drawer=true">☰</button>
    <router-view />
    <button class="fab" title="发愿望" @click="$router.push('/compose')">＋</button>
    <div v-if="drawer" class="drawer-backdrop" @click="drawer=false"></div>
    <aside v-if="drawer" class="drawer">
      <h2 class="serif">我的</h2>
      <router-link to="/mine" @click="drawer=false">我的认领</router-link>
      <router-link to="/done" @click="drawer=false">已完成</router-link>
      <router-link to="/rules" @click="drawer=false">规则</router-link>
      <router-link to="/" @click="drawer=false">愿望墙</router-link>
    </aside>
  </div>
</template>
<script setup>
import { ref } from 'vue'
const drawer = ref(false)
</script>
