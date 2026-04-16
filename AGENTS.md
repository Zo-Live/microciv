# MicroCiv 项目指南

本文件面向 AI 编程助手，帮助你快速理解并修改本项目。阅读者被假设对此项目一无所知。

---

## 项目概览

**MicroCiv** 是一个基于终端的回合制微型文明模拟器，使用 Python 3.13+ 和标准库 `curses` 构建。项目采用正方形网格地图，支持鼠标优先的 curses 交互，地图格使用 Unicode 块字符（2×4 像素块）渲染。

主要功能：

- 程序化随机地图生成（平原、森林、山地、河流、荒地）
- 城市建设、道路网络、建筑建造、科技研究与评分系统
- 手动游玩（Play）与自动演示（Autoplay）两种模式
- 两种 AI 策略：`Greedy`（贪心）与 `Random`（随机）
- 本地 Records 记录系统，支持 JSON 持久化与导出
- 像素字体渲染（标题、分数、回合数）

项目无外部运行时依赖，所有代码均为纯 Python 标准库。

---

## 技术栈

- **语言**: Python >= 3.13
- **UI 框架**: 标准库 `curses`（支持鼠标事件、颜色对、Unicode 块字符渲染）
- **包管理器**: `uv`（推荐），也支持 `pip`
- **构建后端**: `hatchling`
- **代码检查**: `ruff`（lint + format）、`mypy`（类型检查）
- **测试框架**: `pytest` + `pytest-cov`
- **无 CI/CD、无 Makefile、无 Docker**

---

## 安装与运行

### 使用 uv（推荐）

```bash
uv venv
uv sync
python main.py
```

### 使用 pip

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python main.py
```

### 启动方式

- `python main.py`
- `python -m microciv`

`main.py` 的作用是将 `src/` 注入 `sys.path`，然后调用 `microciv.app:main()`。

---

## 常用命令

```bash
# 运行游戏
python main.py

# 批量 AI 数据收集
python scripts/batch_autoplay.py -n 100 --policy greedy

# 大规模参数网格数据集生成（同时导出 JSON 和 CSV）
python scripts/generate_dataset.py -n 10

# 生成诊断报告（需安装 pandas + tabulate）
python scripts/analyze_batch.py --input exports/dataset/dataset.json --output docs/report.md

# 运行全部测试
python -m pytest -q

# 运行单个测试模块
python -m pytest tests/test_engine.py -q

# 运行单个测试
python -m pytest tests/test_engine.py::test_name -q

# 代码检查
ruff check src tests

# 类型检查
mypy
```

---

## 项目结构

```
microciv/
├── src/microciv/
│   ├── ai/                  # AI 策略
│   │   ├── policy.py        # Policy Protocol
│   │   ├── greedy.py        # GreedyPolicy
│   │   ├── random_policy.py # RandomPolicy
│   │   └── custom.py        # 自定义策略占位
│   ├── game/                # 核心游戏规则与状态机
│   │   ├── models.py        # 所有状态数据类
│   │   ├── engine.py        # GameEngine 状态转换
│   │   ├── actions.py       # Action 模型与验证
│   │   ├── enums.py         # 所有 StrEnum 枚举
│   │   ├── networks.py      # 路网连通性（BFS/并查集）
│   │   ├── resources.py     # 资源所有权与每回合结算
│   │   ├── mapgen.py        # 程序化地图生成
│   │   └── scoring.py       # 分数计算
│   ├── records/             # 本地持久化与导出
│   │   ├── models.py        # RecordEntry 与快照数据类
│   │   ├── store.py         # JSON 文件 I/O、schema 版本管理
│   │   └── export.py        # JSON 导出到 exports/
│   ├── tui/                 # 终端 UI 组件
│   │   └── pixel_font.py    # 块字符像素字体渲染
│   ├── utils/               # 工具函数
│   │   ├── grid.py          # Coord 类型、邻居计算、排序
│   │   └── rng.py           # 带种子的 RNG 包装
│   ├── app.py               # 程序入口
│   ├── curses_app.py        # curses 控制器与渲染（最大文件）
│   ├── session.py           # 运行时会话辅助
│   ├── config.py            # 路径配置
│   └── constants.py         # 全局常量与平衡参数
├── scripts/                 # 批量运行与数据分析脚本
│   ├── batch_autoplay.py    # 单一配置批量运行
│   ├── generate_dataset.py  # 参数网格数据集生成
│   └── analyze_batch.py     # 数据集诊断报告生成
├── tests/                   # 测试套件（pytest）
├── data/                    # 运行时 Records 数据 (records.json)
├── exports/                 # JSON 导出目录
├── docs/                    # 中文项目文档与流程图
├── main.py                  # 启动脚本
├── pyproject.toml           # 项目配置
└── uv.lock                  # uv 依赖锁定
```

---

## 运行时架构

**入口流程**:

```
main.py -> sys.path 注入 src -> microciv.app.main()
    -> CursesMicroCivApp().run()
    -> curses.wrapper(_main)
