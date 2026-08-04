import json
import os
import time
import urllib.request
from datetime import datetime, timezone

ADDRESS = os.environ.get("WATCH_ADDRESS", "0x28816c4C4792467390C90e5B426F198570E29307").lower()
RPC_URL = os.environ.get("BSC_RPC_URL", "https://bsc-dataseed.binance.org")
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "5"))
STATE_FILE = os.environ.get("STATE_FILE", "/data/state.json")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55aeb"
METHODS = {
    "095ea7b3": "approve",
    "a9059cbb": "transfer",
    "23b872dd": "transferFrom",
    "38ed1739": "swapExactTokensForTokens",
    "7ff36ab5": "swapExactETHForTokens",
    "18cbafe5": "swapExactTokensForETH",
    "791ac947": "swapExactTokensForETHSupportingFeeOnTransferTokens",
    "b6f9de95": "swapExactETHForTokensSupportingFeeOnTransferTokens",
}


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC_URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.loads(response.read())
    if "error" in result:
        raise RuntimeError(result["error"])
    return result["result"]


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"last_block": None, "seen": []}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    state["seen"] = state["seen"][-2000:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def topic_address(topic):
    return "0x" + topic[-40:].lower() if topic else ""


def describe(tx, receipt, block):
    data = (tx.get("input") or "")[2:]
    method_id = data[:8].lower()
    method = METHODS.get(method_id, "contract_call" if data else "BNB_transfer")
    token_transfers = []
    for log in receipt.get("logs", []):
        topics = log.get("topics", [])
        if len(topics) >= 3 and topics[0].lower().startswith(TRANSFER_TOPIC):
            sender, recipient = topic_address(topics[1]), topic_address(topics[2])
            if sender == ADDRESS:
                token_transfers.append({"token": log.get("address"), "to": recipient, "raw": int(topics[3], 16) if len(topics) > 3 else None})
    return {
        "hash": tx["hash"],
        "block": int(tx["blockNumber"], 16),
        "time": datetime.fromtimestamp(int(block["timestamp"], 16), timezone.utc).isoformat(),
        "to": tx.get("to"),
        "method": method,
        "value_bnb": int(tx.get("value", "0"), 16) / 10**18,
        "status": "success" if receipt.get("status") == "0x1" else "failed",
        "token_transfers": token_transfers,
        "url": "https://bscscan.com/tx/" + tx["hash"],
    }


def format_message(item):
    lines = [
        "🔔 BSC 主动操作",
        f"时间: {item['time']}",
        f"类型: {item['method']} ({item['status']})",
        f"目标: {item['to'] or '(合约创建)'}",
        f"BNB: {item['value_bnb']:.8f}",
    ]
    for transfer in item["token_transfers"]:
        amount = transfer["raw"] if transfer["raw"] is not None else "?"
        lines.append(f"Token: {transfer['token']} → {transfer['to']}，raw={amount}")
    lines.append(f"交易: {item['url']}")
    return "\n".join(lines)


def notify(message):
    print(message, flush=True)
    payload = json.dumps({"content": message, "text": message}).encode()
    if WEBHOOK_URL:
        req = urllib.request.Request(WEBHOOK_URL, payload, {"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as exc:
            print(f"webhook error: {exc}", flush=True)
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        body = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message, "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as exc:
            print(f"telegram error: {exc}", flush=True)


def main():
    print(f"Watching {ADDRESS} on BSC via {RPC_URL}", flush=True)
    state = load_state()
    while True:
        try:
            latest = int(rpc("eth_blockNumber", []), 16)
            if state["last_block"] is None:
                state["last_block"] = latest
                save_state(state)
                print(f"Baseline set at block {latest}", flush=True)
            else:
                start = max(state["last_block"] + 1, latest - 100)
                for number in range(start, latest + 1):
                    block = rpc("eth_getBlockByNumber", [hex(number), True])
                    if not block:
                        continue
                    for tx in block.get("transactions", []):
                        if (tx.get("from") or "").lower() != ADDRESS or tx["hash"] in state["seen"]:
                            continue
                        receipt = rpc("eth_getTransactionReceipt", [tx["hash"]])
                        item = describe(tx, receipt, block)
                        notify(format_message(item))
                        state["seen"].append(tx["hash"])
                    state["last_block"] = number
                    save_state(state)
            time.sleep(POLL_SECONDS)
        except Exception as exc:
            print(f"check error: {exc}", flush=True)
            time.sleep(max(POLL_SECONDS, 10))


if __name__ == "__main__":
    main()
