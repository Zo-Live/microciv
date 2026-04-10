# MicroCiv TUI 重构实施计划

本文档不是重复 [tui.md](/home/zolive/microciv/docs/tui.md)，而是把其中已经冻结的页面规则、交互规则、视觉规则和新增的正式技术路线，拆成“按什么顺序实现、每一步要做到什么、做到什么才算通过”的执行计划。

当前目标只有一个：

1. 先把 TUI 做到可稳定游玩、可稳定观察、可稳定重开。
2. 在此之前，不继续把精力投到 AI 策略细化。

## 1. 本轮完成定义

本轮 TUI 重构只有在下面条件同时满足时才算完成：

1. 初始菜单、地图选择、游戏主界面、游戏内菜单、终局、Records 列表、Records 详情全部严格对齐 [tui.md](/home/zolive/microciv/docs/tui.md)。
2. 手动模式完整游玩一局不需要滚轮。
3. 自动模式完整观看一局不暴露人工操作按钮。
4. `Restart` 不再触发 `DuplicateIds` 或其他 screen 生命周期错误。
5. 左侧地图与终局地图都成为近满高正方形主区域，不再缩成中央小窗。
6. 六边形、LOGO、资源图标、数字都切换到正式高精度渲染路径，不再以字符拼图作为正式实现。

## 2. 硬性约束

本轮实现必须遵守以下硬约束：

1. TUI 主框架固定为 `Textual`。
2. 富文本和普通说明文字固定为 `Rich`。
3. 六边形地图、LOGO、资源图标、小型数字、大型数字的正式路径固定为“离屏光栅生成 + 图像显示后端”。
4. `textual-image` 或同类库只作为“显示后端”，不负责美术逻辑本身。
5. 地图不再采用“每格一个字符控件”的正式方案，而是整张地图一次性渲染。
6. 资源图标、LOGO、数字不再采用“字符拼接”的正式方案。
7. 游戏内除 Records 外，任何页面都不得依赖滚轮完成正常操作。
8. 所有 transient screen 不允许复用会重复冲突的固定 widget id。
9. `Restart` 必须先完成 screen 栈归一，再进入新的地图选择页。
10. 如果 `tui.md` 的结构示意图与旧实现冲突，以 [tui.md](/home/zolive/microciv/docs/tui.md) 为准。
11. `19.4 LOGO 规范` 中当前版本的“组合关系简记”只用于表达相对排布，不作为精确几何模板。
12. LOGO 与地图的正式观感必须接近 [logo.jpg](/home/zolive/microciv/docs/logo.jpg)：六边形之间只有细小缝隙，不允许被拉成明显间隔。
13. 地图中的细小缝隙要被视为选中白边框的预留空间；默认状态下不画成粗边框。

## 3. 正式技术路线

### 3.1 渲染总路线

正式渲染路线固定为：

```text
逻辑状态
   -> Presenter 适配
   -> 离屏渲染层生成图像
   -> 图像显示后端挂到 Textual Widget
   -> 鼠标命中测试回到逻辑坐标
```

职责分层固定如下：

1. `presenters/`
   负责把 `GameState / RecordEntry / Config` 转成界面需要的数据。
2. `renderers/`
   负责生成图像，不直接处理 screen 跳转。
3. `widgets/`
   负责摆放、刷新、命中测试和事件转发。
4. `screens/`
   负责页面区域组合与页面级动作。
5. `app.py`
   负责全局 screen 生命周期与路由入口。

### 3.2 离屏渲染层要求

必须建立统一的离屏渲染层，至少覆盖：

1. `logo_renderer`
2. `digit_renderer_small`
3. `digit_renderer_large`
4. `resource_hex_renderer`
5. `map_renderer`

每种渲染器都必须满足：

1. 输入是纯数据，不读 UI 状态。
2. 输出是可直接显示的图像对象或缓存文件。
3. 同一输入多次渲染结果一致。
4. 可按目标尺寸重绘，不依赖字符单元宽高。
5. 六边形之间的间隙控制必须可配置，但默认收敛到“仅保留细小缝隙”的级别。

### 3.3 图像显示后端要求

图像显示后端固定承担以下职责：

