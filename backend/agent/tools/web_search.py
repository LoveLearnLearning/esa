# backend/agnet/tools/web_search.py

from typing import Any

import requests

from backend.agent.tools.tools import tr

SEARXNG_BASE_URL = "http://127.0.0.1:8888"


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "通过互联网搜索信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索内容",
                    },
                    "max_results": {
                        "type": "int",
                        "description": "最大搜索结果，默认为 5 ",
                        "default": 5,
                    },
                    "language": {
                        "type": "string",
                        "description": "搜索结果便好语言，默认为中文",
                        "default": "zh-CN",
                    },
                    "time_range": {
                        "type": "string",
                        "enum": ["day", "month", "year"],
                        "description": "搜索时间范围，可选天月年",
                    },
                },
                "required": ["query"],
            },
        },
    }
)
def web_search(
    query: str,
    max_results: int = 5,
    language: str = "zh-CN",
    time_range: str | None = None,
) -> dict[str, Any]:
    """
    使用本地 SearXNG 搜索互联网
    Args:
        query       : str       => 搜索内容
        max_results : int = 5   => 最大搜索结果数量
        language    : str       => 搜索结果便好语言
        time_range  : str | None = None =>
            None: 不限制
            day: 最近一天
            month: 最近一个月
            year: 最近一年
    """
    query = query.strip()

    if not query:
        raise ValueError("搜索关键词不能为空")

    max_results = max(1, min(max_results, 20))

    params: dict[str, str | int] = {
        "q": query,
        "format": "json",
        "categories": "general",
        "language": language,
        "safesearch": 1,
    }

    if time_range in {"day", "month", "year"}:
        params["time_range"] = time_range

    try:
        response = requests.get(
            f"{SEARXNG_BASE_URL}/search",
            params=params,
            timeout=20,
        )

        response.raise_for_status()
        data = response.json()

    except requests.Timeout as exc:
        raise RuntimeError("搜索请求超时") from exc

    except requests.HTTPError as exc:
        status_code = exc.response.status_code

        if status_code == 403:
            message = (
                "SearXNG 禁止 JSON 输出，请检查 "
                "settings.yml 中是否启用了 search.formats.json"
            )
        else:
            message = f"SearXNG 返回 HTTP {status_code}"

        raise RuntimeError(message) from exc

    except requests.RequestException as exc:
        raise RuntimeError(f"无法连接到 SearXNG：{exc}") from exc

    except ValueError as exc:
        raise RuntimeError("SearXNG 返回的不是有效 JSON") from exc

    raw_results = data.get("results", [])

    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
            "engine": item.get("engine", ""),
            "engines": item.get("engines", []),
            "published_date": item.get("publishedDate"),
        }
        for item in raw_results[:max_results]
    ]

    return {
        "query": query,
        "result_count": len(results),
        "results": results,
        "suggestions": data.get("suggestions", []),
        "answers": data.get("answers", []),
        "unresponsive_engines": data.get(
            "unresponsive_engines",
            [],
        ),
    }
