# backend/agent/tools/arxiv_search.py

"""arXiv 文献搜索工具

通过 arXiv 公开 API 搜索学术论文，返回标题、作者、摘要、链接等结构化信息。
适用于学术研究、文献调研、论文写作等场景。
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any

import requests

from backend.agent.tools.tools import tr

# arXiv API 端点
_ARXIV_API_URL = "http://export.arxiv.org/api/query"

# XML 命名空间
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

# 搜索字段前缀映射
_FIELD_PREFIX = {
    "all": "all",
    "title": "ti",
    "author": "au",
    "abstract": "abs",
    "category": "cat",
}

# 排序方式映射
_SORT_BY = {
    "relevance": "relevance",
    "lastUpdated": "lastUpdatedDate",
    "submitted": "submittedDate",
}

# 安全限制
_MAX_RESULTS_LIMIT = 20


def _build_search_query(query: str, search_field: str) -> str:
    """构建 arXiv 搜索查询字符串

    Args:
        query        : str => 搜索关键词
        search_field : str => 搜索字段

    Returns:
        str => arXiv 格式的搜索查询字符串
    """
    prefix = _FIELD_PREFIX.get(search_field, "all")
    # 同一字段的多词搜索使用 prefix:word1 word2 格式
    return f"{prefix}:{query}"


def _parse_entry(entry: ET.Element) -> dict[str, Any]:
    """解析单个 Atom entry 为结构化数据

    Args:
        entry: ET.Element => Atom entry 元素

    Returns:
        dict[str, Any] => 结构化论文信息
    """
    # 标题（去除多余空白）
    title_elem = entry.find("atom:title", _NS)
    title = " ".join(title_elem.text.split()) if title_elem is not None and title_elem.text else ""

    # 摘要（去除多余空白）
    summary_elem = entry.find("atom:summary", _NS)
    summary = (
        " ".join(summary_elem.text.split())
        if summary_elem is not None and summary_elem.text
        else ""
    )

    # 作者列表
    authors = []
    for author_elem in entry.findall("atom:author", _NS):
        name_elem = author_elem.find("atom:name", _NS)
        if name_elem is not None and name_elem.text:
            authors.append(name_elem.text)

    # arXiv ID 和链接
    id_elem = entry.find("atom:id", _NS)
    arxiv_url = id_elem.text.strip() if id_elem is not None and id_elem.text else ""
    # 从 URL 提取 arXiv ID (如 http://arxiv.org/abs/2301.00001v1 -> 2301.00001)
    arxiv_id = ""
    if arxiv_url:
        # 去掉版本号
        raw_id = arxiv_url.rsplit("/", 1)[-1]
        arxiv_id = raw_id.rsplit("v", 1)[0] if "v" in raw_id else raw_id

    # PDF 链接
    pdf_url = ""
    for link in entry.findall("atom:link", _NS):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            pdf_url = link.get("href", "")
            break

    # 发表日期和更新日期
    published_elem = entry.find("atom:published", _NS)
    published = published_elem.text.strip() if published_elem is not None and published_elem.text else ""

    updated_elem = entry.find("atom:updated", _NS)
    updated = updated_elem.text.strip() if updated_elem is not None and updated_elem.text else ""

    # 主分类
    primary_cat_elem = entry.find("arxiv:primary_category", _NS)
    primary_category = (
        primary_cat_elem.get("term", "") if primary_cat_elem is not None else ""
    )

    # 所有分类
    categories = [
        cat.get("term", "") for cat in entry.findall("atom:category", _NS) if cat.get("term")
    ]

    # 扩展字段（可选）
    comment_elem = entry.find("arxiv:comment", _NS)
    comment = comment_elem.text.strip() if comment_elem is not None and comment_elem.text else ""

    doi_elem = entry.find("arxiv:doi", _NS)
    doi = doi_elem.text.strip() if doi_elem is not None and doi_elem.text else ""

    journal_ref_elem = entry.find("arxiv:journal_ref", _NS)
    journal_ref = (
        journal_ref_elem.text.strip()
        if journal_ref_elem is not None and journal_ref_elem.text
        else ""
    )

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "authors": authors,
        "abstract": summary,
        "arxiv_url": arxiv_url,
        "pdf_url": pdf_url,
        "published": published,
        "updated": updated,
        "primary_category": primary_category,
        "categories": categories,
        "comment": comment,
        "doi": doi,
        "journal_ref": journal_ref,
    }


@tr.register(
    {
        "type": "function",
        "function": {
            "name": "arxiv_search",
            "description": (
                "搜索 arXiv 学术论文，返回标题、作者、摘要、PDF链接等结构化信息。"
                "适用于学术研究、文献调研、论文写作等场景。"
                "search_field 可选: all(全文), title(标题), author(作者), "
                "abstract(摘要), category(分类)。"
                "sort_by 可选: relevance(相关度), lastUpdated(最后更新), "
                "submitted(提交时间)。"
                "示例: 搜索大语言模型论文 query='large language model' "
                "search_field='all' sort_by='relevance'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如 'transformer attention' 或 'Yann LeCun'",
                    },
                    "search_field": {
                        "type": "string",
                        "enum": ["all", "title", "author", "abstract", "category"],
                        "description": "搜索字段: all=全文, title=标题, author=作者, abstract=摘要, category=分类。默认 all",
                        "default": "all",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数量，默认 5，最多 20",
                        "default": 5,
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["relevance", "lastUpdated", "submitted"],
                        "description": "排序方式: relevance=相关度, lastUpdated=最后更新时间, submitted=提交时间。默认 relevance",
                        "default": "relevance",
                    },
                    "sort_order": {
                        "type": "string",
                        "enum": ["ascending", "descending"],
                        "description": "排序方向: ascending=升序, descending=降序。默认 descending",
                        "default": "descending",
                    },
                },
                "required": ["query"],
            },
        },
    }
)
def arxiv_search(
    query: str,
    search_field: str = "all",
    max_results: int = 5,
    sort_by: str = "relevance",
    sort_order: str = "descending",
) -> dict[str, Any]:
    """搜索 arXiv 学术论文

    通过 arXiv 公开 API 搜索学术论文，返回结构化信息。

    Args:
        query        : str                     => 搜索关键词
        search_field : str = "all"             => 搜索字段
        max_results  : int = 5                 => 最大返回结果数量
        sort_by      : str = "relevance"       => 排序方式
        sort_order   : str = "descending"      => 排序方向

    Returns:
        dict[str, Any] => {
            "query": 搜索关键词,
            "search_field": 搜索字段,
            "total_results": 总匹配结果数,
            "result_count": 本次返回结果数,
            "results": 论文列表
        }
    """
    query = query.strip()
    if not query:
        raise ValueError("搜索关键词不能为空")

    max_results = max(1, min(max_results, _MAX_RESULTS_LIMIT))

    search_query = _build_search_query(query, search_field)
    sort_key = _SORT_BY.get(sort_by, "relevance")

    params: dict[str, str | int] = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_key,
        "sortOrder": sort_order,
    }

    # arXiv API 有速率限制和偶发超时，自动重试
    headers = {"User-Agent": "ESA-Agent/1.0 (Educational Study Agent)"}
    max_retries = 5
    response = None
    for attempt in range(max_retries):
        try:
            response = requests.get(
                _ARXIV_API_URL,
                params=params,
                headers=headers,
                timeout=60,
            )
            response.raise_for_status()
            break
        except requests.HTTPError as exc:
            if exc.response.status_code == 429 and attempt < max_retries - 1:
                time.sleep(10)
                continue
            status_code = exc.response.status_code
            raise RuntimeError(f"arXiv API 返回 HTTP {status_code}") from exc
        except requests.Timeout:
            if attempt < max_retries - 1:
                time.sleep(10)
                continue
            raise RuntimeError("arXiv API 请求超时（已重试 5 次）") from None
        except requests.RequestException as exc:
            raise RuntimeError(f"无法连接到 arXiv API：{exc}") from exc

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        raise RuntimeError(f"arXiv API 返回的 XML 解析失败：{exc}") from exc

    # OpenSearch 总结果数
    total_elem = root.find("opensearch:totalResults", _NS)
    total_results = int(total_elem.text) if total_elem is not None and total_elem.text else 0

    # 解析所有 entry
    entries = root.findall("atom:entry", _NS)
    results = [_parse_entry(entry) for entry in entries]

    return {
        "query": query,
        "search_field": search_field,
        "total_results": total_results,
        "result_count": len(results),
        "results": results,
    }
