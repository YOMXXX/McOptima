"""McOptima - 麦当劳 MCP 客户端封装.

对接麦当劳中国官方 MCP Server (https://mcp.mcd.cn, Streamable HTTP)。
Token 仅从环境变量 MCD_MCP_TOKEN 读取，绝不硬编码、绝不入库。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

MCP_URL = "https://mcp.mcd.cn"
RATE_LIMIT_MAX_PER_MIN = 600


class McpError(RuntimeError):
    """MCP 调用异常。"""


class McpAuthError(McpError):
    """Token 无效或过期 (401)。"""


class McpRateLimitError(McpError):
    """触发限流 (429, >600 req/min)。"""


@dataclass
class McpCallStats:
    calls: int = 0
    errors: int = 0
    _window_start: float = field(default_factory=time.time)
    _window_calls: int = 0

    def tick(self) -> None:
        now = time.time()
        if now - self._window_start >= 60:
            self._window_start = now
            self._window_calls = 0
        self._window_calls += 1
        self.calls += 1
        if self._window_calls > RATE_LIMIT_MAX_PER_MIN:
            raise McpRateLimitError(
                f"本地限流保护: 当前窗口已 {self._window_calls} 次调用, 官方上限 {RATE_LIMIT_MAX_PER_MIN}/min"
            )


class McdMcpClient:
    """麦当劳 MCP Server 的轻量 JSON-RPC 客户端 (无第三方依赖)."""

    def __init__(self, token: str | None = None, url: str = MCP_URL) -> None:
        self.token = token or os.environ.get("MCD_MCP_TOKEN", "")
        if not self.token:
            raise McpAuthError(
                "缺少 MCP Token: 请在环境变量 MCD_MCP_TOKEN 中设置 "
                "(申请入口 https://open.mcd.cn/mcp)"
            )
        self.url = url
        self._id = 0
        self.stats = McpCallStats()
        self._initialized = False

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {self.token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise McpAuthError("401: MCP Token 无效、已过期或未提供") from e
            if e.code == 429:
                raise McpRateLimitError("429: 触发官方限流 (600 req/min), 请降低频率") from e
            raise McpError(f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}") from e
        except urllib.error.URLError as e:
            raise McpError(f"网络错误: {e}") from e

        # 服务端可能返回 SSE 格式 (event: message\ndata: {...}) 或纯 JSON
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                line = line[len("data:"):].strip()
            if line.startswith("{"):
                return json.loads(line)
        raise McpError(f"无法解析响应: {raw[:200]}")

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "mcoptima", "version": "0.1.0"},
                },
            }
        )
        self._initialized = True

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用 MCP tool 并返回解析后的原始业务 JSON (Original Response 中的 data 部分)."""
        self._ensure_initialized()
        self.stats.tick()
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        result = self._post(payload)
        if "error" in result:
            self.stats.errors += 1
            raise McpError(f"MCP 错误: {result['error']}")
        content = result.get("result", {}).get("content", [])
        if not content:
            raise McpError(f"工具 {name} 返回空内容")
        text = content[0].get("text", "")
        if result.get("result", {}).get("isError"):
            raise McpError(f"工具 {name} 执行失败: {text[:300]}")
        return self._extract_original(text, name)

    def _extract_original(self, text: str, name: str) -> dict[str, Any]:
        """从 LLM 友好的响应文本中提取 Original Response JSON."""
        # 优先找 "## Original Response" 段落
        m = re.search(r"## Original Response\s*\n\s*(\{.*\})\s*$", text, re.S)
        if m:
            return json.loads(m.group(1))
        # 兜底: 找第一个 {"success": ...} JSON
        m = re.search(r'\{"success".*\}', text, re.S)
        if m:
            return json.loads(m.group(0))
        raise McpError(f"工具 {name} 响应中未找到业务 JSON: {text[:200]}")


def business_data(response: dict[str, Any]) -> Any:
    """取 MCP 响应中的 data 字段, 失败时抛出带 message 的异常."""
    if not response.get("success", False):
        raise McpError(f"业务失败: code={response.get('code')} message={response.get('message')}")
    return response.get("data")


# ---------- 高层业务封装 ----------

class McdService:
    """面向求解器的业务门面: 缓存 + 常用查询组合."""

    def __init__(self, client: McdMcpClient, cache_dir: str = "data/cache") -> None:
        self.client = client
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _cache_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.json")

    def _load_cache(self, key: str, max_age_sec: int) -> dict[str, Any] | None:
        path = self._cache_path(key)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            wrapper = json.load(f)
        if time.time() - wrapper.get("ts", 0) > max_age_sec:
            return None
        return wrapper.get("data")

    def _save_cache(self, key: str, data: Any) -> None:
        with open(self._cache_path(key), "w") as f:
            json.dump({"ts": time.time(), "data": data}, f, ensure_ascii=False, indent=1)

    def query(self, key: str, tool: str, arguments: dict[str, Any], max_age_sec: int = 3600, use_cache: bool = True) -> Any:
        if use_cache:
            cached = self._load_cache(key, max_age_sec)
            if cached is not None:
                return cached
        data = business_data(self.client.call_tool(tool, arguments))
        self._save_cache(key, data)
        return data

    # 常用查询
    def nutrition(self) -> list[dict[str, Any]]:
        return self.query("nutrition", "list-nutrition-foods", {}, max_age_sec=86400)

    def nearby_stores(self, city: str, keyword: str, be_type: int = 1) -> list[dict[str, Any]]:
        return self.query(
            f"stores_{city}_{keyword}_{be_type}",
            "query-nearby-stores",
            {"beType": be_type, "searchType": 2, "city": city, "keyword": keyword},
            max_age_sec=86400,
        )

    def menu(self, store_code: str, be_type: int = 1, order_type: int = 1) -> dict[str, Any]:
        return self.query(
            f"menu_{store_code}_{be_type}_{order_type}",
            "query-meals",
            {"storeCode": store_code, "orderType": order_type, "beType": be_type},
            max_age_sec=3600,
        )

    def meal_detail(self, store_code: str, code: str, be_type: int = 1, order_type: int = 1) -> dict[str, Any]:
        return self.query(
            f"meal_{store_code}_{code}",
            "query-meal-detail",
            {"storeCode": store_code, "orderType": order_type, "beType": be_type, "code": code},
            max_age_sec=3600,
        )

    def store_coupons(self, store_code: str, be_type: int = 1, order_type: int = 1) -> list[dict[str, Any]]:
        return self.query(
            f"coupons_{store_code}_{be_type}_{order_type}",
            "query-store-coupons",
            {"storeCode": store_code, "orderType": order_type, "beType": be_type},
            max_age_sec=1800,
        )

    def calculate_price(self, store_code: str, items: list[dict[str, Any]], be_type: int = 1, order_type: int = 1) -> Any:
        """价格计算属实时数据, 不走缓存."""
        return business_data(
            self.client.call_tool(
                "calculate-price",
                {
                    "storeCode": store_code,
                    "orderType": order_type,
                    "beType": be_type,
                    "items": items,
                },
            )
        )
