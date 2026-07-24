import { createRouter, createWebHistory } from "vue-router"

import AppLayout from "@/layouts/AppLayout.vue"
import ConnectionView from "@/views/ConnectionView.vue"

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/connect", name: "connect", component: ConnectionView },
    {
      path: "/",
      component: AppLayout,
      children: [
        {
          path: "",
          name: "dashboard",
          component: () => import("@/views/DashboardView.vue"),
        },
        {
          path: "test",
          name: "test",
          component: () => import("@/views/ParseTestView.vue"),
        },
        {
          path: "tasks",
          name: "tasks",
          component: () => import("@/views/TasksView.vue"),
        },
        {
          path: "tasks/:taskId",
          name: "task-detail",
          component: () => import("@/views/TaskDetailView.vue"),
        },
        {
          path: "management/:section",
          name: "management",
          component: () => import("@/views/ManagementView.vue"),
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  if (to.name !== "connect" && !sessionStorage.getItem("parser-serve-connection")) {
    return { name: "connect" }
  }
})

export default router
