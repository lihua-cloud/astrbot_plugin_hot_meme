"""hot_meme 插件功能测试。

可在 AstrBot 自带 venv 下直接运行（不依赖 AstrBot 运行时）：

    D:\\AstrBot\\venv\\Scripts\\python.exe D:\\AstrBot\\data\\plugins\\hot_meme\\tests\\test_hot_meme.py

也可用 pytest 收集执行（test_hot_meme 为聚合断言用例）。

覆盖 5 项：
1. 热梗库加载成功率
2. 关键词匹配正确性
3. 随机调用正确性
4. 调用响应耗时（平均/最慢，毫秒）
5. 配置兼容性（_conf_schema.json / metadata.yaml）
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from hot_source import HotMemeSource  # noqa: E402

DATA_FILE = os.path.join(PLUGIN_DIR, "data", "hot_meme_data.json")
SCHEMA_FILE = os.path.join(PLUGIN_DIR, "_conf_schema.json")
META_FILE = os.path.join(PLUGIN_DIR, "metadata.yaml")

EXPECT_VERSION = "1.1.0"
MIN_ENTRIES = 8
EXPECTED_KEYS = ("enable_hot_source", "hot_source_urls", "hot_source_data_file", "update_interval_minutes")

# (待匹配文本, 期望命中的热梗 name)
KNOWN_CASES = [
    ("你今天 city 不 city 啊", "city不city"),
    ("已老实，求放过", "已老实"),
    ("主打一个听劝", "听劝"),
    ("你这班味太重了", "班味"),
    ("南方小土豆来啦", "小土豆"),
    ("这小孩哥心态太稳了", "小孩哥"),
    ("你真是饿了", "你真是饿了"),
    ("吃饭得配点电子榨菜", "电子榨菜"),
]

RESULTS = []  # (name, ok, ms, detail)


def _build_source():
    src = HotMemeSource()
    n = src.load_file(DATA_FILE)
    return src, n


# ---- 用例 1：热梗库加载成功率 ----
def case_load():
    src, n = _build_source()
    total = len(src.entries)
    assert n >= MIN_ENTRIES, f"加载条数 {n} < 最低要求 {MIN_ENTRIES}"
    valid = 0
    for e in src.entries.values():
        if e.get("name") and (e.get("keywords") or e.get("replies")):
            valid += 1
    ratio = valid / total * 100 if total else 0
    assert valid == total, f"有效条目 {valid}/{total}，存在缺字段条目"
    return f"总共 {total} 条，有效 {valid} 条，加载成功率 {ratio:.1f}%"


# ---- 用例 2：关键词匹配正确性 ----
def case_match():
    src, _ = _build_source()
    for text, name in KNOWN_CASES:
        hit = src.match(text)
        assert hit is not None, f"未命中：{text}"
        assert hit[0] == name, f"命中错误：{text} -> {hit[0]}（期望 {name}）"
    entry = src.find("city不city")
    assert entry is not None and entry["name"] == "city不city", "find 精确查找失败"
    assert src.find("一个不存在的梗") is None, "find 应返回 None"
    return f"{len(KNOWN_CASES)} 个关键词样本全部命中正确"


# ---- 用例 3：随机调用正确性 ----
def case_random():
    src, _ = _build_source()
    names = set(src.entries.keys())
    for _ in range(50):
        e = src.random_pick()
        assert e is not None, "random_pick 返回 None"
        assert e["name"] in names, f"random_pick 返回未知条目：{e.get('name')}"
    reply = src.respond("city不city啊")
    assert reply in src.entries["city不city"]["replies"], f"随机回复不在候选集：{reply}"
    return "随机抽取 50 次均在库内，随机回复属于候选集"


# ---- 用例 4：调用响应耗时 ----
def case_latency():
    src, _ = _build_source()
    src.match("city不city")  # 预热
    reps = 1000
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        src.match("你今天 city 不 city 啊")
        samples.append((time.perf_counter() - t0) * 1000)
    avg = sum(samples) / len(samples)
    worst = max(samples)
    t0 = time.perf_counter()
    src.respond("city不city")
    respond_ms = (time.perf_counter() - t0) * 1000
    assert worst < 50, f"最慢单次 match 超过 50ms：{worst:.3f}ms"
    return (
        f"match×{reps} 平均 {avg:.3f}ms / 最慢 {worst:.3f}ms，"
        f"respond 单次 {respond_ms:.3f}ms"
    )


# ---- 用例 5：配置兼容性 ----
def case_config():
    with open(SCHEMA_FILE, "r", encoding="utf-8") as fp:
        schema = json.load(fp)
    defaults = {
        "enable_hot_source": True,
        "hot_source_urls": [],
        "hot_source_data_file": "",
        "update_interval_minutes": 360,
    }
    for key, default in defaults.items():
        assert key in schema, f"schema 缺少配置项 {key}"
        assert schema[key].get("type"), f"{key} 缺少 type"
        assert schema[key].get("default") == default, (
            f"{key} 默认值不符：{schema[key].get('default')!r}（期望 {default!r}）"
        )

    yaml_note = ""
    try:
        import yaml
    except ImportError:
        yaml_note = "（未安装 PyYAML，跳过 metadata.yaml 解析）"
    else:
        with open(META_FILE, "r", encoding="utf-8") as fp:
            meta = yaml.safe_load(fp)
        assert meta.get("name") == "hot_meme", "metadata name 不符"
        assert str(meta.get("version")) == EXPECT_VERSION, (
            f"版本应为 {EXPECT_VERSION}，实际 {meta.get('version')}"
        )
        yaml_note = f"yaml 解析通过，version={meta.get('version')}"
    return f"schema 新增 {len(EXPECTED_KEYS)} 项默认值正确；{yaml_note}"


CASES = [
    ("热梗库加载成功率", case_load),
    ("关键词匹配正确性", case_match),
    ("随机调用正确性", case_random),
    ("调用响应耗时", case_latency),
    ("配置兼容性", case_config),
]


def run_all():
    global RESULTS
    RESULTS = []
    print(f"数据文件：{DATA_FILE}")
    print(f"插件目录：{PLUGIN_DIR}")
    print("-" * 64)
    for name, fn in CASES:
        t0 = time.perf_counter()
        try:
            detail = fn()
            ms = (time.perf_counter() - t0) * 1000
            RESULTS.append((name, True, ms, detail or ""))
            print(f"[PASS] {name}（{ms:.1f}ms）：{detail or ''}")
        except AssertionError as exc:
            ms = (time.perf_counter() - t0) * 1000
            RESULTS.append((name, False, ms, str(exc)))
            print(f"[FAIL] {name}（{ms:.1f}ms）：{exc}")
        except Exception as exc:  # noqa: BLE001
            ms = (time.perf_counter() - t0) * 1000
            RESULTS.append((name, False, ms, f"{type(exc).__name__}: {exc}"))
            print(f"[FAIL] {name}（{ms:.1f}ms）：{type(exc).__name__}: {exc}")

    passed = sum(1 for _, ok, _, _ in RESULTS if ok)
    total = len(RESULTS)
    ms_list = [ms for _, _, ms, _ in RESULTS]
    print("-" * 64)
    print(f"结果：{passed}/{total} 通过")
    if ms_list:
        print(f"用例耗时：平均 {sum(ms_list) / len(ms_list):.1f}ms，最慢 {max(ms_list):.1f}ms")
    print("整体测试：" + ("PASS" if passed == total else "FAIL"))
    return 0 if passed == total else 1


# pytest 兼容：聚合断言所有核心校验
def test_hot_meme():
    src, n = _build_source()
    assert n >= MIN_ENTRIES
    for text, name in KNOWN_CASES:
        assert src.match(text)[0] == name
    assert src.random_pick() is not None
    assert src.respond("city不city") in src.entries["city不city"]["replies"]
    with open(SCHEMA_FILE, "r", encoding="utf-8") as fp:
        schema = json.load(fp)
    for key in EXPECTED_KEYS:
        assert key in schema


if __name__ == "__main__":
    sys.exit(run_all())