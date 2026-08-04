# BSC address monitor

监控多个指定地址作为 `from` 发起的 BSC 主网交易：BNB 转出、合约调用、授权和可识别的 BEP-20 转账事件。

## 添加地址

编辑 `addresses.json`，每个地址一项：

```json
[
  {"name": "主钱包", "address": "0x28816c4C4792467390C90e5B426F198570E29307"},
  {"name": "交易钱包", "address": "0x你的地址"}
]
```

保存后程序会自动读取新配置。新增地址从当前最新区块建立基线，不会补发历史交易；已有地址的进度保存在 `./data/state.json`。

## 部署

```bash
cp .env.example .env
# 编辑 .env，填写 WEBHOOK_URL 或 Telegram 配置
docker compose up -d --build
docker compose logs -f
```

程序首次启动会把当前区块设为基线，不会补发历史交易；之后从新区块中发现主动操作就推送。状态保存在 `./data/state.json`。

生产环境建议把 `BSC_RPC_URL` 换成你自己的 RPC 服务地址，避免公共 RPC 限流。
