# MicroCiv

基于终端的微型文明模拟器，使用 Python 与 curses 构建。

## 项目简介

MicroCiv 是一款回合制文明经营游戏，运行在终端中。游戏以方格网格为地图，采用鼠标优先的 curses 交互方式，地图格以 Unicode 块字符渲染。

### 功能特性

- 正方形网格随机地图生成，包含平原、森林、山地、河流、荒地五种地形
- 城市建设、道路网络、建筑建造、科技研究与评分系统
- 手动游玩（Play）与自动演示（Autoplay）两种模式
- 两种 Autoplay AI 策略：`Greedy`（分阶段贪心）与 `Random`（带权随机）
- 本地 Records 记录系统，支持 JSON 导出
- 像素字体渲染（标题、分数、回合数）
- AI 决策计时指标：决策时间、单回合耗时、全局会话耗时
- Autoplay 诊断指标：`decision_contexts`、逐回合 `score_breakdown`、Greedy 阶段与局部预算上下文

## 系统要求

- Python 3.11 或更高版本
- 支持 Unicode 与颜色的终端
- 支持 curses 鼠标事件的终端

## 安装

### 使用 uv（推荐）

```bash
git clone git@github.com:Zo-Live/microciv.git
cd microciv
uv venv
uv sync
```

### 使用 pip

```bash
git clone git@github.com:Zo-Live/microciv.git
cd microciv
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### （可选）安装数据分析脚本依赖

`scripts/analyze_batch.py` 依赖 `pandas` 与 `tabulate`，主游戏本身零运行依赖。按需安装：

```bash
uv sync --extra analysis        # uv
pip install -e ".[analysis]"    # pip
pip install -r scripts/requirements.txt  # 无 pyproject extras 环境
```

## 运行

```bash
python main.py
```

或

```bash
python -m microciv
```

若使用 uv，也可直接：

```bash
uv run python main.py
```

### 批量 AI 数据收集与分析

项目提供了无界面的批量运行脚本，用于让 AI 自动执行大量局数并导出结果：

```bash
# 快速批量运行（单一参数配置，输出 JSON / CSV / summary）
python scripts/batch_autoplay.py -n <games> --policy <policy> --label <tag>

# 大规模参数网格数据集生成（输出 dataset JSON / CSV / manifest）
python scripts/generate_dataset.py -n <games-per-combo> --label <tag>

# 生成诊断报告（需要 pandas + tabulate）
python scripts/analyze_batch.py --input <dataset.json> --output <report.md>
```

数据分析脚本依赖 `pandas` 和 `tabulate`；推荐通过项目的 `analysis` extras 安装：

```bash
uv sync --extra analysis
# 或
pip install -e ".[analysis]"
# 或（无 pyproject extras 环境）
pip install -r scripts/requirements.txt
```

常用参数：
- `-n` / `--games-per-combo`：每参数组合局数
- `--policy`：`greedy` 或 `random`
- `--map-size`：地图尺寸
- `--turn-limit`：回合上限
- `--seed-start`：起始种子
- `--label`：给批量输出文件附加标签
- `--policies` / `--map-sizes` / `--turn-limits` / `--difficulties`：覆盖数据集参数网格
- `--no-export-json` / `--no-export-csv` / `--no-write-summary`：控制单配置批跑输出

分析报告会额外汇总最终分数组成、逐回合分数组成、Greedy 阶段动作分布、局部预算与网络风险指标。详细参数请使用 `--help` 查看。

## 操作说明

MicroCiv 以鼠标为主要输入方式。

- **左键单击**：选择地图格、点击按钮、选择建筑 / 科技 / Records 条目
- **滚轮**：滚动 Records 列表
- `m`：打开游戏内菜单或从游戏内菜单返回游戏
- `b`：返回上一层（Records 详情→列表，Records 列表/空页→主菜单，子面板→上级面板）
- `t`：跳转到 Records 列表顶部
- `d`：跳转到 Records 列表底部
- `q`：退出程序
- 方向键：移动地图选中格或滚动 Records 列表

## 项目结构

```
microciv/
├── src/microciv/
│   ├── ai/            # AI 策略（Greedy、Random、Custom 占位）
│   ├── game/          # 核心规则与状态机
│   ├── records/       # 本地持久化与导出
│   ├── tui/           # 终端 UI 组件（像素字体）
│   ├── utils/         # 坐标、邻接、排序、RNG 工具
│   ├── session.py     # 运行时会话与自动播放辅助
│   ├── curses_app.py  # curses 控制器、路由与渲染
│   ├── app.py         # 程序入口
│   ├── config.py      # 路径配置
│   └── constants.py   # 全局常量与数值参数
├── scripts/           # 批量运行与数据分析脚本
├── docs/              # 项目文档与流程图
├── tests/             # 测试套件
├── data/              # 运行时 Records 数据
└── exports/           # 导出目录（JSON / CSV）
```

## 开发

运行测试：

```bash
.venv/bin/python -m pytest -q
```

运行 lint：

```bash
.venv/bin/ruff check src tests
```

类型检查：

```bash
.venv/bin/mypy
```

## 许可证

MIT
