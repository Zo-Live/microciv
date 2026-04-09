# MicroCiv TUI 实施计划

本文档不是补充规则文档，而是把 [tui.md](/home/zolive/microciv/docs/tui.md) 里的冻结规范拆成“按什么顺序实现、改哪些模块、每一步完成后算什么结果”的执行计划。

目标很明确：

1. 先把 TUI 做对。
2. 再在稳定界面上继续打磨 AI。
3. 当前阶段不允许为了赶进度牺牲页面流程、布局层级和视觉基础件。

## 1. 项目目标

本轮 TUI 重构必须同时满足三件事：

1. 页面流程严格符合 [microciv.md](/home/zolive/microciv/docs/microciv.md) 第 `13` 到 `24` 节。
2. 布局与视觉严格符合 [tui.md](/home/zolive/microciv/docs/tui.md)。
3. 最终程序在全屏终端下不依赖滚轮完成正常游戏流程，且地图成为最大视觉主体。

这不是局部修补，而是一次按规范重排界面结构的工程。

## 2. 范围

这次只处理 TUI，不改阶段一核心规则。

涉及范围：

1. `src/microciv/tui/app.py`
2. `src/microciv/tui/screens/`
3. `src/microciv/tui/widgets/`
4. `src/microciv/tui/renderers/`
5. `src/microciv/tui/presenters/`

必要时允许新增 TUI 内部模块，但不应把游戏规则重新塞回 TUI 层。

不在本轮优先范围内的内容：

1. `Baseline` 策略增强
2. `Expert / Custom` AI 真实实现
3. 非必要的规则改动
4. Records 数据结构改版

## 3. 总体顺序

实施顺序固定如下，不要跳着做：

```text
Phase 0  对齐当前代码与规范
   |
Phase 1  先立视觉基础件
   |
Phase 2  再立页面状态机
   |
Phase 3  重做菜单与地图选择
   |
Phase 4  重做游戏主界面骨架
   |
Phase 5  接上下文操作面板
   |
Phase 6  接 Autoplay 专属表现
   |
Phase 7  重做终局与 Records
   |
Phase 8  全面校对对齐与交互
```

原因：

1. 如果先改具体页面，不先统一视觉原件，后面会全盘返工。
2. 如果先堆交互，不先理顺页面状态机，页面切换会继续互相打架。
3. 如果不先把游戏主界面骨架定死，后面的城市面板和 Autoplay 面板都会再次挤占地图区。

## 4. 当前目录与建议落点

基于当前仓库，建议按下面的职责分层组织：

```text
src/microciv/tui/
├── app.py                  # 应用入口、全局绑定、screen 跳转入口
├── presenters/
│   ├── game_session.py     # 逻辑状态到界面状态的适配
│   ├── status.py           # 右侧小字信息区与状态摘要
│   └── state_machine.py    # 新增：统一页面状态与切换规则
├── renderers/
│   ├── map.py              # 六边形地图渲染
│   ├── logo.py             # 7 六边形 LOGO
│   ├── digits.py           # 新增：小型/大型点阵数字与标题字
│   └── hexes.py            # 新增：纯色六边形图元
├── screens/
│   ├── menu.py             # 初始菜单
│   ├── setup.py            # 地图选择
│   ├── game.py             # 手动 / 自动共用主界面
│   ├── final.py            # 终局界面
│   └── records.py          # 记录列表 / 详情
└── widgets/
    ├── logo.py             # LOGO 挂载件
    ├── map_grid.py         # 地图部件
    ├── side_panel.py       # 新增：右侧窄栏骨架
    ├── action_panel.py     # 新增：普通格/城市/确认面板
    ├── metric_panel.py     # 新增：SCORE / STEP / 小字信息区
    └── record_cards.py     # 新增：双列记录卡片
```

这里最重要的原则是：

