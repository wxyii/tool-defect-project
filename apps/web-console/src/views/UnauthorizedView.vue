<template>
  <section class="empty-state" role="alert">
    <p class="eyebrow">访问被拒绝</p>
    <h2>当前账号没有访问此功能的权限</h2>
    <p>菜单隐藏不能替代后端鉴权，本次访问未执行任何业务操作。</p>
    <RouterLink to="/workstation">返回工位页</RouterLink>
  </section>
</template>
