import { createRouter, createWebHistory } from 'vue-router'
import Wall from './pages/Wall.vue'
import Detail from './pages/Detail.vue'
import Compose from './pages/Compose.vue'
import Mine from './pages/Mine.vue'
import Done from './pages/Done.vue'
import Rules from './pages/Rules.vue'
export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Wall },
    { path: '/wishes/:id', component: Detail, props: true },
    { path: '/compose', component: Compose },
    { path: '/mine', component: Mine },
    { path: '/done', component: Done },
    { path: '/rules', component: Rules },
  ],
})
