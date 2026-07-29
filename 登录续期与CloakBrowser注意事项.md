# 登录续期与 CloakBrowser 注意事项

## 一、先明确认证数据

脚本实际使用的是请求头中的 `authorization`，不是浏览器 Cookie。
浏览器 Cookie 和 Cloudflare `cf_clearance` 只负责让浏览器进入 Picix 登录页；
Telegram 登录成功后，Picix 返回的新 `authorization` 才是自动解锁接口使用的凭证。

新的凭证会保存到：

```text
unlock_data/authorization.json
```

该目录已被 `.gitignore` 排除。不要把此文件、Bot Token、登录码或 API 日志提交到仓库或转发给他人。

## 二、认证失效后的正确流程

1. 定时任务发现 Picix API 返回 401/403。
2. 机器人请求公开接口 `/api/Users/getLoginCode`，生成新的动态登录码。
3. 机器人只向已配置的允许用户发送：

   ```text
   /login 12345678
   ```

4. 用户把整行指令发送给 Picix 官方认证 Bot：`@vStreamingBot`。
5. 也可以点击机器人消息中的按钮，打开：

   ```text
   https://t.me/vStreamingBot?start=login_12345678
   ```

6. 本机器人每 2 秒轮询 `/api/Users/checkLoginCode`。
7. 用户认证成功后，机器人自动保存并立即启用新的 `authorization`，无需修改源码或重启。

登录码是动态生成的，不要硬编码，也不要重复使用旧通知里的登录码。默认等待 10 分钟；
超时后发送 `/reauth` 获取新指令。

## 三、Telegram Bot 使用要求

- 使用 `/reauth` 可以随时手动生成新登录指令。
- 必须正确配置 `ALLOWED_USER_IDS` 或 `unlock_data/bot_config.json` 中的 `user_ids`。
- `/setuser` 只用于允许列表为空时的首次初始化；列表建立后，陌生用户不能自助加入。
- 登录指令只能发送给可信用户；任何能操作该认证流程的人，都可能取得 Picix 账号访问权限。
- 同一时间只运行一个认证流程，避免多个登录码互相覆盖。
- 认证成功通知出现前，不要关闭机器人进程。

## 四、CloakBrowser 与 Cloudflare

实测旧免费版 CloakBrowser Chromium 146 可以通过 Picix Cloudflare，但启动顺序必须正确：

```text
CloakBrowser 用全新持久化 Profile 启动
→ Cloak 自己访问 Picix
→ Cloak 的 humanize 层完成验证
→ 写入就绪状态
→ Chrome DevTools MCP 再连接接管
```

以下参数经过对照测试，不是被拦截的原因：

- `--remote-debugging-address=127.0.0.1`
- `--remote-debugging-port=9242`
- 固定的 `--fingerprint=<seed>`
- `--fingerprint-platform=windows`

此前失败的原因是 DevTools MCP 在 Cloak 预热前直接导航，并复用了已经进入挑战循环的旧 Profile。
`humanize=True` 是 Cloak Python 包装层能力；外部 CDP 客户端的操作不会自动经过该层。

当前启动器只使用 `cloakbrowser_profile_v2`，先预热 Picix，再允许 MCP 接入。
旧的 `cloakbrowser_profile` 已清理，不要手动恢复或复用。

## 五、网络与进程注意事项

- 项目统一使用 uv；Bot 运行在 `.venv`，CloakBrowser 运行在独立的
  `.venv-cloak`。Bot 使用根目录锁文件，浏览器使用
  `tools/cloak_runtime/uv.lock`，依赖不会混装。
- CloakBrowser 启动器会自动同步浏览器子项目。首次启动需要下载依赖，
  之后复用 uv 缓存。
- CDP 仅监听 `127.0.0.1:9242`，不要改成 `0.0.0.0` 或暴露到公网。
- CDP 可以读取页面、执行脚本和控制浏览器，暴露端口等同于交出浏览器控制权。
- 保留同一个 Profile 和指纹 seed，避免 Cloudflare 看到身份频繁变化。
- 不要同时启动多个使用同一 Profile 的 CloakBrowser 进程。
- 浏览器预热结果写入：

  ```text
  unlock_data/cloakbrowser_cdp_ready.json
  ```

- 启动问题查看：

  ```text
  unlock_data/cloakbrowser_stdout.log
  unlock_data/cloakbrowser_stderr.log
  ```

## 六、故障处理

- Cloudflare 再次循环：关闭占用 9242 端口的旧 CloakBrowser，确认启动器使用 `cloakbrowser_profile_v2`，然后重启 Codex。
- Bot 未发送登录指令：确认已设置通知用户，并查看 `unlock_data/auth_notification_log.json`。
- 登录码超时：发送 `/reauth`，不要继续使用旧码。
- 用户已认证但恢复失败：检查网络后再次发送 `/reauth`；不要手工把 token 发到 Telegram 或聊天记录中。
- 新凭证已保存但接口仍返回 401/403：检查 `unlock_data/authorization.json` 是否可读，并重新启动机器人加载持久化值。