1. `renderers/` 只负责“怎么画”。
2. `widgets/` 只负责“怎么摆”和“怎么接事件”。
3. `screens/` 只负责“当前页面有哪些区域”。
4. `presenters/` 只负责“当前状态该显示什么”。

## 5. 每阶段实施内容

## 5.1 Phase 0：先做结构校对

目标：把当前代码与 [tui.md](/home/zolive/microciv/docs/tui.md) 的差距列成明确修改面，不直接写视觉细节。

需要完成：

1. 盘点每个现有 screen 是否符合 `页面总流程`。
2. 盘点 `game.py` 是否把右侧面板做成了“常驻大状态栏”。
3. 盘点 `map_grid.py` 是否仍在格内放文字、符号或覆盖信息。
4. 盘点 `records.py` 是否仍保留与规范不符的按钮布局。
5. 盘点 `logo.py` 和 `map.py` 是否还在使用带边框六边形。

交付结果：

1. 一份代码层 TODO 列表。
2. 一组准备被替换或拆分的模块名单。

完成标准：

1. 不改逻辑。
2. 只输出重构边界。

## 5.2 Phase 1：先立视觉基础件

目标：先把后续所有页面都会复用的视觉原件做对。

必须先完成的原件：

1. 纯色六边形图元
2. 选中态白边框
3. 地图六边形网格排布
4. 资源信息区六边形图标
5. 7 六边形 LOGO
6. 小型点阵数字
7. 大型点阵数字

关键要求：

1. 六边形默认没有边框。
2. 只有地图当前选中格有白边框。
3. 地图六边形、资源图标、LOGO 六边形是同一套视觉语言。
4. 小型数字用于右侧信息区。
5. 大型数字用于 `SCORE`、终局分数、标题强化区域。
6. 数字阴影方向固定为向右，且必须贴轮廓。

建议新增模块：

1. `src/microciv/tui/renderers/hexes.py`
2. `src/microciv/tui/renderers/digits.py`

完成标准：

1. 任何页面都不再依赖文字塞进地图格表达状态。
2. 任何六边形默认都不出现黑框、灰框、白框。
3. 在独立测试页里能单独渲染：
   - LOGO
   - 一小片地图
   - 四种资源图标
   - 小型/大型数字

## 5.3 Phase 2：页面状态机归一

目标：把页面切换逻辑先做成单一真源。

必须覆盖的状态：

1. `initial_menu`
2. `map_select_play`
3. `map_select_autoplay`
4. `game_play`
5. `game_autoplay`
6. `in_game_menu`
7. `final_screen`
8. `records_list`
9. `record_detail`

必须覆盖的跳转：

```text
Initial Menu
  -> Play Map Select
  -> Autoplay Map Select
  -> Records List
  -> Exit

Play Map Select
  -> Game Screen
  -> Menu

Autoplay Map Select
  -> Game Screen
  -> Menu

Game Screen
  -> In-game Menu
  -> Final Screen

In-game Menu
  -> Continue
  -> Menu
  -> Exit

Final Screen
  -> Restart
  -> Menu
  -> Exit

Records List
  -> Record Detail
  -> Back

Record Detail
  -> Back to List
```

建议新增模块：

1. `src/microciv/tui/presenters/state_machine.py`

完成标准：

1. 页面流转只经过一套路由。
2. `Play` 和 `Autoplay` 的区别只体现在配置项和权限，不产生两套平行 UI 体系。
3. `m / b / q / d / t` 的行为在对应页面固定。

## 5.4 Phase 3：重做初始菜单与地图选择

目标：先把用户进入游戏前的两层页面做对。

### 初始菜单

必须满足：

1. 左侧只有 LOGO 与 `MicroCiv`。
2. 右侧只有 `Play / Autoplay / Records / Exit`。
3. 不能提前出现 `Baseline / Normal / Speed`。
4. 终端放大后左右区域同步扩张，不缩在中间。

### 地图选择

必须满足：

