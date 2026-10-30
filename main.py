"""智能热梗响应插件。

自动识别并学习用户输入中的典型网络热梗与情绪性词汇（如「似冯」「串子」等），
采用「关键词精准匹配 + 语境模糊匹配」结合的方式，内置基础热梗回复库，
并支持动态学习交互过程中出现的新热梗与回复风格。

设计要点：
1. 通过 ``filter.custom_filter`` 注册一个自定义过滤器，仅当消息命中热梗时才
   「唤醒」机器人并触发回复，避免无热梗时打扰默认的 LLM 流程。
2. 匹配引擎为模块级单例 ``_ENGINE``，供过滤器与处理函数共享同一份热梗库。
3. 已学习的热梗与候选词通过 AstrBot 的插件 KV 存储持久化（无需额外文件）。
"""

import asyncio
import random
import re
from copy import deepcopy

from astrbot.api.star import Context, Star
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.core.star.filter.command import GreedyStr

# ---------------------------------------------------------------------------
# 内置基础热梗回复库
# 每个条目：
#   keywords  : 精准匹配关键词（命中即高置信度）
#   fuzzy     : 模糊匹配词（近义/谐音变体，命中为中置信度）
#   context   : 语境词，出现任意一个会提升模糊匹配置信度
#   negative  : 排除语境词，出现任意一个则本次命中作废（防误判）
#   replies   : 回复候选列表，命中后随机选择一条
# ---------------------------------------------------------------------------

