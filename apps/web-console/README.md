# 前端控制台

本目录实现 Vue 3 前端基础：同源本地账号会话、统一请求层、
路由认证与权限守卫、权限菜单、认证服务器发送事件、短时签名地址和
1920×1080 工位布局。

构建基线按项目决策锁定为 Node.js 20.13.1 和 pnpm 10.34.5。网络状态与接口
类型从 `packages/typescript-contracts/` 生成包导入；前端只展示后端返回的
最终处置，隐藏按钮不能替代后端鉴权。

浏览器通过同源业务接口完成账号密码登录。会话标识使用仅服务器可读的安全
浏览器标识，改变状态的请求携带请求来源校验令牌；前端不读取或持久化会话值。
业务接口不允许配置为跨源地址。

```text
VITE_API_BASE_URL
```

验证命令：

```text
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
```
