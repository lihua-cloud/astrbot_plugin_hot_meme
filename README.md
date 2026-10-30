# 智能热梗响应插件（hot_meme）

为 [AstrBot](https://astrbot.app) 开发的智能热梗响应插件：自动识别并学习用户输入中的典型网络热梗与情绪性词汇（如「似冯」「串子」「city不city」等），采用「关键词精准匹配 + 语境模糊匹配」相结合的方式，内置基础热梗回复库，并支持动态学习。回复贴合对应热梗的网络语境，自然轻松，避免生硬机械。

本版本（1.1.0）新增**网络热梗数据源 + 定时更新**能力：可从本地 JSON 或远程 URL 加载热梗库，按 `name` 去重合并，并定时刷新；新增 `/hotmeme random` 与 `/hotmeme <关键词>` 命令，返回热梗的完整内容（名称 + 含义 + 出处 + 示例）。

## 功能特性

- **自动识别热梗**：识别「似冯」「串子」「city不city」等流行调侃、情绪类网络用语，内置 16+ 组基础热梗库。
- **网络热梗数据源**：从本地 JSON / 远程 URL（HTTP GET）加载热梗库，条目 schema 为 `{name, keywords, fuzzy, replies, meaning, source, platform, heat, updated_at, examples}`，按 `name` 去重合并。
- **定时更新**：后台任务按配置间隔（默认 360 分钟）自动刷新数据源，保证梗库时效性；加载/网络异常均被捕获，失败不影响插件运行、保留已有数据。
- **精准 + 模糊双匹配**：关键词精准匹配（高置信度）+ 谐音/近义模糊匹配（结合语境词提升置信度），兼顾准确率与召回。
- **随机调用与关键词查找**：`/hotmeme random` 随机返回一条热梗完整内容；`/hotmeme <关键词>` 按关键词查找热梗。
- **内置回复库 + 动态学习**：内置多样回复，命中后随机选取；支持命令学习新热梗，也支持从 `「」`/`“”` 包裹的新词中自动学习。
- **丰富配置项**：热梗总开关、回复敏感度、模糊匹配开关、动态学习开关、数据源开关/URL/文件/更新间隔、自定义映射、白名单过滤。
- **遵循插件规范**：继承 `Star` 基类，实现 `initialize()` / `terminate()` 生命周期，支持热加载/热卸载；数据源模块仅用标准库，核心逻辑与 AstrBot 解耦、便于单测。
- **防误判机制**：白名单过滤 + 每个热梗可配置「排除语境词」。

## 目录结构

```
hot_meme/
├── main.py                 # 插件主体（匹配引擎 + 生命周期 + 命令）
├── hot_source.py           # 网络热梗数据源（加载/合并/查询，不依赖 AstrBot）
├── data/
│   └── hot_meme_data.json  # 自带样例热梗库（10 条近年真实网络热梗）
├── tests/
│   └── test_hot_meme.py    # 功能测试（加载成功率/匹配/耗时/配置兼容）
├── metadata.yaml           # 插件元数据
├── _conf_schema.json       # 配置项 Schema
└── README.md               # 本说明文档
```

## 安装方式

1. 将 `hot_meme` 文件夹放入 AstrBot 的插件目录：`AstrBot/data/plugins/`。
2. 重启 AstrBot（或在 WebUI 的「插件管理」中点击重载）。
3. 在 WebUI「插件」页面找到「智能热梗响应」，按需调整配置后保存。

> 无需安装任何第三方依赖。插件使用标准库与 AstrBot 自带的插件 API 与 KV 存储。

## 配置说明

在 WebUI 插件配置面板（或直接编辑生成于 `AstrBot/data/config/hot_meme_config.json` 的配置）可调整：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enable` | bool | true | 热梗响应总开关 |
| `sensitivity` | int | 45 | 回复敏感度（0-100）。数值越大越宽松，越容易触发模糊匹配；100 时仅精准匹配；0 时最严格 |
| `fuzzy_enabled` | bool | true | 是否启用语境模糊匹配（谐音/近义 + 语境词） |
| `learn_enabled` | bool | true | 是否允许动态学习新热梗 |
| `custom_mappings` | dict | {} | 自定义「热梗 → 回复」映射：键为热梗词，值为回复文本或回复列表 |
| `whitelist` | list | [] | 白名单过滤：消息中出现这些词时跳过热梗响应，避免误判 |
| `enable_hot_source` | bool | true | 是否启用网络热梗数据源（本地/远程加载与定时刷新）。关闭后 `/hotmeme random` / `/hotmeme <关键词>` 失效 |
| `hot_source_urls` | list | [] | 远程热梗数据源 URL 列表（HTTP GET 返回同 schema 的 JSON），定时拉取刷新，按 `name` 去重合并 |
| `hot_source_data_file` | string | "" | 本地热梗数据文件路径。留空则使用插件自带 `data/hot_meme_data.json`；填写后改从该文件加载 |
| `update_interval_minutes` | int | 360 | 定时刷新数据源的间隔（分钟），默认 360 分钟（6 小时） |

### 敏感度与匹配置信度

匹配引擎为每种命中计算置信度：

- 精准关键词命中：置信度 **100**
- 模糊匹配且命中语境词：置信度 **80**
- 模糊匹配但无语境词：置信度 **50**

只有 `命中置信度 >= sensitivity` 时才会回复。因此：

- `sensitivity = 45`（默认）：精准与带语境模糊均可触发，无语境模糊不触发。
- `sensitivity = 100`：仅精准匹配触发。
- 想彻底关闭模糊匹配，优先把 `fuzzy_enabled` 设为 false。

## 命令用法

### 1. 自动响应热梗（无需唤醒词）

用户直接输入包含热梗的消息即可触发：

```
用户：你这波就挺 city 不 city 的
机器人：city不city啊～
```

### 2. 随机返回一条网络热梗

```
/hotmeme random
# or /hotmeme 随机
机器人：
【city不city】
含义：询问或感叹某地、某物是否洋气、时尚、有都市范儿，也泛指「高级不高级、好玩不好玩」。
出处：2024 年由外国博主「保保熊」在短视频中的口头禅「city不city啊」走红，后被广泛借用。
示例：这个餐厅感觉city不city啊？；今天这穿搭挺city的。
```

### 3. 按关键词查找网络热梗

```
/hotmeme 班味
机器人：
【班味】
含义：指上班族久经职场后身上流露出的疲惫、萎靡、身不由己的「打工人」气质或状态。
出处：2024 年网络流行语，常被用来调侃自己或他人上班上久了「班味」明显。
示例：上了几年班，班味是怎么洗也洗不掉。；一看你就班味十足。
```

### 4. 查看热梗

```
/hotmeme list
# 内置热梗词 N 个，网络热梗 10 个，已学习热梗 M 个。
# 网络热梗：已老实、city不city、听劝、电子榨菜、班味、脆皮大学生、小土豆、显眼包、小孩哥、你真是饿了
```

### 5. 学习 / 删除热梗（管理员）

```
/hotmeme learn 尊嘟 尊嘟~|尊嘟假嘟
/hotmeme forget 尊嘟
```

### 6. 临时开/关与敏感度（管理员）

```
/hotmeme off      # 关闭热梗响应
/hotmeme on       # 开启热梗响应
/hotmeme sens 60  # 调整敏感度
```

### 7. 帮助

```
/hotmeme help
```

> 管理员身份由 AstrBot 的 `admins_id` 判断（可用 `/sid` 获取 ID）。

## 数据源与定时更新说明

### 数据格式

热梗库为标准 JSON，整体可以是：

- **数组**：`[{...}, {...}]`（每个对象一条热梗）；
- **对象**：`{"items": [...]}`、`{"memes": [...]}`、`{"entries": [...]}`、`{"data": [...]}`，或 `{name: {...}}` 形式。

每条热梗字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | 热梗名称（去重键） |
| `keywords` | list | 否 | 精准匹配关键词，命中置信度 100 |
| `fuzzy` | list | 否 | 模糊匹配词（谐音/变体），命中置信度 50 |
| `replies` | list | 否 | 自动回复候选，命中后随机选一条 |
| `meaning` | string | 否 | 含义（`/hotmeme` 查询/随机时展示） |
| `source` | string | 否 | 出处 |
| `platform` | string | 否 | 平台（如 抖音/微博） |
| `heat` | number/string | 否 | 热度（留存展示） |
| `updated_at` | string | 否 | 更新时间 |
| `examples` | list | 否 | 示例句 |

示例（`data/hot_meme_data.json`）：

```json
{
  "name": "city不city",
  "keywords": ["city不city", "city 不 city"],
  "fuzzy": ["city不city啊"],
  "replies": ["city不city啊～", "好city啊！", "这不city上来了吗。"],
  "meaning": "询问或感叹某地、某物是否洋气、时尚、有都市范儿。",
  "source": "2024 年由外国博主「保保熊」短视频口头禅走红。",
  "platform": "抖音/小红书",
  "heat": 95,
  "updated_at": "2024-06-15",
  "examples": ["这个餐厅感觉city不city啊？"]
}
```

### 加载与刷新

1. **启动加载**：`initialize()` 先读 `hot_source_data_file`（留空用自带文件），再依次拉取 `hot_source_urls`，全部按 `name` 去重合并进匹配引擎。
2. **定时刷新**：后台任务每 `update_interval_minutes` 分钟重复以上加载，网络/解析/文件异常均被捕获并以 warning 记日志，**绝不因网络问题崩溃插件或清空已有数据**。
3. **远程数据源**：URL 需返回同 schema 的 JSON；列表字段追加去重，标量字段以新数据覆盖。

## 如何扩展热梗

### 方式一：编辑自带数据文件（推荐，扩展网络热梗库）

编辑 `data/hot_meme_data.json`，按上面的字段新增条目，重启/重载插件即可。也可把 `hot_source_data_file` 指向你自己的 JSON 文件。

### 方式二：配置远程数据源

在 WebUI「远程数据源 URL」里填入返回同 schema JSON 的 URL，插件会定时拉取并合并，实现热梗库集中维护、多实例同步。

### 方式三：命令学习（运行时动态扩展）

```
/hotmeme learn 关键词 回复1|回复2|回复3
```

### 方式四：配置面板自定义映射

在 WebUI「自定义热梗映射」中编辑 JSON/键值对（`热梗词 → 回复`）。

### 方式五：修改内置热梗库（代码级扩展）

编辑 `main.py` 中的 `BASE_MEMES` 字典，条目结构：

```python
{
    "keywords": ["新梗词"],        # 精准匹配
    "fuzzy": ["谐音变体"],          # 模糊匹配
    "context": ["语境词"],          # 出现则提升模糊置信度
    "negative": ["排除词"],         # 出现则作废命中
    "replies": ["回复一", "回复二"], # 回复候选
}
```

## 测试

在 AstrBot 自带的 venv 下运行：

```
D:\AstrBot\venv\Scripts\python.exe D:\AstrBot\data\plugins\hot_meme\tests\test_hot_meme.py
```

测试覆盖：热梗库加载成功率、关键词匹配与随机调用正确性、调用响应耗时（毫秒）、配置兼容性，并输出 pass/fail 与耗时统计。

## 常见问题

**Q：为什么群里发「羊肉串子」没反应？**
A：因为「串子」的热梗被 `羊肉串` 等排除语境词命中，属于防误判，符合预期。

**Q：学习的数据存在哪里？**
A：已学习热梗通过 AstrBot 的插件 KV 存储持久化；网络热梗库来自 `data/hot_meme_data.json` 与配置的远程 URL（内存合并，定时刷新）。

**Q：远程数据源拉取失败会影响插件吗？**
A：不会。所有网络/解析/文件异常均被捕获并记录 warning，失败时保留已有数据。

**Q：能适配多个平台吗？**
A：插件仅依赖 AstrBot 统一消息事件接口，理论上适配 AstrBot 支持的各类平台，不对特定平台做额外绑定。