BASE_MEMES: dict[str, dict] = {
    "sifeng": {
        "keywords": ["似冯"],
        "fuzzy": ["似风", "似逢"],
        "context": ["抽象", "梗", "懂的都懂", "笑死", "绷", "行为艺术"],
        "negative": [],
        "replies": [
            "似冯？懂的都懂，不懂的说破天也白搭。",
            "这事儿不能细说，主打一个似冯。",
            "你别说，还真有点似冯内味儿了。",
            "冯子虽无，其神常在，抽象就完事了。",
        ],
    },
    "chuanzi": {
        "keywords": ["串子", "反串"],
        "fuzzy": [],
        "context": ["黑", "粉", "卧底", "钓鱼", "带节奏", "装", "演", "自爆"],
        "negative": ["羊肉串", "烤串", "撸串", "麻辣烫", "串串香", "糖葫芦"],
        "replies": [
            "好一个串子，演得我差点就信了。",
            "串子收收味，味儿属实有点冲了。",
            "你这反串，属于是自爆卡车了属于是。",
            "别串了别串了，再串味儿就散了。",
        ],
    },
    "pofang": {
        "keywords": ["破防", "破大防"],
        "fuzzy": ["破放", "破房"],
        "context": ["哭了", "绷", "顶不住", "泪目", "顶"],
        "negative": [],
        "replies": [
            "这波直接破防了属于是。",
            "别破防了，深呼吸，深呼吸。",
            "破防了？哥们儿顶住，这局还没完。",
        ],
    },
    "bengbu": {
        "keywords": ["蚌埠住了", "绷不住了", "蚌埠住"],
        "fuzzy": ["绷不住"],
        "context": ["笑", "无语", "啥", "操作"],
        "negative": [],
        "replies": [
            "绷不住了家人们。",
            "蚌埠住了，真的蚌埠住了。",
            "我也蚌埠住了，这什么操作。",
        ],
    },
    "shuanq": {
        "keywords": ["栓q", "栓Q", "真的谢", "栓扣"],
        "fuzzy": ["栓Q了", "栓了"],
        "context": ["谢", "无语", "服", "麻"],
        "negative": [],
        "replies": [
            "栓Q，我真的会谢。",
            "一整个大无语栓Q住了。",
            "别谢了别谢了，再谢就真栓Q了。",
        ],
    },
    "zundu": {
        "keywords": ["尊嘟假嘟", "尊嘟", "假嘟"],
        "fuzzy": ["真嘟假嘟"],
        "context": [],
        "negative": [],
        "replies": [
            "尊嘟假嘟？尊嘟。",
            "假嘟假嘟，尊嘟假嘟已经分不清啦。",
            "尊嘟 O.o",
        ],
    },
    "yyds": {
        "keywords": ["yyds", "永远的神"],
        "fuzzy": ["永远滴神"],
        "context": [],
        "negative": [],
        "replies": [
            "yyds！",
            "这波 yyds，没毛病。",
            "永远的神，不接受反驳。",
        ],
    },
    "juejuezi": {
        "keywords": ["绝绝子", "绝了"],
        "fuzzy": ["泰裤辣", "太酷啦", "泰酷辣"],
        "context": ["好", "美", "棒", "最强"],
        "negative": [],
        "replies": [
            "绝绝子，这也太绝了吧。",
            "泰裤辣！",
            "绝了，属你会整活。",
        ],
    },
    "mala": {
        "keywords": ["麻了", "我麻了", "人麻了"],
        "fuzzy": ["人麻"],
        "context": [],
        "negative": ["麻将", "麻辣"],
        "replies": [
            "麻了，真的麻了。",
            "我已经麻了，爱咋咋地。",
            "麻了，但还得继续坐牢（不是）。",
        ],
    },
    "bailan": {
        "keywords": ["摆烂", "摆了", "开摆", "躺平"],
        "fuzzy": ["开摆！", "摆咯"],
        "context": [],
        "negative": ["摆摊"],
        "replies": [
            "摆了，哥们儿先摆为敬。",
            "一起开摆，卷不动了。",
            "躺平一时爽，一直躺平一直爽。",
        ],
    },
    "moyu": {
        "keywords": ["摸鱼", "划水"],
        "fuzzy": [],
        "context": ["上班", "下课", "无聊", "偷"],
        "negative": ["摸鱼儿"],
        "replies": [
            "摸鱼？带上我一个。",
            "上班摸鱼，人生乐事。",
            "摸鱼虽好，可别被抓住了哦。",
        ],
    },
    "wuyu": {
        "keywords": ["无语子", "大无语", "无语"],
        "fuzzy": [],
        "context": [],
        "negative": [],
        "replies": [
            "我也是无语住了。",
            "一整个大无语事件。",
            "无语，但大受震撼。",
        ],
    },
    "ningsuan": {
        "keywords": ["柠檬", "酸了", "我酸了"],
        "fuzzy": ["柠檬精"],
        "context": [],
        "negative": ["柠檬茶", "柠檬水", "柠檬汁"],
        "replies": [
            "柠檬精驾到，我先酸为敬。",
            "别酸了，你也会有滴。",
            "酸了酸了，实名羡慕。",
        ],
    },
    "shesi": {
        "keywords": ["社死", "社会性死亡"],
        "fuzzy": ["社死现场"],
        "context": [],
        "negative": [],
        "replies": [
            "好家伙，直接社死现场。",
            "替我抠出三室一厅了属于是。",
            "社死了，但问题不大，只要我们不说。",
        ],
    },
    "hajimi": {
        "keywords": ["哈基米", "hajimi"],
        "fuzzy": [],
        "context": [],
        "negative": [],
        "replies": [
            "哈基米哈基米~",
            "可爱捏，哈基米。",
            "哈基米摇头.gif（脑补）。",
        ],
    },
    "liufan": {
        "keywords": ["6翻", "六翻", "6死了", "太6了", "六六六"],
        "fuzzy": ["6翻了"],
        "context": [],
        "negative": [],
        "replies": [
            "这波 6 翻了。",
            "6，还得是你。",
            "不是哥们，这也太 6 了。",
        ],
    },
}

# 自动学习：引号/括号包裹的新词出现达到该次数后，自动学习为热梗。
AUTO_LEARN_THRESHOLD = 3