1. 在 Textual 中显示离屏生成结果。
2. 响应 widget 尺寸变化，触发重新渲染或缩放。
3. 支持地图、LOGO、数字、资源图标四类图像。

图像显示后端明确不承担：

1. 六边形拼接规则
2. 数字模板定义
3. LOGO 组合规则
4. 地图命中测试逻辑

### 3.4 地图命中测试要求

地图已经不是一个个 tile button 之后，点击命中必须改成：

```text
鼠标位置
   -> 地图图像局部坐标
   -> 六边形网格命中测试
   -> 逻辑坐标 (q, r)
   -> 现有 Game action flow
```

命中测试必须满足：

1. 只有地图区域内部可命中。
2. 点中六边形边缘时命中结果稳定。
3. 选中白边框只绘制，不参与逻辑遮挡。
4. 细小缝隙区不应造成明显的误命中或漏命中。

### 3.5 数字正式路线

数字路线固定如下：

1. 小型数字和大型数字分别使用固定模板族。
2. 模板允许后续微调弧度，但不允许运行时随布局自由拉伸断裂。
3. 阴影方向固定为向右。
4. 阴影必须贴着轮廓走。
5. 中空字形内轮廓也要遵守相同阴影规则。

## 4. 页面与路由冻结

页面状态机固定为：

```text
+------------------+
|   Initial Menu   |
+--------+---------+
         |
         +--> Play ------> Map Select (Play) ------> Game (Manual)
         |
         +--> Autoplay --> Map Select (Autoplay) --> Game (Auto)
         |
         +--> Records ---> Record List ---> Record Detail
         |
         +--> Exit

Game (Manual / Auto)
   --m--> In-game Menu
   --final turn--> Final

In-game Menu
   --Continue / m--> back to Game
   --Menu----------> Initial Menu
   --Exit----------> quit

Final
   --Restart-------> Map Select (same mode + same config family)
   --Menu----------> Initial Menu
   --Exit----------> quit
```

实现上必须满足：

1. `Play` 和 `Autoplay` 只共用一套页面骨架，不复制两套页面。
2. `Map Select (Play)` 与 `Map Select (Autoplay)` 是同一类 screen，不同参数。
3. `Game (Manual)` 与 `Game (Auto)` 是同一类 screen，不同权限和不同右侧内容。
4. `Restart` 不复用未清理完成的旧 screen 实例。

## 5. 各页面操作流程冻结

本节是正式重构时必须逐项实现的动作清单。

### 5.1 初始菜单

页面上只允许出现：

1. `Play`
2. `Autoplay`
3. `Records`
4. `Exit`

不允许出现：

1. `Baseline`
2. `Normal`
3. `Speed`
4. 地图参数说明
5. AI 类型说明

动作与结果固定如下：

| 动作 | 结果 |
| --- | --- |
| 点击 `Play` | 进入 `Map Select (Play)` |
| 点击 `Autoplay` | 进入 `Map Select (Autoplay)` |
| 点击 `Records` | 进入 `Record List` |
| 点击 `Exit` | 退出程序 |
| 按 `q` | 退出程序 |

### 5.2 地图选择页

公共控件固定为：

1. `Map Difficulty`
2. `Map Size`
3. `Turn Limit`
4. `Start`
5. `Recreate`
6. `Menu`

Autoplay 版额外控件固定为：

1. `AI Type`
2. `Custom Input` 仅在 `AI Type = Custom` 时显示
3. `Playback`

动作与结果固定如下：

| 动作 | 结果 |
| --- | --- |
| 点击 `Map Difficulty` | 在 `Normal / Hard` 间切换 |
| 点击 `Map Size` | 在阶段一允许范围内循环 |
| 点击 `Turn Limit` | 在阶段一允许范围内循环 |
| 点击 `AI Type` | 在 `Baseline / Expert / Custom` 间切换 |
| `AI Type = Custom` | 显示 `Custom Input` |
| 点击 `Playback` | 在 `Normal / Speed` 间切换 |
| 点击 `Recreate` | 仅重生成地图，保留当前配置 |
| 点击 `Start` | 若当前配置允许，进入对应 `Game` |
| 点击 `Menu` | 返回 `Initial Menu` |
| 按 `q` | 退出程序 |

