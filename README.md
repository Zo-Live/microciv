# MicroCiv

基于终端的微型文明模拟器，使用 Python 与 curses 构建。

## 项目简介

MicroCiv 是一款回合制文明经营游戏，运行在终端中。游戏以方格网格为地图，采用鼠标优先的 curses 交互方式，地图格以 Unicode 块字符渲染。

### 功能特性

- 正方形网格随机地图生成，包含平原、森林、山地、河流、荒地五种地形
- 城市建设、道路网络、建筑建造、科技研究与评分系统
- 手动游玩（Play）与自动演示（Autoplay）两种模式
- 两种 Autoplay AI 策略：`Greedy`（贪心）与 `Random`（随机）
- 本地 Records 记录系统，支持 JSON 导出
- 像素字体渲染（标题、分数、回合数）
- AI 决策计时指标：决策时间、单回合耗时、全局会话耗时

## 系统要求

- Python 3.13 或更高版本
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

## 运行

```bash
python main.py
```

或

```bash
python -m microciv
```

### 批量 AI 数据收集与分析

项目提供了无界面的批量运行脚本，用于让 AI 自动执行大量局数并导出结果（JSON + CSV）：

```bash
# 快速批量运行（单一参数配置）
python scripts/batch_autoplay.py -n 100 --policy greedy

# 大规模参数网格数据集生成
python scripts/generate_dataset.py -n 10

# 生成诊断报告（需要 pandas + tabulate）
python scripts/analyze_batch.py --input exports/dataset/dataset.json --output docs/report.md
```

数据分析脚本依赖 `pandas` 和 `tabulate`，可通过以下方式安装：

```bash
uv add --dev pandas tabulate
# 或
pip install pandas tabulate
```

常用参数：
- `-n` / `--games-per-combo`：每参数组合局数
- `--policy`：`greedy` 或 `random`
- `--map-size`：地图尺寸
- `--turn-limit`：回合上限
- `--seed-start`：起始种子

详细参数请使用 `--help` 查看。

## 操作说明

MicroCiv 以鼠标为主要输入方式。

- **左键单击**：选择地图格、点击按钮、选择建筑/科技/Records 条目
- **滚轮**：在 Records 列表中滚动翻页
- `m`：打开游戏内菜单
- `b`：返回上一层（Records 详情→列表，Records 列表/空页→主菜单，子面板→上级面板）
- `t`：跳转到 Records 列表顶部
- `d`：跳转到 Records 列表底部
- `q`：退出程序
- 方向键：移动地图选中格或滚动 Records

## 项目结构

```
microciv/
├── src/microciv/
│   ├── ai/            # AI 策略（Greedy、Random）
│   ├── game/          # 核心规则与状态机
│   ├── records/       # 本地持久化与 JSON 导出
│   ├── tui/           # 终端 UI 组件（像素字体）
│   ├── session.py     # 运行时会话辅助
│   ├── curses_app.py  # curses 控制器与渲染
│   └── app.py         # 程序入口
├── docs/              # 项目文档与流程图
├── tests/             # 测试套件
├── data/              # 运行时 Records 数据
└── exports/           # JSON 导出
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

## 许可证

MIT