1. 左侧显示地图预览。
2. 右侧显示配置项。
3. `Play` 版只显示地图参数。
4. `Autoplay` 版额外显示 `AI Type / Custom Input / Playback`。
5. `Recreate` 只刷新地图，不重置配置。
6. `Menu` 返回初始菜单。

需要优先修改：

1. `src/microciv/tui/screens/menu.py`
2. `src/microciv/tui/screens/setup.py`
3. `src/microciv/tui/widgets/logo.py`
4. `src/microciv/tui/widgets/map_grid.py`

完成标准：

1. 初始菜单与地图选择界面已经完全符合 [tui.md](/home/zolive/microciv/docs/tui.md)。
2. 后续进入游戏时不再需要“补充解释当前模式”。

## 5.5 Phase 4：重做游戏主界面骨架

目标：把最重要的主界面版式先拉正。

页面结构必须固定为：

```text
+------------------------------+------------------+
|                              | SCORE            |
|                              | STEP             |
|   左侧：近满高正方形地图区     | Skip / 小字信息区 |
|                              |                  |
+------------------------------+------------------+
```

必须满足：

1. 左侧地图区是主角。
2. 左侧地图区是近满高正方形。
3. 右侧是窄栏。
4. 左侧底部不留提示区。
5. 右侧底部保留小字信息区。
6. 默认状态下不展开大资源表或大科技表。
7. 正常游戏流程不需要滚轮。

需要优先修改：

1. `src/microciv/tui/screens/game.py`
2. `src/microciv/tui/widgets/map_grid.py`
3. `src/microciv/tui/widgets/side_panel.py`
4. `src/microciv/tui/widgets/metric_panel.py`
5. `src/microciv/tui/presenters/status.py`

完成标准：

1. 即便还没接城市面板，默认游戏界面也已经正确利用全屏。
2. 当前界面中没有任何需要滚动才能看到的核心动作。

## 5.6 Phase 5：接上下文面板与操作流程

目标：把“点击什么格，右侧出现什么面板”做成确定规则。

必须按顺序接入：

1. 普通地形默认状态
2. 普通地形建造面板
3. 道路格只高亮不出操作
4. 城市操作面板
5. 建筑确认面板
6. 研究确认面板
7. `Skip`
8. 失败提示生命周期

交互规则必须固定：

1. 一次只选中一个格。
2. 点击已选中格取消选中。
3. `Cancel` 取消选中或返回上一级面板。
4. Build / Research 失败不结束回合。
5. Build / Research 成功后推进回合并刷新分数。
6. 提示只显示在右下小字区。

需要优先修改：

1. `src/microciv/tui/screens/game.py`
2. `src/microciv/tui/widgets/action_panel.py`
3. `src/microciv/tui/presenters/game_session.py`
4. `src/microciv/tui/presenters/status.py`

完成标准：

1. 手动游玩整局不需要滚轮。
2. 所有人工操作都通过明确的上下文面板完成。
3. 地图点击和右侧面板切换不再互相冲突。

## 5.7 Phase 6：接 Autoplay 专属表现

目标：在不复制一套页面的前提下，让自动模式看起来就是自动模式。

必须满足：

1. `Autoplay` 与 `Play` 共用主界面骨架。
2. `Autoplay` 不出现人工操作按钮。
3. `SCORE / STEP` 位置与手动模式一致。
4. 底部小字区显示：
   - `mode`
   - `ai`
   - `tip`
5. `Normal` 逐回合同步刷新。
6. `Speed` 批量低频刷新。
7. 自动运行中仍可：
   - `m`
   - `q`

需要优先修改：

1. `src/microciv/tui/screens/game.py`
2. `src/microciv/tui/presenters/game_session.py`
3. `src/microciv/tui/presenters/status.py`

完成标准：

1. 自动模式下用户不会误以为还能手动下指令。
2. `Normal` 与 `Speed` 的差异只体现在刷新节奏，不体现在页面结构。

## 5.8 Phase 7：终局与 Records

目标：把后半段页面全部拉回规范。

### 终局页