阶段一的额外限制固定为：

1. `Expert` 与 `Custom` 不可启动真实对局。
2. 当 `AI Type` 不是 `Baseline` 时，`Start` 不应进入可运行对局。

### 5.3 游戏主界面：手动模式

手动模式必须覆盖以下 UI 状态：

1. `idle`
2. `terrain_selected_buildable`
3. `terrain_selected_unbuildable`
4. `road_selected`
5. `city_selected`
6. `build_confirm`
7. `research_confirm`
8. `in_game_menu`

#### 5.3.1 `idle`

右侧只显示：

1. `SCORE`
2. 当前分数数字
3. `STEP`
4. 当前回合数字
5. `Skip`
6. 右下小字信息区

动作与结果：

| 动作 | 结果 |
| --- | --- |
| 点击不可建城也不可修路的普通格 | 进入 `terrain_selected_unbuildable` |
| 点击可建造普通格 | 进入 `terrain_selected_buildable` |
| 点击道路格 | 进入 `road_selected` |
| 点击城市格 | 进入 `city_selected` |
| 点击 `Skip` | 立即结算回合，留在 `idle` 或进入 `Final` |
| 按 `m` | 进入 `In-game Menu` |
| 按 `q` | 退出程序 |

#### 5.3.2 `terrain_selected_unbuildable`

规则固定为：

1. 地图只高亮当前格。
2. 右侧仍保持默认面板。
3. 不额外出现 `Build / Cancel`。

动作与结果：

| 动作 | 结果 |
| --- | --- |
| 再点同一格 | 回到 `idle` |
| 点其他格 | 按新格类型切换状态 |
| 点击 `Skip` | 结算回合 |
| 按 `m` | 进入 `In-game Menu` |

#### 5.3.3 `terrain_selected_buildable`

可见内容固定为：

1. 若既可建城又可修路，则横向显示 `City / Road` 两个切换项。
2. 若只允许一种，则只显示一种。
3. 下方固定显示 `Build / Cancel`。
4. 提示显示在右下小字区。

动作与结果：

| 动作 | 结果 |
| --- | --- |
| 点击 `City` 或 `Road` | 仅切换当前建造目标，不结算 |
| 点击 `Build` 成功 | 执行动作，结算，回到 `idle` 或进入 `Final` |
| 点击 `Build` 失败 | 保持当前状态，右下显示错误 |
| 点击 `Cancel` | 清除选中，回到 `idle` |
| 再点同一格 | 清除选中，回到 `idle` |
| 点其他格 | 按新格类型切换状态 |

#### 5.3.4 `road_selected`

规则固定为：

1. 道路格只高亮，不出现额外操作面板。
2. 右侧保持默认面板。

动作与结果：

| 动作 | 结果 |
| --- | --- |
| 再点同一格 | 回到 `idle` |
| 点其他格 | 按新格类型切换状态 |
| 点击 `Skip` | 结算回合 |

#### 5.3.5 `city_selected`

可见内容固定为：

1. 四项资源，按 `2 x 2` 排列。
2. 资源图标内部只有颜色，无文字。
3. 图标右侧显示该网络资源数值。
4. 科技区显示 `Agriculture / Logging / Mining / Education`。
5. 已研究科技加粗，但点击无响应。
6. 未研究科技点击进入 `research_confirm`。
7. 右下保留提示小字区。

动作与结果：

| 动作 | 结果 |
| --- | --- |
| 点击某资源图标 | 进入 `build_confirm` |
| 点击某未研究科技 | 进入 `research_confirm` |
| 点击已研究科技 | 保持 `city_selected` |
| 再点同一城市 | 回到 `idle` |
| 点击其他格 | 按新格类型切换状态 |

#### 5.3.6 `build_confirm`

可见内容固定为：

1. 顶部仅显示所选资源六边形图标与当前建筑数量。
2. 文字使用 `count` 或纯数字，不使用 `current count`。
3. 下方固定显示 `Build / Cancel`。
4. 提示留在右下小字区。

动作与结果：

