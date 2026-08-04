# BSC address monitor

监控指定地址作为 `from` 发起的 BSC 主网交易：BNB 转出、合约调用、授权和可识别的 BEP-20 转账事件。

## 部署

```bash
cp .env.example .env
# 编辑 .env，填写 WEBHOOK_URL 或 Telegram 配置
docker compose up -d --build
docker compose logs -f
```

程序首次启动会把当前区块设为基线，不会补发历史交易；之后从新区块中发现主动操作就推送。状态保存在 `./data/state.json`。

生产环境建议把 `BSC_RPC_URL` 换成你自己的 RPC 服务地址，避免公共 RPC 限流。
