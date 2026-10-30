"""网络热梗数据源模块。

负责从本地 JSON 文件与远程 URL 加载、去重合并并维护「网络热梗库」，
为关键词匹配、随机调用与 /hotmeme 命令提供时效性数据。

设计要点：
1. 不依赖 AstrBot 运行时，仅使用标准库（json / urllib / logging），便于单独测试与复用。
2. 所有网络 / 解析 / 文件 IO 异常均在内部捕获并记录告警，绝不向上抛出导致插件
   崩溃；失败时保留已有数据（绝不因网络问题清空/污染梗库）。
3. 条目按 name 去重合并：列表字段（keywords/fuzzy/replies/examples）追加去重，
   标量字段（meaning/source/platform/heat/updated_at）以新数据覆盖。

条目 schema：{name, keywords:[], fuzzy:[], replies:[], meaning, source,
platform, heat, updated_at, examples:[]}。
"""

import json
import logging
import os
import random
from urllib.request import Request, urlopen

# 列表型字段：合并时追加去重；其余标量字段以新值覆盖
_LIST_FIELDS = ("keywords", "fuzzy", "replies", "examples")
_SCALAR_FIELDS = ("meaning", "source", "platform", "heat", "updated_at")

_DEFAULT_UA = "AstrBot-hot-meme/1.1.0"