| 动作 | 结果 |
| --- | --- |
| 点击 `Build` 成功 | 扣资源，建造，结算，回到 `idle` 或进入 `Final` |
| 点击 `Build` 失败 | 停留在 `build_confirm`，显示错误 |
| 点击 `Cancel` | 返回 `city_selected`，保留当前选中城市 |

#### 5.3.7 `research_confirm`

可见内容固定为：

1. 隐藏资源信息区。
2. 仅显示 `Research / Cancel`。
3. 提示留在右下小字区。

动作与结果：

| 动作 | 结果 |
| --- | --- |
| 点击 `Research` 成功 | 扣科技点，解锁科技，结算，回到 `idle` 或进入 `Final` |
| 点击 `Research` 失败 | 停留在 `research_confirm`，显示错误 |
| 点击 `Cancel` | 返回 `city_selected`，保留当前选中城市 |

### 5.4 游戏内菜单

可见控件固定为：

1. `Continue`
2. `Menu`
3. `Exit`

动作与结果固定为：

| 动作 | 结果 |
| --- | --- |
| 点击 `Continue` | 返回游戏 |
| 点击 `Menu` | 返回 `Initial Menu`，不保留局内 UI 选中态 |
| 点击 `Exit` | 退出程序 |
| 按 `m` | 等同 `Continue` |
| 按 `q` | 退出程序 |

### 5.5 游戏主界面：Autoplay 模式

Autoplay 使用和手动模式同一页面骨架，但权限固定不同：

1. 不允许点击地图插入动作。
2. 不允许显示人工 `Build / Cancel / Research / City / Road`。
3. 保留 `m` 和 `q`。
4. 右下小字区第一行固定显示 `mode / ai`。
5. 若存在提示，则提示占第二行。
6. `SCORE / STEP` 的位置与风格必须与手动模式一致。

动作与结果固定为：

| 动作 | 结果 |
| --- | --- |
| `Normal` 模式自动推进 | 逐回合同步刷新 |
| `Speed` 模式自动推进 | 批量推进，低频刷新 |
| 按 `m` | 进入 `In-game Menu` |
| 按 `q` | 退出程序 |

### 5.6 终局页

可见控件固定为：

1. 左侧终局地图
2. `SCORE`
3. 最终分数数字
4. `Restart`
5. `Menu`
6. `Exit`

动作与结果固定为：

| 动作 | 结果 |
| --- | --- |
| 点击 `Restart` | 进入新的地图选择页，保留同模式配置家族，不崩溃 |
| 点击 `Menu` | 回到 `Initial Menu` |
| 点击 `Exit` | 退出程序 |
| 按 `q` | 退出程序 |

### 5.7 Records 列表

无记录时：

1. 只显示 `No Records`
2. 只显示居中的 `Back`
3. 不显示 `Export`

有记录时：

1. 使用左右双列卡片
2. 两列横向铺满宽度
3. 底部固定 `Export / Back`

动作与结果固定为：

| 动作 | 结果 |
| --- | --- |
| 点击记录卡 | 进入 `Record Detail` |
| 点击 `Export` | 导出 CSV |
| 点击 `Back` | 返回 `Initial Menu` |
| 按 `b` | 返回 `Initial Menu` |
| 按 `d` | 滚到底部 |
| 按 `t` | 滚到顶部 |
| 按 `q` | 退出程序 |

### 5.8 Records 详情

顶部固定结构：

1. 左地图
2. 右信息
3. `Back`

向下滚动后出现统计区。

动作与结果固定为：

| 动作 | 结果 |
| --- | --- |
| 点击 `Back` | 返回 `Record List` |
| 按 `b` | 返回 `Record List` |
| 按 `d` | 滚到底部 |
| 按 `t` | 滚到顶部 |
| 按 `q` | 退出程序 |

## 6. 布局与几何预算

为避免再次出现“看起来写了，实际上点不到”的情况，本轮验收视口固定两档：

1. `120 x 40`
2. `140 x 60`

这两档都必须满足以下条件：

