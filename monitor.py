import json
import os
import time
import urllib.request
from datetime import datetime, timezone

RPC_URL = os.environ.get("BSC_RPC_URL", "https://bsc-dataseed.binance.org")
ADDRESSES_FILE = os.environ.get("ADDRESSES_FILE", "/app/addresses.json")
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


def load_watchlist():
    with open(ADDRESSES_FILE, "r", encoding="utf-8") as f:
        entries = json.load(f)
    if not isinstance(entries, list) or not entries:
        raise ValueError("addresses.json must contain at least one address")
    watches = {}
    for entry in entries:
        address = entry["address"].lower()
        if not address.startswith("0x") or len(address) != 42:
            raise ValueError(f"Invalid address: {address}")
        watches[address] = entry.get("name", address[:10] + "...")
    return watches


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        return {"addresses": {}}
    # Migrate the original single-address state format automatically.
    if "addresses" not in state:
        old_address = os.environ.get("WATCH_ADDRESS", "").lower()
        return {"addresses": {old_address: {"last_block": state.get("last_block"), "seen": state.get("seen", [])}}}
    return state


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    for address_state in state["addresses"].values():
        address_state["seen"] = address_state.get("seen", [])[-2000:]
    temp_file = STATE_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(temp_file, STATE_FILE)


def topic_address(topic):
    return "0x" + topic[-40:].lower() if topic else ""


def describe(tx, receipt, block, address):
    data = (tx.get("input") or "")[2:]
    method_id = data[:8].lower()
    method = METHODS.get(method_id, "contract_call" if data else "BNB_transfer")
    token_transfers = []
    for log in receipt.get("logs", []):
        topics = log.get("topics", [])
        if len(topics) >= 3 and topics[0].lower() == TRANSFER_TOPIC:
            sender, recipient = topic_address(topics[1]), topic_address(topics[2])
            if sender == address:
                token_transfers.append({"token": log.get("address"), "to": recipient, "raw": int(topics[3], 16) if len(topics) > 3 else None})
    return {
        "hash": tx["hash"],
        "time": datetime.fromtimestamp(int(block["timestamp"], 16), timezone.utc).isoformat(),
        "to": tx.get("to"),
        "method": method,
        "value_bnb": int(tx.get("value", "0"), 16) / 10**18,
        "status": "success" if receipt.get("status") == "0x1" else "failed",
        "token_transfers": token_transfers,
        "url": "https://bscscan.com/tx/" + tx["hash"],
    }


def format_message(item, name, address):
    lines = [
        "🔔 BSC 主动操作",
        f"地址: {name} ({address})",
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
    if WEBHOOK_URL:
        payload = json.dumps({"content": message, "text": message}).encode()
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
    print(f"Watching addresses in {ADDRESSES_FILE} on BSC via {RPC_URL}", flush=True)
    state = load_state()
    while True:
        try:
            watches = load_watchlist()
            for address in watches:
                state["addresses"].setdefault(address, {"last_block": None, "seen": []})
            latest = int(rpc("eth_blockNumber", []), 16)
            active = {address: state["addresses"][address] for address in watches}
            baseline_addresses = [s for s in active.values() if s["last_block"] is None]
            for address_state in baseline_addresses:
                address_state["last_block"] = latest
            if baseline_addresses:
                save_state(state)
                print(f"Baseline set at block {latest} for {len(baseline_addresses)} address(es)", flush=True)
            starts = [s["last_block"] + 1 for s in active.values()]
            start = min(starts) if starts else latest + 1
            start = max(start, latest - 100)
            for number in range(start, latest + 1):
                block = rpc("eth_getBlockByNumber", [hex(number), True])
                if not block:
                    continue
                for tx in block.get("transactions", []):
                    sender = (tx.get("from") or "").lower()
                    if sender not in active or tx["hash"] in active[sender]["seen"]:
                        continue
                    receipt = rpc("eth_getTransactionReceipt", [tx["hash"]])
                    item = describe(tx, receipt, block, sender)
                    notify(format_message(item, watches[sender], sender))
                    active[sender]["seen"].append(tx["hash"])
                for address_state in active.values():
                    if address_state["last_block"] < number:
                        address_state["last_block"] = number
                save_state(state)
            time.sleep(POLL_SECONDS)
        except Exception as exc:
            print(f"check error: {exc}", flush=True)
            time.sleep(max(POLL_SECONDS, 10))


if __name__ == "__main__":
    main()
