# 前端控制台

本目录实现 P2-W01 的 Vue 3 前端基础：内存认证会话、令牌刷新、统一请求层、
路由认证与权限守卫、权限菜单、认证服务器发送事件、短时签名地址和
1920×1080 工位布局。

构建基线按项目决策锁定为 Node.js 20.13.1 和 pnpm 10.34.5。网络状态与接口
类型从 `packages/typescript-contracts/` 生成包导入；前端只展示后端返回的
最终处置，隐藏按钮不能替代后端鉴权。

浏览器使用 OIDC 授权码与 PKCE。访问令牌和刷新令牌只保存在内存；为跨越
授权跳转，标签页会话存储仅暂存一次性的 `state`、PKCE 校验器和站内返回路径，
回调读取前即删除。运行环境必须提供以下配置，缺失时登录明确失败，不回退到
示例身份服务：

```text
VITE_API_BASE_URL
VITE_OIDC_AUTHORIZATION_ENDPOINT
VITE_OIDC_TOKEN_ENDPOINT
VITE_OIDC_USERINFO_ENDPOINT
VITE_OIDC_REVOCATION_ENDPOINT（可选）
VITE_OIDC_CLIENT_ID
VITE_OIDC_REDIRECT_URI（可选，默认同源 /auth/callback）
VITE_OIDC_SCOPES（可选）
```

验证命令：

```text
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build
```