```

**核心游戏循环**:

```
GameConfig
    -> session.create_game_session()
        -> MapGenerator().generate(config)   # 地图生成
        -> GameState.empty(config) + 填充 board
        -> 挂载 Policy (Greedy/Random/None)
    -> GameSession (持有 GameState + GameEngine + Policy)
    -> 每回合: apply_action(action)
        -> validate_action()                 # 动作合法性验证
        -> _apply_*()                        # 状态变更
        -> recompute_networks()              # 网络连通性
        -> recompute_resource_ownership()    # 资源归属
        -> settle_resources()                # 资源结算
        -> calculate_score()                 # 分数计算
        -> turn += 1 或 is_game_over = True
```

**应用分层**:

1. **UI 层**: `CursesMicroCivApp`（curses 事件循环 + 渲染）
2. **控制器层**: `MicroCivController`（UI 无关的状态路由与交互逻辑）
3. **会话层**: `GameSession`（封装 `GameState`、`GameEngine`、`Policy`）
4. **引擎层**: `GameEngine`（所有状态转换与回合推进）
5. **领域层**: `game/models.py`、`game/actions.py`、`game/enums.py`
6. **系统层**: `networks.py`、`resources.py`、`scoring.py`、`mapgen.py`
7. **持久层**: `records/store.py`、`records/models.py`、`records/export.py`

---

## 编码规范与开发约定

### 通用约定

- **每模块首行**: `from __future__ import annotations`
- **坐标系**: `Coord = tuple[int, int]`，格式为 `(row, col)` / `(x, y)`
  - 确定性排序通过 `coord_sort_key()` 实现
- **枚举**: 全部为 `StrEnum`，便于 JSON 序列化
- **数据类**:
  - 状态类用 `@dataclass(slots=True)`
  - 不可变值对象用 `@dataclass(frozen=True, slots=True)`（如 `Action`、record snapshots）
- **状态可变**: `GameState` 及其嵌套对象都是可变的；AI 前瞻使用 `deepcopy` + `simulate_action()`
- **网络合并**: 道路连接城市时，`recompute_networks()` 使用 BFS 发现连通分量，并通过 `Network.merge_from()` 合并资源与科技
- **资源结算**: 每次 `apply_action()` 后都会调用 `settle_resources()`，而非仅回合结束时
- **地图生成质量门**: `MAX_MAP_RETRIES = 20`，确保 buildable ratio、plain ratio、wasteland ratio、河流邻接荒地等约束满足

### Ruff 配置

- `line-length = 100`
- `target-version = "py313"`
- 启用的规则集：`B` (bugbear)、`E` (pycodestyle errors)、`F` (pyflakes)、`I` (isort)、`UP` (pyupgrade)

### 关键类与函数速查

**状态模型**:
- `GameConfig.for_play(...)` / `GameConfig.for_autoplay(...)` — 配置工厂
- `GameState.empty(config)` — 空状态工厂
- `Tile(base_terrain, occupant=OccupantType.NONE)`
- `ResourcePool(food, wood, ore, science)` — `.can_afford()`, `.spend()`, `.merge()`

**动作**:
- `Action.build_city(coord)`, `Action.build_road(coord)`, `Action.build_building(city_id, type)`, `Action.research_tech(city_id, type)`, `Action.skip()`

**引擎**:
- `GameEngine(state).apply_action(action) -> EngineResult`

**AI**:
- `GreedyPolicy().select_action(state) -> Action`
- `RandomPolicy(seed).select_action(state) -> Action`
- `simulate_action(state, action) -> GameState`（deepcopy 前瞻）

**记录**:
- `RecordEntry.from_game_state(record_id=..., timestamp=..., state=...)`
- `RecordStore(path).append_completed_game(state) -> RecordEntry`
- `export_records_json(database, output_dir) -> Path`

---

## 测试策略

测试框架为 `pytest`，配置在 `pyproject.toml` 中。

**测试文件分布**:

- `test_smoke.py` — 配置默认值与枚举基础断言
- `test_engine.py` — 核心引擎动作验证（建城、修路、建筑、科技、跳过、游戏结束）
- `test_actions.py` — 动作合法性
- `test_models.py` — 数据模型验证
- `test_mapgen.py` — 地图生成可复现性、尺寸、质量规则、河流数量
- `test_networks.py` — 网络连通性
- `test_resources.py` — 资源结算
- `test_scoring.py` — 分数计算
- `test_ai.py` — Greedy/Random 策略合法性、Greedy 食物救援行为、全游戏完成性、得分基准
- `test_records.py` — RecordEntry 序列化、Store 持久化、schema 迁移、FIFO 裁剪、导出
- `test_grid.py`、`test_curses_app.py`、`test_tui.py` 等 — 工具与 UI 测试

**测试风格特点**:

- 大量使用 `GameState.empty(GameConfig.for_play())` 手动构造最小状态
- 集成测试与单元测试混合：如 `test_greedy_and_random_can_finish_full_games` 会跑完整 30 回合游戏
- 使用 `tmp_path` 和 `monkeypatch` 进行文件系统与常量隔离测试
- 测试中包含性能/基准类断言（如 `assert state.score >= 500`）

---

## 安全与部署说明

- **无传统部署流程**：这是一个本地运行的终端应用，没有 CI/CD、Docker 或云部署配置。
- **数据文件位置**：运行时数据保存在 `data/records.json`，不兼容的旧文件会被重命名为 `.incompatible` 备份。
- **无外部运行时依赖**：纯标准库实现，不存在供应链攻击风险。
- **输入来源**：当前仅通过 `curses` 接受本地鼠标/键盘输入，无网络接口，无需考虑网络攻击面。
- **修改敏感代码时**：注意 `GameEngine.apply_action()` 是状态变更的核心路径，任何改动都需要同步更新 `tests/test_engine.py` 和 `tests/test_actions.py`。

---

## 修改建议

若需扩展功能，建议优先关注以下文件：

- **新增动作类型**: `game/actions.py` + `game/engine.py`
- **状态机扩展**: `game/engine.py` + `game/models.py`
- **策略调整**: `ai/greedy.py` + `ai/policy.py`
- **UI 路由与渲染**: `curses_app.py`
- **平衡参数调整**: `constants.py`（注意同步测试中的硬编码断言）
- **批量运行脚本**: `scripts/batch_autoplay.py`、`scripts/generate_dataset.py`
- **数据分析脚本**: `scripts/analyze_batch.py`
- **Records 模型扩展**: `records/models.py`（新增字段需同步更新 `CSV_FIELD_ORDER` 与 `from_dict`/`to_dict`）