必须满足：

1. 左侧仍是大正方形终局地图。
2. 右侧只放分数和 `Restart / Menu / Exit`。
3. 不退化成普通摘要卡片。

### Records 列表

必须满足：

1. 无记录时不显示 `Export`。
2. 无记录时 `Back` 居中。
3. 有记录时是左右双列卡片。
4. 两列横向铺满宽度，不留大块空白。
5. Records 是唯一允许滚轮的主页面。

### Records 详情

必须满足：

1. 顶部是左地图右信息。
2. 向下滚动才进入统计区域。
3. `Back` 与 `b` 都返回列表。

需要优先修改：

1. `src/microciv/tui/screens/final.py`
2. `src/microciv/tui/screens/records.py`
3. `src/microciv/tui/widgets/record_cards.py`

完成标准：

1. 终局和 Records 不再是主界面规范之外的独立风格。
2. 所有页面共享同一套视觉语言。

## 5.9 Phase 8：最后做对齐、间距与验收

目标：解决“能用”和“像规范”之间最后那段差距。

必须逐项检查：

1. 全屏终端下每个页面是否真正扩张利用空间。
2. 地图区是否始终是最大视觉主体。
3. 右侧窄栏是否存在多余空白或过度挤压。
4. 选项间距是否足够，正常操作是否完全不需要滚轮。
5. 字体、点阵字、LOGO、六边形图标是否语言统一。
6. 六边形默认是否真的无边框。
7. 只有选中格是否真的有白框。
8. 小字信息区是否始终留在右下。
9. Markdown 示意图中的字符误差是否没有被带进程序。

完成标准：

1. TUI 达到可以让人完整手测的程度。
2. 后续 AI 工作不再受“界面难以操作”阻塞。

## 6. 阶段依赖

必须遵守下面的依赖关系：

```text
视觉原件
   -> 页面骨架
   -> 游戏主界面
   -> 上下文操作面板
   -> Autoplay
   -> 终局 / Records
   -> 最终对齐验收
```

禁止反向施工：

1. 不要先做 Records 卡片动画，再回头修地图骨架。
2. 不要先堆 Autoplay 展示，再回头修手动模式面板层级。
3. 不要先做局部美术特效，再回头修状态机。

## 7. 每阶段验收口径

每个阶段都至少要过三类检查：

1. 结构检查
   - 页面和模块职责是否对上
2. 交互检查
   - 鼠标、快捷键、面板切换是否符合文档
3. 视觉检查
   - 布局比例、对齐、边框、地图占比是否符合文档

建议每阶段至少补一类自动化检查：

1. `Textual` screen smoke test
2. 关键页面渲染断言
3. 基础交互路径测试

## 8. 本轮完成定义

本轮 TUI 工作只有在下面条件同时满足时才算完成：

1. 初始菜单、地图选择、游戏主界面、游戏内菜单、终局、Records 列表、Records 详情全部按 [tui.md](/home/zolive/microciv/docs/tui.md) 重做完成。
2. 手动模式完整游玩一局不需要滚轮。
3. 自动模式不会暴露人工操作按钮。
4. 地图格、LOGO、资源六边形图标默认都无边框，只有选中格出现白边框。
5. 小型和大型点阵数字都已落地，并符合右侧阴影规则。
6. 全屏终端下界面已正确铺满，不再缩成中央小窗。

## 9. 实施建议

建议后续真正动手时按下面的提交粒度推进：

1. 提交 1：视觉原件与公共部件
2. 提交 2：页面状态机与菜单/地图选择
3. 提交 3：游戏主界面骨架
4. 提交 4：手动模式上下文面板
5. 提交 5：Autoplay 专属表现
6. 提交 6：终局与 Records
7. 提交 7：最终对齐与测试补齐

这样做的好处是：

1. 每一步都能独立回看。
2. 出现偏差时容易定位。
3. 不会把“布局问题、交互问题、视觉问题”混在同一次提交里。