# 识别「」『』“” 等包裹的候选热梗词
_QUOTE_RE = re.compile(r"[「『“\"]([^」』”\"\s]{2,12})[」』”\"]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _norm_replies(value) -> list[str]:
    """将配置/学习中的回复值归一化为字符串列表。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    return []


def _build_memes(base: dict, custom: dict, learned: dict) -> dict:
    """合并内置库、已学习热梗与自定义映射。"""
    memes = {k: deepcopy(v) for k, v in base.items()}

    # 已学习热梗覆盖同 key 的内置条目
    for name, entry in (learned or {}).items():
        if isinstance(entry, dict) and entry.get("replies"):
            memes[name] = deepcopy(entry)

    # 自定义映射：键=热梗词，值=回复（字符串或列表）
    for kw, val in (custom or {}).items():
        kw = str(kw).strip()
        replies = _norm_replies(val)
        if not kw or not replies:
            continue
        placed = False
        for entry in memes.values():
            if kw in entry.get("keywords", []):
                entry["replies"] = list(
                    dict.fromkeys(entry.get("replies", []) + replies)
                )
                placed = True
                break
        if not placed:
            memes[kw] = {
                "keywords": [kw],
                "fuzzy": [],
                "context": [],
                "negative": [],
                "replies": replies,
            }
    return memes


class MemeEngine:
    """热梗匹配引擎（模块级单例）。"""

    def __init__(self) -> None:
        self.enabled = False
        self.sensitivity = 45
        self.fuzzy_enabled = True
        self.learn_enabled = True
        self.whitelist: list[str] = []
        self.custom_mappings: dict = {}
        self.learned: dict = {}
        self.candidates: dict[str, int] = {}
        self._memes = _build_memes(BASE_MEMES, {}, {})

    # ---- 配置与状态 ----
    def configure(self, config) -> None:
        conf = config or {}
        self.enabled = bool(conf.get("enable", True))
        self.sensitivity = max(0, min(100, int(conf.get("sensitivity", 45))))
        self.fuzzy_enabled = bool(conf.get("fuzzy_enabled", True))
        self.learn_enabled = bool(conf.get("learn_enabled", True))
        self.whitelist = [
            str(w).strip() for w in (conf.get("whitelist") or []) if str(w).strip()
        ]
        self.custom_mappings = conf.get("custom_mappings") or {}
        self._rebuild()

    def set_learned(self, learned: dict) -> None:
        self.learned = learned or {}
        self._rebuild()

    def set_candidates(self, candidates: dict) -> None:
        self.candidates = candidates or {}

    def _rebuild(self) -> None:
        self._memes = _build_memes(BASE_MEMES, self.custom_mappings, self.learned)

    # ---- 匹配 ----
    def _whitelisted(self, haystack: str) -> bool:
        return any(w.casefold() in haystack for w in self.whitelist)

    @staticmethod
    def _vetoed(haystack: str, pos: int, kw_len: int, negatives: list[str]) -> bool:
        for neg in negatives or []:
            p = haystack.find(neg.casefold())
            if p != -1 and abs(p - pos) <= max(4, kw_len + 2):
                return True
        return False

    def match(self, text: str):
        """返回命中的 (名称, 置信度, 条目)，未命中返回 None。"""
        if not self.enabled or not text:
            return None
        haystack = text.casefold()
        if self._whitelisted(haystack):
            return None

        best = None  # (name, confidence, entry)
        for name, entry in self._memes.items():
            pos, conf, kw_len = -1, 0, 0
            for kw in entry.get("keywords", []):
                p = haystack.find(kw.casefold())
                if p != -1:
                    pos, conf, kw_len = p, 100, len(kw)
                    break
            if pos == -1 and self.fuzzy_enabled:
                for fz in entry.get("fuzzy", []):
                    p = haystack.find(fz.casefold())
                    if p != -1:
                        pos, conf, kw_len = p, 50, len(fz)
                        ctx = entry.get("context", [])
                        if ctx and any(c.casefold() in haystack for c in ctx):
                            conf = 80
                        break
            if pos == -1:
                continue
            if self._vetoed(haystack, pos, kw_len, entry.get("negative", [])):
                continue
            if best is None or conf > best[1]:
                best = (name, conf, entry)
        return best

    def would_respond(self, text: str) -> bool:
        hit = self.match(text)
        return bool(hit and hit[1] >= self.sensitivity)

    def respond(self, text: str) -> str:
        hit = self.match(text)
        if not hit or hit[1] < self.sensitivity:
            return ""
        replies = hit[2].get("replies") or []
        return random.choice(replies) if replies else ""

    # ---- 动态学习 ----
    def note_candidate(self, text: str) -> None:
        """从引号/括号包裹的新词中提取候选热梗（同步、仅内存计数）。"""
        if not self.enabled or not self.learn_enabled or not text:
            return
        for m in _QUOTE_RE.finditer(text):
            token = m.group(1).strip()
            if not _CJK_RE.search(token):
                continue
            if self._known(token):
                continue
            self.candidates[token] = self.candidates.get(token, 0) + 1

    def _known(self, token: str) -> bool:
        if token in self.learned:
            return True
        for entry in self._memes.values():
            if token in entry.get("keywords", []) or token in entry.get("fuzzy", []):
                return True
        return False

    def lookup_owner(self, keyword: str) -> str | None:
        """返回关键词当前归属：learned / builtin_or_custom / None。"""
        if keyword in self.learned:
            return "learned"
        for entry in self._memes.values():
            if keyword in entry.get("keywords", []) or keyword in entry.get("fuzzy", []):
                return "builtin_or_custom"
        return None

    def promote_candidates(self) -> None:
        """将达到阈值的候选词自动学习为热梗。"""
        changed = False
        for token, cnt in list(self.candidates.items()):
            if cnt >= AUTO_LEARN_THRESHOLD:
                self.learned.setdefault(
                    token,
                    {
                        "keywords": [token],
                        "fuzzy": [],
                        "context": [],
                        "negative": [],
                        "replies": [
                            f"「{token}」这个梗我记下了，下次带你一起玩。",
                            f"学到了，{token} 是吧，懂你意思。",
                            f"收到新梗「{token}」，已加入热梗库。",
                        ],
                    },
                )
                self.candidates.pop(token, None)
                changed = True
        if changed:
            self._rebuild()

    def learn(self, keyword: str, replies: list[str]) -> None:
        keyword = keyword.strip()
        self.learned[keyword] = {
            "keywords": [keyword],
            "fuzzy": [],
            "context": [],
            "negative": [],
            "replies": replies,
        }
        self.candidates.pop(keyword, None)
        self._rebuild()

    def forget(self, keyword: str) -> bool:
        keyword = keyword.strip()
        if keyword in self.learned:
            del self.learned[keyword]
            self._rebuild()
            return True
        if keyword in self.candidates:
            del self.candidates[keyword]
            return True
        return False


_ENGINE = MemeEngine()


class MemeFilter(filter.CustomFilter):
    """自定义过滤器：仅当消息命中热梗（且达到敏感度）时放行，唤醒机器人。"""

    def filter(self, event: AstrMessageEvent, cfg) -> bool:
        text = event.get_message_str()
        # 顺带在每条消息上收集候选热梗词（不扰动匹配结果）
        _ENGINE.note_candidate(text)
        return _ENGINE.would_respond(text)


class Main(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context, config)
        self.config = config or {}
        _ENGINE.configure(self.config)
        self._flush_task: asyncio.Task | None = None

    # ---- 生命周期 ----
    async def initialize(self) -> None:
        learned = (await self.get_kv_data("learned_memes", {})) or {}
        candidates = (await self.get_kv_data("learn_candidates", {})) or {}
        _ENGINE.set_learned(learned)
        _ENGINE.set_candidates(candidates)

        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._flush_loop())
            self.logger.info("智能热梗插件已启动，内置 %d 条热梗，已学习 %d 条。", len(BASE_MEMES), len(_ENGINE.learned))

    async def terminate(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
            self._flush_task = None
        await self._persist()

    async def _flush_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(60)
                await self._persist()
        except asyncio.CancelledError:
            pass

    async def _persist(self) -> None:
        _ENGINE.promote_candidates()
        await self.put_kv_data("learned_memes", _ENGINE.learned)
        await self.put_kv_data("learn_candidates", _ENGINE.candidates)

    # ---- 热梗响应 ----
    @filter.custom_filter(MemeFilter)
    async def on_meme(self, event: AstrMessageEvent):
        """命中热梗时返回一条贴合的回复并终止事件传播。"""
        reply = _ENGINE.respond(event.get_message_str())
        if reply:
            return MessageEventResult().message(reply).stop_event()
        return None

    # ---- 管理命令 ----
    @filter.command("hotmeme", priority=10)
    async def hotmeme(self, event: AstrMessageEvent, text: GreedyStr):
        parts = (text or "").strip().split()
        if not parts:
            return MessageEventResult().message(self._help_text()).stop_event()
        sub = parts[0].lower()

        if sub in ("help", "帮助", "h"):
            return MessageEventResult().message(self._help_text()).stop_event()
        if sub in ("list", "列表"):
            return MessageEventResult().message(self._list_text()).stop_event()
        if sub in ("learn", "学习"):
            return await self._cmd_learn(event, parts)
        if sub in ("forget", "删除", "忘"):
            return await self._cmd_forget(event, parts)
        if sub in ("on", "off"):
            return await self._cmd_toggle(event, sub)
        if sub in ("sens", "sensitivity", "敏感度"):
            return await self._cmd_sens(event, parts)
        return MessageEventResult().message(self._help_text()).stop_event()

    @staticmethod
    def _admin_only(event: AstrMessageEvent) -> MessageEventResult | None:
        if not event.is_admin():
            return MessageEventResult().message("只有管理员可以执行此操作。").stop_event()
        return None

    async def _cmd_learn(self, event, parts) -> MessageEventResult:
        denied = self._admin_only(event)
        if denied:
            return denied
        if len(parts) < 3:
            return MessageEventResult().message(
                "用法：/hotmeme learn 关键词 回复1|回复2\n例如：/hotmeme learn 尊嘟 尊嘟~|尊嘟假嘟"
            ).stop_event()
        keyword = parts[1]
        replies = [r.strip() for r in re.split(r"[|｜]", " ".join(parts[2:])) if r.strip()]
        owner = _ENGINE.lookup_owner(keyword)
        if owner == "learned":
            return MessageEventResult().message(
                f"「{keyword}」已学习过，可用 /hotmeme forget {keyword} 删除后再重新学习。"
            ).stop_event()
        if owner == "builtin_or_custom":
            return MessageEventResult().message(
                f"「{keyword}」已是内置/自定义热梗，无法覆盖；如需自定义回复请在配置面板的「自定义热梗映射」中修改。"
            ).stop_event()
        _ENGINE.learn(keyword, replies)
        await self._persist()
        return MessageEventResult().message(
            f"已学习热梗「{keyword}」，共 {len(replies)} 条回复。"
        ).stop_event()

    async def _cmd_forget(self, event, parts) -> MessageEventResult:
        denied = self._admin_only(event)
        if denied:
            return denied
        if len(parts) < 2:
            return MessageEventResult().message("用法：/hotmeme forget 关键词").stop_event()
        keyword = parts[1]
        if _ENGINE.forget(keyword):
            await self._persist()
            return MessageEventResult().message(f"已删除热梗「{keyword}」。").stop_event()
        return MessageEventResult().message(f"未找到热梗「{keyword}」。").stop_event()

    async def _cmd_toggle(self, event, sub) -> MessageEventResult:
        denied = self._admin_only(event)
        if denied:
            return denied
        should = sub == "on"
        _ENGINE.enabled = should
        self.config["enable"] = should
        return MessageEventResult().message(
            f"热梗响应已{'开启' if should else '关闭'}（本次运行内存生效，重启后以配置面板为准）。"
        ).stop_event()

    async def _cmd_sens(self, event, parts) -> MessageEventResult:
        denied = self._admin_only(event)
        if denied:
            return denied
        if len(parts) < 2:
            return MessageEventResult().message("用法：/hotmeme sens 0-100").stop_event()
        try:
            value = int(parts[1])
        except ValueError:
            return MessageEventResult().message("敏感度必须是 0-100 的整数。").stop_event()
        value = max(0, min(100, value))
        _ENGINE.sensitivity = value
        self.config["sensitivity"] = value
        return MessageEventResult().message(
            f"回复敏感度已设为 {value}（0 最严格，100 最宽松，仅本次运行内存生效）。"
        ).stop_event()

    def _list_text(self) -> str:
        builtin = sum(len(e.get("keywords", [])) for e in BASE_MEMES.values())
        lines = [f"内置热梗词 {builtin} 个，已学习热梗 {len(_ENGINE.learned)} 个。"]
        if _ENGINE.learned:
            for kw, entry in _ENGINE.learned.items():
                n = len(entry.get("replies", []))
                lines.append(f"· {kw}（{n} 条回复）")
        else:
            lines.append("暂无已学习热梗，可用 /hotmeme learn 添加。")
        return "\n".join(lines)

    @staticmethod
    def _help_text() -> str:
        return (
            "智能热梗响应插件\n"
            "自动识别「似冯」「串子」等热梗与情绪词并回复。\n\n"
            "命令：\n"
            "/hotmeme help —— 查看帮助\n"
            "/hotmeme list —— 查看内置与已学习热梗\n"
            "/hotmeme learn 关键词 回复1|回复2 —— 学习新热梗（管理员）\n"
            "/hotmeme forget 关键词 —— 删除热梗（管理员）\n"
            "/hotmeme on / off —— 临时开/关（管理员）\n"
            "/hotmeme sens 0-100 —— 调整敏感度（管理员）"
        )