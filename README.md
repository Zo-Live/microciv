# MicroCiv

## 当前状态

当前仓库已完成阶段一的核心实现，当前可用内容包括：

1. `docs/microciv.md`
   阶段一需求与规则文档
2. `project.md`
   阶段一执行冻结规范
3. `main.py`
   仓库根目录薄入口，负责引导到 `src/`
4. `pyproject.toml`
   Python 项目配置
5. `src/microciv/game/`
   阶段一逻辑层、地图生成、结算、动作系统
6. `src/microciv/ai/`
   `Baseline` 与 `Random` 策略实现
7. `src/microciv/records/`
   本地持久化与 CSV 导出
8. `src/microciv/tui/`
   最小可用 Textual 界面：主菜单、地图设置、游戏页、终局页、Records 页

当前项目结构如下。

## 已确认的项目结构

```text
microciv/
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── main.py
├── project.md
├── docs/
│   ├── microciv.md
│   ├── logo.jpg
│   └── number-like-this.png
├── data/
│   └── records.json
├── exports/
├── tests/
└── src/
    └── microciv/
        ├── __init__.py
        ├── app.py
        ├── config.py
        ├── constants.py
        ├── game/
        │   ├── __init__.py
        │   ├── enums.py
        │   ├── models.py
        │   ├── actions.py
        │   ├── engine.py
        │   ├── mapgen.py
        │   ├── resources.py
        │   ├── networks.py
        │   └── scoring.py
        ├── ai/
        │   ├── __init__.py
        │   ├── policy.py
        │   ├── baseline.py
        │   └── random_policy.py
        ├── tui/
        │   ├── __init__.py
        │   ├── screens/
        │   ├── widgets/
        │   ├── renderers/
        │   └── presenters/
        ├── records/
        │   ├── __init__.py
        │   ├── models.py
        │   ├── store.py
        │   └── export.py
        └── utils/
            ├── __init__.py
            ├── rng.py
            └── hexgrid.py
```

## 结构说明

### 入口层

1. `main.py`
   保持为仓库根目录下的薄入口，只负责启动应用
2. `src/microciv/app.py`
   作为程序主入口，负责初始化配置、加载 Records、启动 Textual App

### 逻辑层

1. `src/microciv/game/`
   放置阶段一的核心规则逻辑，不依赖具体 UI
2. `enums.py`
   定义地形、建筑、科技、模式、动作等枚举
3. `models.py`
   定义 `GameConfig`、`GameState`、城市、道路、网络等数据结构
4. `actions.py`
   定义动作对象与合法性校验入口
5. `engine.py`
   负责动作执行、回合推进、结算顺序与终局判断
6. `mapgen.py`
   负责可复现的地图生成
7. `resources.py`
   负责资源归属、停工判定、建筑与地形产出
8. `networks.py`
   负责网络识别、并网与共享资源/科技状态
9. `scoring.py`
   负责当前分数与终局分数计算

### AI 层

1. `src/microciv/ai/policy.py`
   定义策略接口，给阶段二继续扩展
2. `src/microciv/ai/baseline.py`
   实现阶段一 Baseline AI
3. `src/microciv/ai/random_policy.py`
   实现对照用随机策略，仅用于测试与实验比较

### TUI 层

1. `src/microciv/tui/`
   放置所有 Textual 表现层代码
2. `screens/`
   放置主菜单、地图选择、游戏界面、Records、终局等页面
3. `widgets/`
   放置地图、右侧面板、LOGO、记录卡片等可复用组件
4. `renderers/`
   放置地图、点阵字、LOGO 等渲染逻辑
5. `presenters/`
   负责把逻辑层状态转换为界面展示数据，避免 UI 直接处理复杂规则

### Records 与数据层

1. `src/microciv/records/store.py`
   负责 `data/records.json` 的读写与 FIFO 裁剪
2. `src/microciv/records/export.py`
   负责 CSV 导出到 `exports/`
3. `src/microciv/records/models.py`
   定义记录结构和导出字段
4. `data/`
   运行时生成，本地持久化 Records
5. `exports/`
   运行时生成，保存 CSV 导出文件

### 测试层

1. `tests/`
   放置地图生成、规则结算、Baseline AI、Records 持久化等测试
2. 测试必须优先覆盖 `project.md` 中冻结的参数、阈值、顺序和导出口径

### 工具层

1. `src/microciv/utils/rng.py`
   统一管理带种子的随机数接口，确保地图和 AI 可复现
2. `src/microciv/utils/hexgrid.py`
   提供六边形坐标、邻接、距离、路径等通用工具

## 实现约束

1. 逻辑层与 TUI 层必须解耦，AI 直接调用逻辑层，不依赖 Textual
2. 阶段一只实现 `Baseline` 的可运行 Autoplay，`Expert` 与 `Custom` 只保留接口
3. `data/` 与 `exports/` 属于运行时目录，可以在程序启动时自动创建
4. 后续实现以 `project.md` 为冻结规范，以 `docs/microciv.md` 为需求背景说明