class HotMemeSource:
    """网络热梗数据源（尽量与 AstrBot 解耦，便于单测）。"""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("hot_meme.hot_source")
        self.entries: dict[str, dict] = {}
        # 简单统计：文件/URL 加载次数与错误次数，便于日志与测试
        self.stats: dict[str, int] = {"files": 0, "urls": 0, "errors": 0}

    # ------------------------------------------------------------------
    # 加载入口
    # ------------------------------------------------------------------
    def refresh(self, urls=(), files=()) -> None:
        """先加载本地文件，再拉取远程 URL；单个失败不影响整体。"""
        for path in (files or []):
            self.load_file(path)
        for url in (urls or []):
            self.fetch_url(url)

    def load_file(self, path) -> int:
        """从 JSON 文件加载热梗，返回新增条目数；失败返回 0 并保留现有数据。"""
        if not path or not os.path.isfile(path):
            self.logger.warning("热梗数据文件不存在，跳过：%s", path)
            return 0
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            added = self._ingest(data)
            self.stats["files"] += 1
            return added
        except Exception as exc:  # 文件 IO / JSON 解析等
            self.stats["errors"] += 1
            self.logger.warning("读取/解析热梗数据文件失败 %s：%s", path, exc)
            return 0

    def fetch_url(self, url, timeout: float = 10.0) -> int:
        """通过 HTTP GET 拉取远程 JSON 并合并，返回新增条目数；失败返回 0。"""
        if not url:
            return 0
        try:
            req = Request(url, headers={"User-Agent": _DEFAULT_UA})
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            added = self._ingest(json.loads(raw))
            self.stats["urls"] += 1
            return added
        except Exception as exc:  # 网络 / 超时 / 解析等
            self.stats["errors"] += 1
            self.logger.warning("拉取热梗数据源失败 %s：%s", url, exc)
            return 0

    # ------------------------------------------------------------------
    # 解析与合并
    # ------------------------------------------------------------------
    def _ingest(self, data) -> int:
        """解析数据并合并进 entries，返回新增条目数。"""
        items = self._extract_items(data)
        added = 0
        for raw in items:
            entry = self._normalize(raw)
            if entry is None:
                continue
            name = entry["name"]
            if name in self.entries:
                self._merge(self.entries[name], entry)
            else:
                self.entries[name] = entry
                added += 1
        return added

    @staticmethod
    def _extract_items(data) -> list:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "memes", "entries", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
            # 形如 {name: {...}} 的映射
            if data and all(isinstance(v, dict) for v in data.values()):
                return [{"name": k, **v} for k, v in data.items()]
            # 单条条目
            return [data]
        return []

    @staticmethod
    def _str_list(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple)):
            return [str(x).strip() for x in value if str(x).strip()]
        return [str(value)]

    @classmethod
    def _normalize(cls, raw) -> dict | None:
        if not isinstance(raw, dict):
            return None
        name = str(raw.get("name") or "").strip()
        if not name:
            return None
        heat = raw.get("heat")
        return {
            "name": name,
            "keywords": cls._str_list(raw.get("keywords")),
            "fuzzy": cls._str_list(raw.get("fuzzy")),
            "replies": cls._str_list(raw.get("replies")),
            "meaning": str(raw.get("meaning") or "").strip(),
            "source": str(raw.get("source") or "").strip(),
            "platform": str(raw.get("platform") or "").strip(),
            "heat": heat if heat is not None else 0,
            "updated_at": str(raw.get("updated_at") or "").strip(),
            "examples": cls._str_list(raw.get("examples")),
        }

    @staticmethod
    def _merge(old: dict, new: dict) -> None:
        for field in _LIST_FIELDS:
            merged = list(old.get(field) or []) + list(new.get(field) or [])
            old[field] = list(dict.fromkeys(merged))
        for field in _SCALAR_FIELDS:
            if new.get(field) not in (None, "", []):
                old[field] = new[field]

    # ------------------------------------------------------------------
    # 查询 / 随机 / 输出
    # ------------------------------------------------------------------
    def to_engine(self) -> dict[str, dict]:
        """转换为匹配引擎可用的条目结构（key=name）。"""
        result = {}
        for name, entry in self.entries.items():
            result[name] = {
                "keywords": list(entry.get("keywords") or []),
                "fuzzy": list(entry.get("fuzzy") or []),
                "context": [],
                "negative": [],
                "replies": list(entry.get("replies") or []),
            }
        return result

    def find(self, keyword: str) -> dict | None:
        """按 name / keywords / fuzzy 查找热梗，返回条目或 None。"""
        kw = (keyword or "").strip().casefold()
        if not kw:
            return None
        # 首选精确相等
        for name, entry in self.entries.items():
            if name.casefold() == kw:
                return entry
            if any(kw == str(k).casefold() for k in entry.get("keywords", [])):
                return entry
            if any(kw == str(f).casefold() for f in entry.get("fuzzy", [])):
                return entry
        # 次选子串包含
        for name, entry in self.entries.items():
            if kw in name.casefold():
                return entry
            if any(kw in str(k).casefold() for k in entry.get("keywords", [])):
                return entry
            if any(kw in str(f).casefold() for f in entry.get("fuzzy", [])):
                return entry
        return None

    def match(self, text: str):
        """按关键词/模糊词在文本中匹配，返回 (name, entry) 或 None。"""
        hay = (text or "").casefold()
        if not hay:
            return None
        for name, entry in self.entries.items():
            for kw in entry.get("keywords", []):
                if kw and kw.casefold() in hay:
                    return name, entry
            for fz in entry.get("fuzzy", []):
                if fz and fz.casefold() in hay:
                    return name, entry
        return None

    def respond(self, text: str) -> str | None:
        """命中热梗后随机返回一条回复；未命中或回复为空返回 None。"""
        hit = self.match(text)
        if not hit:
            return None
        replies = hit[1].get("replies") or []
        return random.choice(replies) if replies else None

    def random_pick(self) -> dict | None:
        """随机返回一条热梗条目；库为空时返回 None。"""
        if not self.entries:
            return None
        return random.choice(list(self.entries.values()))

    @staticmethod
    def format_entry(entry: dict) -> str:
        """把条目格式化为「名称+含义+出处+示例」的文本。"""
        lines = [f"【{entry.get('name') or ''}】"]
        if entry.get("meaning"):
            lines.append(f"含义：{entry['meaning']}")
        if entry.get("source"):
            lines.append(f"出处：{entry['source']}")
        if entry.get("examples"):
            lines.append("示例：" + "；".join(entry["examples"]))
        return "\n".join(lines)