1. 主菜单四个入口全部可见、可点。
2. 地图选择页全部配置按钮可见、可点。
3. 手动模式一整套 `城市 -> 建筑确认 -> 返回` 操作不出现 `OutOfBounds`。
4. 手动模式 `城市 -> 科研确认 -> 返回` 操作不出现 `OutOfBounds`。
5. Autoplay 到终局后 `Restart / Menu / Exit` 全部可见、可点。

布局预算固定为：

1. 页面外边距只允许小空隙，不允许大面积留白。
2. 左侧地图壳必须以“近满高正方形”为目标。
3. 右侧信息栏固定为窄栏。
4. 左侧地图底部不预留提示区。
5. 右侧底部固定保留小字信息区。
6. 手动模式下右侧所有核心操作必须完整落在可视区，无滚动。
7. 只有 Records 页面允许纵向滚动。

建议的实现预算：

1. `side_width = clamp(28, floor(viewport_width * 0.24), 36)`
2. `gap = 2`
3. `map_square_side = min(viewport_height - 2 * outer_padding, viewport_width - side_width - gap - 2 * outer_padding)`
4. 资源区固定为两行两列。
5. 科技区固定为四行。
6. 建造确认区和研究确认区固定为短面板，不允许把按钮挤到屏幕外。

## 7. 模块落点

建议按下面的模块边界执行，不再混合职责：

```text
src/microciv/tui/
├── app.py
├── presenters/
│   ├── game_session.py
│   ├── status.py
│   └── state_machine.py
├── renderers/
│   ├── assets.py
│   ├── digits.py
│   ├── logo.py
│   ├── map.py
│   └── hexes.py
├── screens/
│   ├── menu.py
│   ├── setup.py
│   ├── game.py
│   ├── game_menu.py
│   ├── final.py
│   └── records.py
└── widgets/
    ├── image_surface.py
    ├── logo.py
    ├── map_view.py
    ├── metric_panel.py
    ├── action_panel.py
    └── record_cards.py
```

模块职责固定如下：

1. `renderers/assets.py`
   - 图像缓存键
   - 公共颜色与尺寸常量
2. `renderers/hexes.py`
   - 六边形几何与资源/地形/选中边框绘制
3. `renderers/logo.py`
   - 按 `19.4 LOGO 规范` 输出 LOGO
4. `renderers/digits.py`
   - 小型/大型数字模板与标题字模板
5. `renderers/map.py`
   - 整张地图渲染与命中测试辅助
6. `widgets/image_surface.py`
   - 图像显示后端的统一包装
7. `widgets/map_view.py`
   - 地图图像挂载、缩放、点击坐标转换
8. `widgets/action_panel.py`
   - 手动模式右侧上下文区域
9. `widgets/metric_panel.py`
   - `SCORE / STEP / info` 固定框架

## 8. 实施顺序

实施顺序固定如下，不允许跳步：

### Phase 0：收口生命周期与路由

目标：

1. 先解决 `Restart` 崩溃风险。
2. 先把 screen 栈和 route 入口收成单一真源。

必须完成：

1. 明确 route 名称与 screen 创建入口。
2. 去掉会重复冲突的 transient fixed id。
3. 把 `Restart` 改成“清理旧 screen -> 新建 setup screen”的安全路径。

通过标准：

1. `Restart` 多次循环不崩溃。
2. `Menu -> Play/Autoplay -> Final -> Restart` 不出现 `DuplicateIds`。

### Phase 1：建立正式渲染基础设施

目标：

1. 把六边形、数字、LOGO 从字符路线切走。
2. 建好离屏渲染与图像显示最小闭环。

必须完成：

1. 图像显示 widget
2. LOGO 渲染器
3. 小型数字渲染器
4. 大型数字渲染器
5. 六边形图元渲染器

通过标准：

1. 单独测试页可以稳定显示 LOGO、资源六边形、小型数字、大型数字。
2. 不再依赖字符画作为正式实现。
3. LOGO 与地图六边形默认都只有细小缝隙，不出现大面积空洞。

### Phase 2：重做菜单与地图选择

目标：

1. 先把用户进入游戏前的两层页面做正确。

必须完成：

1. 初始菜单只保留四入口
2. 地图选择正确分离 `Play` 与 `Autoplay`
3. 左侧地图预览改为正式图像路线
4. `Recreate` 保留配置

通过标准：

1. 不再提前出现 `Baseline / Normal / Speed`
2. 菜单与地图选择在两档验收视口都无溢出

### Phase 3：重做游戏主界面骨架与地图视图

目标：

1. 把地图重新做成页面主角。
2. 左侧地图切到整图渲染 + 命中测试。

必须完成：

1. 左侧近满高正方形地图壳
2. 右侧窄栏
3. 默认 `SCORE / STEP / Skip / info`
4. 地图点击命中测试

通过标准：

1. 点击地图可稳定得到逻辑坐标
2. 地图、LOGO、资源图标六边形语言统一
3. 地图六边形之间只保留细小缝隙，选中时白边框能够清晰落位

### Phase 4：重做手动模式上下文面板

目标：

1. 把 `idle / terrain / city / confirm` 做成明确状态机。

必须完成：

1. 普通格建造面板
2. 道路格只高亮
3. 城市资源区
4. 科技区
5. 建造确认页
6. 研究确认页
7. 提示生命周期

通过标准：

1. `城市 -> 建造确认 -> Cancel -> 城市`
2. `城市 -> 研究确认 -> Cancel -> 城市`
3. `普通格 -> Build 成功 / 失败`
4. 以上流程都不出现 `OutOfBounds`

### Phase 5：重做 Autoplay 表现

目标：

1. 自动模式看起来就是自动模式。

必须完成：

1. 隐藏人工操作
2. 保留 `m / q`
3. `mode / ai / tip` 放入右下小字区
4. `Normal / Speed` 共用骨架

通过标准：

1. 自动模式中无法误触人工动作
2. `SCORE / STEP` 与手动模式一致

### Phase 6：重做终局与 Records

目标：

1. 把后半段页面全部切到统一视觉体系。

必须完成：

1. 终局地图改为正式图像路线
2. `Restart / Menu / Exit` 稳定可用
3. Records 双列卡片铺满
4. 无记录时隐藏 `Export`
5. 详情页顶部左地图右信息

通过标准：

1. `Autoplay -> Final -> Restart`
2. `Records -> Detail -> Back`
3. `Records -> Export`
4. 全部路径稳定

### Phase 7：最终对齐与回归

目标：

1. 解决最后的对齐、间距和细节问题。

必须完成：

1. LOGO 组合与 [tui.md](/home/zolive/microciv/docs/tui.md) `19.4` 当前示意一致
2. 大小数字阴影方向与轮廓一致
3. 地图和资源图标默认无边框
4. 只有选中格出现白边框
5. 文档示意误差不带入程序
6. LOGO 与地图的缝隙控制接近 [logo.jpg](/home/zolive/microciv/docs/logo.jpg)，只有细小缝隙

通过标准：

1. 两档验收视口全部通过
2. 人工完整手测一局不被界面阻塞

## 9. 回归检查单

每次提交后至少回归以下动作：

1. 初始菜单四入口
2. 地图选择 `Start / Recreate / Menu`
3. 手动模式：
   - 普通格选中 / 取消
   - 建城
   - 修路
   - 点击道路格
   - 点击城市
   - 资源 -> 建造确认 -> Build / Cancel
   - 科技 -> 研究确认 -> Research / Cancel
   - `Skip`
4. `m` 打开游戏内菜单
5. 游戏内菜单 `Continue / Menu / Exit`
6. Autoplay `Normal`
7. Autoplay `Speed`
8. 终局 `Restart / Menu / Exit`
9. Records：
   - 空列表
   - 有记录列表
   - 导出
   - 详情
   - `b / d / t / q`

## 10. 本轮不做的事

以下内容不在本轮重构目标内：

1. `Baseline` 策略增强
2. `Expert / Custom` 真实对局能力
3. 游戏规则改版
4. Records 数据模型改版
5. 额外动画特效优先级提升到高于可用性

结论很简单：

1. 先修 screen 生命周期。
2. 再切正式渲染路线。
3. 再重做页面骨架与操作面板。
4. 直到“所有动作可达、所有页面稳定、所有六边形和数字不再靠字符硬拼”为止。
