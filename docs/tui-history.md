# TUI 重构历史

本文档记录本轮按 [tui-project.md](/home/zolive/microciv/docs/tui-project.md) 执行 TUI 重构时，每个阶段完成后的实际结果。

## 0. 启动基线

开始时间：`2026-04-09`

启动时确认到的问题：

1. 初始菜单提前暴露了 `Autoplay Baseline Normal / Speed`，不符合 [tui.md](/home/zolive/microciv/docs/tui.md)。
2. 地图选择界面仍是最小配置页，没有按 `Play / Autoplay` 区分配置层级。
3. 游戏主界面右侧长期常驻大状态栏和长按钮列表，严重挤压地图区。
4. 地图格仍使用带文字的按钮，不符合“格内仅颜色、默认无边框”的规范。
5. 终局页和 Records 页仍是最小摘要页，不符合正式布局。
6. 当前 TUI 测试只覆盖“能启动、能到终局、能导出”，不足以约束新规范。

本轮执行顺序固定为：

1. 视觉基础件
2. 页面状态机
3. 菜单与地图选择
4. 游戏主界面骨架
5. 上下文操作面板
6. Autoplay 专属表现
7. 终局与 Records
8. 测试与最终校对

## 1. 视觉基础件

完成内容：

1. 新增了 `src/microciv/tui/renderers/hexes.py`，统一六边形颜色、选中白边框和地图/资源/LOGO 共用色板。
2. 新增了 `src/microciv/tui/renderers/digits.py`，落了小型和大型数字的第一版块面实现。
3. 重写了 `src/microciv/tui/renderers/logo.py`，把 LOGO 变成 7 六边形布局，而不是旧 ASCII 标题字。
4. 新增了 `src/microciv/tui/widgets/hexes.py`，提供可点击六边形和资源显示件。
5. 重写了 `src/microciv/tui/widgets/logo.py`，正式用七个纯色六边形拼出 LOGO。
6. 重写了 `src/microciv/tui/widgets/map_grid.py`，地图格不再显示字母，而是纯色六边形。

实际结果：

1. 地图格、LOGO 六边形、资源图标默认都无边框。
2. 只有当前选中地图格会出现白边框。
3. 旧的地图文字按钮与旧 ASCII LOGO 已退出主路径。

## 2. 页面状态机

完成内容：

1. 新增了 `src/microciv/tui/presenters/state_machine.py`。
2. `main-menu-screen / setup-play-screen / setup-autoplay-screen / game-screen / game-menu-screen / final-screen / records-list-screen / record-detail-screen` 已固定。
3. `MicroCivApp` 的入口方法改成围绕这些 route 工作，不再混用旧 screen id。

实际结果：

1. `Play` 和 `Autoplay` 进入的是同一类地图选择页，只是配置项不同。
2. `Records` 现在是“列表页 -> 详情页”，不再把列表和详情硬拼在同一页。
3. `m / b / d / t / q` 的作用范围已回到对应页面。

## 3. 菜单与地图选择

完成内容：

1. 重写了 `src/microciv/tui/screens/menu.py`。
2. 初始菜单只保留 `Play / Autoplay / Records / Exit` 四项。
3. 重写了 `src/microciv/tui/screens/setup.py`。
4. 地图选择页改成左侧地图预览、右侧配置区。
5. `Autoplay` 配置项回收到地图选择页，包含 `AI Type / Playback / Custom Input`。
6. `Recreate` 现在会保留配置并重生地图，不再露出旧 seed 操作。

实际结果：

1. 初始菜单已不再提前出现 `Baseline / Normal / Speed`。
2. `Autoplay` 的 `Expert / Custom` 入口被保留在 UI 中，但 `Start` 仅对 `Baseline` 可用，符合阶段一冻结要求。
3. 地图预览已接上真实生成逻辑，而不是占位文本。

## 4. 游戏主界面骨架

完成内容：

1. 重写了 `src/microciv/tui/screens/game.py`。
2. 新增了 `src/microciv/tui/widgets/metric_panel.py`。
3. 主界面固定成“左侧地图主区域 + 右侧窄栏”的全屏布局。
4. 左侧地图不再放进滚动区域，右侧也不再是长滚动操作栏。
5. 右侧顶部改成 `SCORE / STEP` 与小字信息区。

实际结果：

1. 地图区域重新成为页面主角。
2. 左侧底部不再预留提示区。
3. 正常游戏流程已不再依赖滚轮。

## 5. 上下文操作面板

完成内容：

1. 新增了 `src/microciv/tui/widgets/action_panel.py`。
2. 普通格点击后会根据合法动作进入默认态或建造态。
3. 城市点击后会进入城市操作面板。
4. 建筑和科技改成确认界面，不再一次性把所有动作摊平。
5. 失败提示统一收回到右下小字区。
6. 新增了 `src/microciv/tui/screens/game_menu.py`，`m` 进入正式游戏内菜单。

实际结果：

1. 地图点击 -> 面板切换 -> Build/Research/Cancel 这条链已经接通。
2. 手动模式完整操作不需要滚动右侧列表。
3. 地图格里不再用字母表达状态。

## 6. Autoplay 专属表现

完成内容：

1. `GameScreen` 现在对手动和自动模式共用同一骨架。
2. Autoplay 下禁用了人工操作面板。
3. 右下小字区改成显示 `mode / ai / tip`。
4. `Normal / Speed` 仍由同一套定时逻辑驱动，只改变刷新节奏。

实际结果：

1. Autoplay 不再出现误导性的人工建造按钮。
2. `SCORE / STEP` 位置和手动模式保持一致。
3. Speed 自动对局仍可自然走到终局并写入 Records。

## 7. 终局与 Records

完成内容：

1. 重写了 `src/microciv/tui/screens/final.py`，恢复成左大地图、右分数与三个选项。
2. 重写了 `src/microciv/tui/screens/records.py`。
3. 新增了 `src/microciv/tui/widgets/record_cards.py`。
4. Records 列表恢复成左右双列卡片。
5. 无记录时隐藏 `Export`，只保留居中的 `Back`。
6. 新增了 Records 详情页，顶部左地图右信息，下方滚动统计。

实际结果：

1. 终局页已经回到正式布局，不再是摘要卡片。
2. Records 列表和详情页分离完成。
3. CSV 导出仍保持可用。

## 8. 测试与最终校对

完成内容：

1. 更新了 `tests/test_tui.py`，让测试路径对齐新菜单、新 setup、新 records 路由。
2. 补了“手动模式建城后点击城市进入城市面板”的交互测试。
3. 更新了 `tests/test_logo.py`，对齐新的 7 六边形 LOGO。
4. 修掉了六边形按钮在 Textual 下的渲染和点击稳定性问题。

验证结果：

1. `./.venv/bin/python -m pytest tests/test_tui.py tests/test_logo.py`
   - `5 passed`
2. `./.venv/bin/python -m pytest`
   - `48 passed in 14.04s`

收尾结论：

1. 本轮 TUI 重构已从入口、主界面、Autoplay、终局到 Records 全链落完。
2. 当前阶段的主要阻塞点已经不再是“界面难以操作”，后续可以回到更高层次的交互微调和 AI 策略打磨。

## 9. 实测后新增问题

在用户手动观察一局 `Autoplay` 后，新增确认了以下问题：

1. 主界面没有正确显示游戏名。
2. LOGO 与 [tui.md](/home/zolive/microciv/docs/tui.md) 的七六边形拼接示意不一致，当前六边形既不严丝合缝，也不够像六边形。
3. 地图选择界面与游戏界面的地图六边形之间间隔过大，导致地图整体无法完整、紧凑地显示。
4. 当前基于字符和 Rich 段落拼装的六边形渲染策略，精度不足，已经被证明无法满足目标视觉要求。
5. 数字渲染出现断裂；数字在不同尺寸下高度不稳定，大尺寸时尤其明显。
6. 当前数字渲染策略同样存在精度不足的问题，需要改成更高精度、受控的渲染方案。
7. `Autoplay` 对局结束后点击 `Restart` 会崩溃，报错为 `DuplicateIds`，说明当前屏幕切换和重启流程仍有状态管理问题。

这些问题说明：

1. 本轮 TUI 重构虽然把页面结构和交互层级拉回到了正确方向，但视觉基础件的技术路线仍然不够稳定。
2. 下一轮工作重点不应继续做零散微调，而应优先重构“六边形渲染策略、数字渲染策略、Screen 生命周期管理”这三个基础问题。

## 10. 动作级审计结果

在补写完新的渲染方案后，我又对当前程序里的显式动作做了一轮完整审计，重点检查：

1. 页面跳转是否正确。
2. 按钮是否可点击。
3. 快捷键是否触发到正确页面。
4. 页面切换后是否出现生命周期错误。
5. 手动模式下的实际操作是否仍会把控件挤出可视区。

### 10.1 已确认通过的动作

以下路径在当前版本中没有发现新的崩溃或明显状态错误：

1. 初始菜单：
   - `Play`
   - `Autoplay`
   - `Records`
2. 地图选择界面：
   - `Map Difficulty`
   - `Map Size`
   - `Turn Limit`
   - `AI Type`
   - `Playback`
   - `Recreate`
   - `Menu`
   - `Start`
3. Records：
   - 空记录列表打开
   - 空记录列表 `Back`
   - 有记录列表打开
   - `Export`
   - 点击记录进入详情
   - 详情页 `Back`
   - `b / d / t`
4. 游戏内菜单：
   - `Continue`
   - `Menu`
   - `Exit`
5. 终局页：
   - `Menu`
   - `Exit`
6. 退出路径：
   - 初始菜单 `Exit`
   - 地图选择界面 `q`
   - 游戏主界面 `q`
   - Records 界面 `q`
   - 游戏内菜单 `Exit`
7. 游戏主界面的基础地块交互：
   - 选中可建城普通格
   - 再次点击同一格取消选中
   - 建立第一座城市
   - 选择合法相邻道路格
   - 建立道路
   - 点击道路格不会错误打开城市操作面板

### 10.2 已确认存在的问题

#### 10.2.1 `Restart` 会崩溃

问题路径：

1. 进入 `Autoplay`
2. 跑到终局
3. 点击 `Restart`

确认结果：

1. 程序会抛出 `DuplicateIds`。
2. 报错内容指向重复插入 `SetupScreen(id='setup-autoplay-screen')`。
3. 这说明当前 `restart_from_session()` 的 screen 生命周期处理有问题：旧的 setup screen 还未完全离开节点树，就又 push 了一个相同 id 的 setup screen。

#### 10.2.2 游戏内城市操作面板仍然严重溢出

问题路径：

1. 进入手动 `Play`
2. 建一座城市
3. 点击该城市进入城市操作面板

确认结果：

1. 右侧资源与科技控件并没有被稳定限制在可视区内。
2. 在 `140 x 60` 的测试视口下，实际布局坐标已经明显越界：
   - `resource-food` 的 region 为 `x=106, y=21, width=32, height=40`
   - `resource-wood` 的 region 为 `x=141, y=21, width=32, height=40`
   - `resource-ore` 的 region 为 `x=106, y=61, width=32, height=40`
   - `action-cancel` 的 region 为 `x=106, y=119, width=32, height=3`
3. 这些坐标已经超出当前可视范围，说明城市操作面板虽然逻辑上存在，但实际并不真正可操作。

#### 10.2.3 城市操作面板中的部分动作因此不可达

在上述溢出条件下，进一步点击验证得到：

1. `resource-food` 本身还能勉强点到，但进入建造确认后：
   - `Build` 会报 `OutOfBounds`
   - `Cancel` 会报 `OutOfBounds`
2. `tech-agriculture` 点击同样会报 `OutOfBounds`，研究路径实际不可达。
3. 这意味着当前并不是“逻辑功能没写”，而是“控件已经被布局系统挤到屏幕外面”，所以用户会感知成“根本点不到”。

### 10.3 审计结论

当前动作层面真正需要优先修的，不是零散按钮逻辑，而是两类基础问题：

1. `Screen` 生命周期：
   先解决 `Restart -> DuplicateIds`，否则终局后的重开路径不可信。
2. 主界面布局与渲染：
   右侧操作面板和左侧地图都必须进入严格受控的高精度布局体系，否则即便逻辑动作都存在，用户也无法正常触达。

## 11. Phase 0：生命周期与路由收口

本阶段目标是先完成 [tui-project.md](/home/zolive/microciv/docs/tui-project.md) 中的 `Phase 0`：

1. 去掉 transient screen 的固定 `id` 依赖。
2. 把“当前页面身份”从 `Screen.id` 收回到统一 route。
3. 先修掉 `Restart` 的 `DuplicateIds` 崩溃。

完成内容：

1. 在 `src/microciv/tui/presenters/state_machine.py` 新增了 `route_for_screen(...)`，把 route 解析收成一个入口。
2. `src/microciv/tui/app.py` 新增 `current_route`，并让 `return_to_menu()` 改成基于 route 判断，而不是基于 screen id 字符串。
3. `MainMenu / Setup / Game / GameMenu / Final / RecordsList / RecordDetail` 全部改成 route 字段表达页面身份，不再把 `Screen.id` 当成页面身份的唯一来源。
4. `SetupScreen` 不再创建固定的 `setup-play-screen / setup-autoplay-screen` screen id，因此重开时不会再因为旧 setup screen 尚未完全离开节点树而触发重复 id。
5. `tests/test_tui.py` 改成基于 `app.current_route` 断言页面，并新增了 `Restart` 回归测试。

本阶段预期结果：

1. `Autoplay -> Final -> Restart` 可以安全回到新的地图选择页。
2. route 成为页面身份的单一真源。
3. 后续重做视觉和布局时，不再被旧的 screen id 生命周期问题拖住。

## 12. Phase 1：正式渲染基础设施

本阶段目标是完成 [tui-project.md](/home/zolive/microciv/docs/tui-project.md) 中的 `Phase 1`：

1. 把六边形、LOGO、数字从“字符拼图”主路径里切出去。
2. 建立离屏光栅渲染层。
3. 建立图像显示 widget。
4. 先让正式渲染链路本身成立，再在后续阶段接入各个 screen。

完成内容：

1. `pyproject.toml` 新增了运行时依赖：
   - `pillow`
   - `textual-image`
2. 新增了 `src/microciv/tui/renderers/assets.py`，集中定义：
   - app 背景色
   - 文本主色与阴影色
   - LOGO / 资源 / 地图六边形的 raster metrics
   - 小型/大型数字的 cell 尺寸
3. 重写了 `src/microciv/tui/renderers/hexes.py`：
   - 保留旧的 Rich fallback
   - 新增基于 `Pillow` 的 flat-top 六边形 raster 渲染
   - 新增 `RasterHexSpec`
   - 新增单 hex 与 hex cluster 的图像输出
4. 重写了 `src/microciv/tui/renderers/logo.py`：
   - 以“中心 + 六邻居”的七六边形 cluster 表达正式 LOGO
   - 新增 `render_logo_specs()`
   - 新增 `render_logo_image()`
   - 保留 `render_logo_text()` 仅作为文档近似示意
5. 重写了 `src/microciv/tui/renderers/digits.py`：
   - 保留旧的 Rich fallback
   - 新增 `render_small_number_image()`
   - 新增 `render_large_number_image()`
   - 新增基于模板光栅化的数字图像输出
6. 重写了 `src/microciv/tui/renderers/map.py`：
   - 保留旧的 `grouped_map_rows()` 供旧 widget 暂时使用
   - 新增 `render_map_image()`，把整张地图作为一张图输出
7. 新增了 `src/microciv/tui/widgets/image_surface.py`：
   - 用组合方式包装 `textual-image`
   - 提供稳定的 `set_image()` / `render_with()` 接口
8. `src/microciv/tui/widgets/logo.py` 已切到新图像链路，不再继续用小 hex button 拼 LOGO。

测试与验收：

1. 新增 `tests/test_raster_renderers.py`，覆盖：
   - 选中白边框 hex 图像
   - 小型/大型数字图像
   - LOGO 图像
   - 地图图像
   - `ImageSurface` 挂载
2. 更新 `tests/test_logo.py`，把旧的 4 行字符式行分组断言改成新的 5 层近似分组与图像输出断言。
3. 运行：
   - `./.venv/bin/python -m pytest tests/test_logo.py tests/test_raster_renderers.py`
   - `5 passed`
4. 运行：
   - `./.venv/bin/python -m pytest tests/test_tui.py`
   - `5 passed`
5. 运行：
   - `./.venv/bin/python -m pytest`
   - `53 passed in 17.66s`

本阶段结果：

1. 正式图像渲染链路已经成立。
2. LOGO 已经进入新链路。
3. 六边形、数字、地图都已经有可复用的 raster renderer。
4. 后续 `Phase 2` 与 `Phase 3` 可以直接基于这套基础设施，把菜单预览和主地图逐步切到正式图像路线。

## 13. Phase 2：菜单与地图选择

本阶段目标是完成 [tui-project.md](/home/zolive/microciv/docs/tui-project.md) 中的 `Phase 2`：

1. 把初始菜单收口为正式入口结构。
2. 把地图选择页左侧预览切到正式图像路线。
3. 保持 `Play / Autoplay` 的配置层级分离。
4. 让地图选择页的文案更克制，不再依赖大段解释文字。

完成内容：

1. 新增了 `src/microciv/tui/widgets/map_preview.py`：
   - 专门用于 setup 类页面的非交互地图预览
   - 内部直接使用 `render_map_image()` + `ImageSurface`
2. `src/microciv/tui/screens/setup.py` 已切换：
   - 左侧不再使用旧的 `MapGrid(compact=True)`
   - 改为正式图像预览 `MapPreview`
3. `SetupScreen._refresh_preview()` 已改成就地刷新预览图像，而不是依赖整页重组来更新旧字符地图。
4. `src/microciv/tui/screens/menu.py` 已收口为：
   - 左侧 `LogoWidget(show_title=True)`
   - 右侧 `Play / Autoplay / Records / Exit`
   - 不再额外拼一个独立的 `MicroCiv` 标题控件
5. `src/microciv/tui/screens/setup.py` 的右侧说明文字已收得更克制：
   - `Play` 模式不再显示解释性 note
   - `Autoplay + Baseline` 不再显示解释性 note
   - 只有 `Expert / Custom` 才显示阶段一不可执行的简短提示
6. `src/microciv/tui/widgets/__init__.py` 已导出 `MapPreview`。

测试与验收：

1. `tests/test_tui.py` 新增并更新了以下覆盖：
   - 菜单只保留顶层入口，不提前暴露 setup 控件
   - `Play` 进入的 setup 不显示 `AI Type`
   - `Autoplay` 进入的 setup 显示 `AI Type / Playback`
   - `setup-map-preview` 已经是图像预览 widget
   - `Recreate` 后预览图像对象发生更新，同时右侧控件保留
2. 运行：
   - `./.venv/bin/python -m pytest tests/test_tui.py`
   - `7 passed`
3. 运行：
   - `./.venv/bin/python -m pytest tests/test_logo.py tests/test_raster_renderers.py`
   - `5 passed`
4. 运行：
   - `./.venv/bin/python -m pytest`
   - `55 passed in 16.32s`

本阶段结果：

1. 初始菜单和地图选择的结构已进一步靠近文档冻结口径。
2. 地图选择页左侧预览已不再依赖旧字符六边形路线。
3. `Play` 与 `Autoplay` 的配置职责继续保持清晰分离。
4. 后续 `Phase 3` 可以直接把主游戏地图切到同一套正式图像/命中测试路线。

## 14. Phase 3：游戏主界面骨架与主地图视图

本阶段目标是完成 [tui-project.md](/home/zolive/microciv/docs/tui-project.md) 中的 `Phase 3`：

1. 把主游戏地图切到正式图像路线。
2. 让主地图不再依赖 `MapGrid` 的字符/按钮式格子。
3. 为后续手动模式上下文面板保留稳定的点击命中接口。
4. 先把主界面骨架中的“左地图 / 右窄栏”关系拉到新路线上。

完成内容：

1. `src/microciv/tui/renderers/assets.py`
   - 地图六边形 metrics 与预览六边形 metrics 分离
   - `MapPreview` 与主地图不再共用同一尺寸
2. `src/microciv/tui/renderers/map.py`
   - 新增 `MapRasterLayout`
   - 新增 `build_map_layout(...)`
   - 为整图渲染补上可复用的几何元数据
   - 新增像素命中到逻辑坐标的 `coord_at_pixel(...)`
3. `src/microciv/tui/widgets/image_surface.py`
   - 新增基于 `textual-image.get_cell_size()` 的显式 cell 尺寸映射
   - 解决了图像 widget 在 Textual 布局中 region 为 `0x0` 的问题
4. 新增 `src/microciv/tui/widgets/map_view.py`
   - 主游戏地图的新 widget
   - 内部使用整张地图图像
   - 支持点击命中测试
   - 提供 `local_offset_for_coord(...)` 供自动化测试稳定点击
5. `src/microciv/tui/screens/game.py`
   - 主地图已从 `MapGrid` 切到 `MapView`
   - `on_map_grid_tile_selected(...)` 改为 `on_map_view_tile_selected(...)`
   - 动作执行和 autoplay 推进后都会刷新 `MapView`
   - 主界面外边距和右栏宽度做了第一轮收口：
     - `#game-root` padding 从 `1 2` 收到 `1`
     - `#game-side-shell` 宽度从 `34` 收到 `30`
6. `src/microciv/tui/widgets/map_preview.py`
   - 改用较小的 preview metrics，避免 setup 预览和主游戏地图耦在一起

测试与验收：

1. `tests/test_tui.py` 已切换到新的地图点击方式：
   - 不再依赖 `#tile-q-r`
   - 改为通过 `MapView.local_offset_for_coord(...)` 在图像地图上点击
2. 新增并更新覆盖：
   - 游戏主界面使用的是 `MapView`
   - `MapView` 内部已经挂上 `ImageSurface`
   - 点击图像地图后，`selected_coord` 会正确切换
   - 通过图像地图完成建城后，再点城市可进入城市操作面板
3. 运行：
   - `./.venv/bin/python -m pytest tests/test_tui.py`
   - `8 passed`
4. 运行：
   - `./.venv/bin/python -m pytest`
   - `56 passed in 14.25s`

额外记录：

1. 在这一阶段中途确认过一个关键问题：
   - `MapView` 起初 region 为 `0x0`
   - 根因不是命中公式，而是 `textual-image` 包装层没有显式把图像像素尺寸映射成终端 cell 尺寸
2. 这个问题已经在 `ImageSurface` 层统一修掉，后续 `Final` 和 `Records Detail` 若切图像路线，也可以直接复用。
3. 当前全量测试会出现 `textual_image` 内部对 `Pillow.getdata()` 的弃用 warning；这来自第三方库，不影响当前功能正确性，但后续升级依赖时需要顺手关注。

本阶段结果：

1. 主游戏地图已经进入正式图像路线。
2. 主地图点击命中已经可用。
3. 主游戏界面后续不需要再依赖旧的 `#tile-*` 格子控件。
4. 后续 `Phase 4` 可以在这个新地图骨架上继续重做手动模式上下文面板和可达性问题。

## 15. Phase 4：手动模式上下文面板与可达性

本阶段目标是完成 [tui-project.md](/home/zolive/microciv/docs/tui-project.md) 中的 `Phase 4`：

1. 修掉右侧城市操作面板和确认面板的溢出问题。
2. 让 `资源 -> 建造确认 -> Cancel` 与 `科技 -> 研究确认 -> Cancel` 成为稳定可达路径。
3. 把资源图标从旧字符 hex button 切到正式图像 icon。
4. 把“按钮点不到”从布局层面真正解决掉。

完成内容：

1. 重写了 `src/microciv/tui/widgets/action_panel.py` 中的 `ResourceButton`：
   - 不再使用旧的 `HexButton` 字符六边形
   - 改为 `ImageSurface + 资源数值`
   - 图标直接走 `render_hex_image(..., metrics=RESOURCE_HEX_METRICS)`
   - 点击行为改由 `on_click` 触发 `Pressed` message
2. `src/microciv/tui/screens/game.py`
   - 城市资源区继续保持 `2 x 2` 排列
   - 建造确认界面的顶部资源图标改成非交互 `ResourceButton(..., interactive=False)`
   - 右侧面板在现有窄栏宽度下已能容纳：
     - 资源区
     - 科技区
     - 建造确认
     - 研究确认
3. 这一阶段没有重新拆面板结构成独立 widget 树，而是先把最直接导致溢出的资源控件改小并接到正式图像路线，确保当前阶段先恢复可达性。

关键修复结果：

1. 右侧资源控件不再有 `40` 行高度的异常 region。
2. 在 `140 x 60` 视口下，当前城市面板的关键控件都已经落在 `#game-side-shell` 内部：
   - 四个资源按钮
   - 四个科技按钮
   - `Cancel`
3. 建造确认界面中的：
   - 资源图标
   - `Build`
   - `Cancel`
   也都已落在右栏内部。
4. 研究确认界面中的：
   - `Research`
   - `Cancel`
   也都已落在右栏内部。

测试与验收：

1. `tests/test_tui.py` 新增了 `test_tui_city_context_and_confirm_panels_fit_inside_side_shell`
   - 先建第一座城市
   - 点击城市进入城市面板
   - 检查资源区、科技区和 `Cancel` 都落在当前 `#game-side-shell` 内
   - 点击资源图标进入建造确认
   - 检查建造确认控件都在右栏内
   - 点击 `Cancel` 返回城市面板
   - 点击科技进入研究确认
   - 检查研究确认控件都在右栏内
   - 再次 `Cancel` 返回城市面板
2. 运行：
   - `./.venv/bin/python -m pytest tests/test_tui.py`
   - `9 passed`
3. 运行：
   - `./.venv/bin/python -m pytest`
   - `57 passed in 16.08s`

额外记录：

1. 这一步里确认过，之前右栏溢出的直接根因不是科技按钮本身，而是旧 `ResourceButton -> HexButton` 路线产生了超大 region。
2. 现在资源图标已经进入图像链路，因此 Phase 5 不需要再为了右栏可达性回头返修这一部分。
3. 当前测试仍会收到 `textual-image` 来自第三方库的 `Pillow.getdata()` 弃用 warning；这不影响现阶段功能结论。

本阶段结果：

1. 右侧手动操作面板已经从“逻辑上存在、实际上点不到”变成“关键路径可稳定触达”。
2. `城市 -> 建造确认 -> Cancel` 与 `城市 -> 研究确认 -> Cancel` 已恢复为可操作路径。
3. 资源区已经切到正式图像 icon 路线。
4. 后续 `Phase 5` 可以专注处理 Autoplay 的专属表现，而不需要再被手动模式可达性阻塞。

## 16. Phase 5：Autoplay 专属表现

本阶段目标是完成 [tui-project.md](/home/zolive/microciv/docs/tui-project.md) 中的 `Phase 5`：

1. 让自动模式在视觉和交互上都明确表现为“自动模式”。
2. 移除自动模式下无意义的空上下文面板。
3. 把 `mode / ai / tip` 收到右侧底部小字区。
4. 明确禁止自动模式中通过地图点击插入人工动作。

完成内容：

1. 重写了 `src/microciv/tui/widgets/metric_panel.py`：
   - 从单个 `Static` 改成结构化 widget
   - 顶部固定显示 `SCORE / STEP`
   - 自动模式下加入 spacer，把小字信息压到右栏底部
2. `src/microciv/tui/screens/game.py`
   - `MetricPanel` 新增 `autoplay` 形态
   - 自动模式下不再渲染 `#game-context-shell`
   - 自动模式的 `info_lines` 改成：
     - 第一行：`mode + ai`
     - 第二行及以后：`tip`
3. 自动模式下当前界面按钮层面不再出现人工 `action-*` 控件。
4. 地图在自动模式下继续保持 `interactive=False`，但本阶段还补了显式测试来确认“点地图不会产生 selection”。

测试与验收：

1. `tests/test_tui.py` 新增了 `test_tui_autoplay_hides_manual_context_and_ignores_map_clicks`
   - 自动模式下不存在 `#game-context-shell`
   - 自动模式下不存在人工 `action-*` 按钮
   - `MetricPanel` 基本吃满右栏
   - 右下信息 widget 保持在右栏内部
   - 点击地图不会改变 `selected_coord`
2. 运行：
   - `./.venv/bin/python -m pytest tests/test_tui.py`
   - `10 passed`
3. 运行：
   - `./.venv/bin/python -m pytest`
   - `58 passed in 16.67s`

本阶段结果：

1. 自动模式已经不再像“手动界面去掉几个按钮”的残缺版本。
2. 自动模式的右栏结构已经回到“上分数 / 下小字信息”的专属布局。
3. 自动模式中不再暴露人工操作入口。
4. 后续 `Phase 6` 可以专注终局与 Records 的统一视觉和路由，而不需要再回头修自动模式表现。

## 17. Phase 6：终局与 Records

本阶段目标是完成 [tui-project.md](/home/zolive/microciv/docs/tui-project.md) 中的 `Phase 6`：

1. 把终局页切到正式图像地图路线。
2. 把 Records 列表和详情收回到冻结的正式布局。
3. 确认 `Restart / Export / Detail / Back` 这些后半段路径都稳定。

完成内容：

1. 重写了 `src/microciv/tui/screens/final.py`
   - 左侧终局地图改成 `MapPreview + FINAL_MAP_HEX_METRICS`
   - 右侧改成 `SCORE + 大数字 + Restart / Menu / Exit`
   - 终局分数字图做了受控缩放，避免大数字挤出窄栏
2. 更新了 `src/microciv/tui/renderers/assets.py`
   - 新增 `DETAIL_MAP_HEX_METRICS`
   - 新增 `FINAL_MAP_HEX_METRICS`
3. 扩展了 `src/microciv/tui/widgets/map_preview.py`
   - 非交互地图 widget 现在可以按页面传入不同的 raster metrics
4. 重写了 `src/microciv/tui/screens/records.py`
   - Records 列表继续保持双列卡片
   - 无记录时不显示 `Export`
   - 底部按钮区统一居中
   - 详情页顶部切成“左地图右信息”，下方变成两列统计区
5. 更新了 `src/microciv/tui/widgets/record_cards.py`
   - 记录编号统一成 `#0001` 这种格式
   - `mode / diff` 统一成 title case 显示

测试与验收：

1. `tests/test_tui.py` 新增了：
   - `test_tui_records_empty_state_hides_export_and_centers_back`
   - `test_tui_final_screen_uses_raster_map_and_controls_fit`
   - `test_tui_records_detail_uses_raster_map_and_back_returns_to_list`
2. 运行：
   - `./.venv/bin/python -m pytest tests/test_tui.py`
   - `13 passed`
3. 运行：
   - `./.venv/bin/python -m pytest`
   - `61 passed in 20.12s`

本阶段结果：

1. 终局页已经不再走旧 `MapGrid` 路线，而是切到了统一的图像地图链路。
2. `Autoplay -> Final -> Restart` 继续稳定，且终局页的三个按钮和分数控件都落在右栏内部。
3. Records 空状态已经符合文档：无 `Export`，只留居中的 `Back`。
4. Records 详情页的顶部结构已经回到“左地图右信息”，并能稳定返回列表。

## 18. Phase 7：最终对齐与回归

本阶段目标是完成 [tui-project.md](/home/zolive/microciv/docs/tui-project.md) 中的 `Phase 7`：

1. 收掉最后一轮缝隙、对齐和视觉路线遗留问题。
2. 把右侧分数/回合数字彻底切到正式图像路线。
3. 用测试把“默认无边框、仅选中白边框、两档视口通过”这些要求钉死。

完成内容：

1. 更新了 `src/microciv/tui/renderers/assets.py`
   - 收紧了 `LOGO / RESOURCE / PREVIEW_MAP / DETAIL_MAP / FINAL_MAP / MAP` 的 `fill_inset` 和 `margin`
   - 默认六边形缝隙和外圈留白都比上一版更小，更接近 `logo.jpg` 的观感
2. 扩展了 `src/microciv/tui/renderers/digits.py`
   - 新增 `scale_number_image(...)`
   - 数字缩放统一走最近邻，不再在各个 screen 里零散处理
3. 重写了 `src/microciv/tui/widgets/metric_panel.py`
   - `SCORE` 数字和 `STEP` 数字都正式切到 `ImageSurface + raster digit` 路线
   - 自动模式下底部小字区位置保持不变
4. 微调了 `src/microciv/tui/screens/final.py`
   - 终局分数缩放改为复用统一数字缩放 helper
5. 扩展了测试：
   - `tests/test_raster_renderers.py`
     - 新增“未选中 LOGO / 地图不出现白边框”
     - 保留“选中地图会出现白边框”
   - `tests/test_tui.py`
     - 显式检查主游戏右栏里的 score/step 已经是图像控件
     - 新增 `120 x 40` 小视口下的手动模式右栏可达性测试
     - 新增 `120 x 40` 小视口下的终局与 Records 布局测试

测试与验收：

1. 运行：
   - `./.venv/bin/python -m pytest tests/test_raster_renderers.py tests/test_logo.py tests/test_tui.py`
   - `21 passed`
2. 运行：
   - `./.venv/bin/python -m pytest`
   - `64 passed in 23.26s`

本阶段结果：

1. 右侧 `SCORE / STEP` 数字已经不再依赖文本 fallback，而是切到了正式图像渲染。
2. LOGO、地图和资源图标继续共用同一六边形语言，同时默认缝隙进一步收紧。
3. “默认无边框，只有选中格出现白边框”已经被渲染测试直接覆盖。
4. `140 x 60` 和 `120 x 40` 两档关键视口都补上了回归检查。
5. 按 [tui-project.md](/home/zolive/microciv/docs/tui-project.md) 的阶段划分，这一轮 TUI 重构已从 `Phase 0` 到 `Phase 7` 全部完成。

## 19. 审计后问题修复

在完成 `Phase 7` 后，又针对“进入程序后所有可执行动作”做了一轮动作级审计。该审计最初暴露出两项真实问题：

### 19.1 设置页按钮文字不刷新

问题表现：

1. 点击 `Map Difficulty` 后，左侧地图预览会变化，但按钮文字仍显示旧值。
2. 点击 `Map Size` 后，内部配置已经变化，但按钮文字仍停留在旧值。

根因：

1. `src/microciv/tui/screens/setup.py` 中 `Map Difficulty / Map Size` 走的是 `_refresh_preview(...)`。
2. 旧版 `_refresh_preview(...)` 只更新预览 widget，不重组整个设置页，因此按钮 label 不会同步刷新。

修复：

1. 将 `_refresh_preview(...)` 改成在更新 `_preview_state` 后执行 `refresh(layout=True, recompose=True)`。
2. 这样预览和按钮文本使用同一份最新状态重新渲染，不再出现“预览变了但文字没变”的错位。

### 19.2 `City / Road` 双选项里 `Road` 实际点不到

问题表现：

1. 在同一格同时允许建城和修路时，右侧会显示 `City / Road` 两个选项。
2. 但原先的 `Road` 按钮会溢出到右栏之外，用户实际上很难点中。
3. 结果就是看起来有 `Road` 选项，实际 `Build` 仍按默认 `City` 执行。

根因：

1. `src/microciv/tui/screens/game.py` 里这两个按钮原先放在普通 `Horizontal` 行里。
2. 两个按钮都继承了全宽按钮样式，导致在 30 列右栏中并排时发生横向溢出。
3. 动作审计中也确认过：`Road` 按钮 region 已经跑到右栏外，点击后 `_terrain_choice` 根本没有被切到 `build_road`。

修复：

1. 将 `City / Road` 双选项区域改成单独的 `Grid` 两列布局。
2. 为该行增加专门的 `.terrain-choice-row` CSS，固定 `grid-size / grid-columns / grid-gutter`，并限制按钮宽度。
3. 修复后，`Road` 按钮保持在右栏内部，点击后可正确切换建造目标，随后 `Build` 会实际修路而不是误建城。

### 19.3 补充测试与复核

新增/更新的验证：

1. `tests/test_tui.py`
   - 新增 `test_tui_setup_play_refreshes_labels_for_difficulty_and_map_size`
   - 新增 `test_tui_terrain_choice_row_fits_and_road_choice_builds_road`
   - 调整了 setup `Recreate` 测试，使其在页面重组后重新获取当前 `MapPreview`
2. 运行：
   - `./.venv/bin/python -m pytest tests/test_tui.py`
   - `17 passed`
3. 运行：
   - `./.venv/bin/python -m pytest`
   - `66 passed in 25.56s`
4. 重新执行动作级审计脚本后，以下动作组全部 `PASS`：
   - `main_menu_buttons`
   - `main_menu_exit_paths`
   - `setup_play_actions`
   - `setup_autoplay_actions`
   - `manual_game_actions`
   - `game_menu_and_quit_actions`
   - `autoplay_normal_and_speed_actions`
   - `final_actions`
   - `records_actions`

本轮结论：

1. 设置页的配置切换现在不会再出现“内部状态已变但按钮文字不变”。
2. 手动模式下 `City / Road` 双选项已经真正可点，`Road` 路径可稳定执行。
3. 这两项问题修复后，重新审计“进入程序后所有可执行动作”，未再发现同类阻塞问题。

## 20. `issues/` 用户问题逐条原因定位

本节对应 `issues/issues.txt` 中这一轮人工测试记录。这里先做“现象 -> 根因”定位，不在本节直接实施修复。

### 20.1 `341` 主页面右侧条状空缺

现象：

1. 刚进入主页面时，右侧会出现一条窄条状空缺。

根因定位：

1. `src/microciv/tui/screens/menu.py` 中 `#menu-right Button` 使用了 `margin: 1 0`，按钮之间会主动留出一整行空隙。
2. `src/microciv/tui/widgets/image_surface.py`、`src/microciv/tui/widgets/logo.py`、`src/microciv/tui/widgets/map_preview.py` 这一套图像 widget 默认都使用 `background: transparent`。
3. 当前主菜单布局依赖透明背景叠放，因此这些按钮间隙和右侧壳层未被重新填充的 cell 会直接暴露出来，看上去就像一条“空缺”。
4. 这个问题和后面的 `348 / 349 / 357` 本质上是同一类“透明区域没有被完整清底”的残影问题。

### 20.2 `342` `map size` 从 `10` 切回 `4` 后出现残留线

现象：

1. 在地图选择界面把 `map size` 从 `10` 切回 `4` 时，会稳定留下旧地图的一条残影。

根因定位：

1. `src/microciv/tui/widgets/map_preview.py` 中 `MapPreview` 和内部 `ImageSurface` 都是 `width: auto; height: auto; background: transparent;`。
2. `src/microciv/tui/widgets/image_surface.py` 的 `set_image(...)` 会更新图片尺寸和图片内容，但不会先把旧图像占用过、而新图像不再覆盖的区域显式清空。
3. 因为 `map size = 10` 生成的预览图比 `map size = 4` 更大，缩回小图时，旧大图边缘留下的终端 cell 就会形成细长残留线。

### 20.3 `Recreate` / 调高难度并增大地图时闪退

现象：

1. 在 `map size = 10, map difficulty = hard, turn limit = 150, playback = normal` 下，连续点击多次 `Recreate` 会闪退。
2. 另一个同类案例是先把难度切到 `hard`，再增大地图，也可能直接闪退。

根因定位：

1. `src/microciv/tui/screens/setup.py` 的 `_refresh_preview(...)` 在每次 `Recreate` 或切换部分配置后都会调用 `_build_preview_state()`。
2. `_build_preview_state()` 继续调用 `build_state_from_config(...)`，最终进入 `src/microciv/game/mapgen.py` 的 `MapGenerator.generate(...)`。
3. `src/microciv/game/mapgen.py` 的 `_generate_rivers(...)` 在大图 + `hard` 下要求生成两条河；如果 `_generate_single_river(...)` 多次尝试后仍找不到合法路径，就会在 `line 477` 直接 `raise RuntimeError("River generation failed.")`。
4. 这个异常当前没有在 setup 预览层被捕获，所以它会直接把整个 TUI 屏幕带崩，而不是退化成“提示本次重生成失败”。

### 20.4 `343` `map size = 10` 时游戏内地图底部显示不全

现象：

1. 进入正式游戏后，`map size = 10` 的地图底部被裁掉。

根因定位：

1. `src/microciv/tui/renderers/assets.py` 把主游戏地图固定成 `MAP_HEX_METRICS = HexRasterMetrics(cell_side=32, ...)`。
2. `src/microciv/tui/widgets/map_view.py` 和 `src/microciv/tui/renderers/map.py` 会按这组固定 metrics 整张生成地图图像，并直接交给 `ImageSurface` 显示。
3. 当前实现没有“根据左侧可用正方形区域自适应缩放地图”的逻辑，只有固定像素尺寸。
4. 因此当地图规模增大到 `10` 时，图像高度超过了左侧壳层的实际可视高度，底部就会被直接裁切。

### 20.5 `344 / 345` `Autoplay` 过程中按 `m` 后残留地图内容

现象：

1. `Autoplay` 过程中按 `m` 打开菜单，会在界面上留下与当前地图相关的一条残留内容。

根因定位：

1. `Autoplay` 主界面左侧仍然是 `MapView -> ImageSurface -> textual-image` 这条图像渲染链。
2. `src/microciv/tui/widgets/map_view.py`、`src/microciv/tui/widgets/image_surface.py` 默认都使用透明背景。
3. 从游戏界面切到覆盖式菜单时，旧地图图像退场后并没有把曾经占用过的透明区域彻底清底，所以打开菜单后会看到一条“跟着当前地图变化”的残留。
4. 这说明问题不在 Autoplay 状态机，而在当前图像控件的退场清理和非透明底面策略。

### 20.6 `346 / 347` 小型数字 `3` 和 `8` 辨识度低

现象：

1. 小型数字里 `3` 和 `8` 的可辨识度偏低。

根因定位：

1. `src/microciv/tui/renderers/digits.py` 的 `SMALL_PATTERNS` 仍然是手工字符模板。
2. 其中 `3` 使用：
   - `("███▒", "  ██▒", "  ██▒", "███▒")`
3. `8` 使用：
   - `(" ███▒", "█  █▒", "█  █▒", " ███▒")`
4. 这两者在缩小后都依赖很少的笔画差异，而 `src/microciv/tui/widgets/metric_panel.py` 里 `STEP` 数字还会再做一次 `0.9` 的缩放。
5. 结果就是本来就很紧的模板，在终端图像显示中进一步模糊，`3` 和 `8` 特别容易糊在一起。

### 20.7 `348 / 349` 主菜单 `Autoplay / Records` 之间有缝，返回后缝里残留旧内容

现象：

1. 初始主菜单里 `Autoplay` 和 `Records` 之间能看到一条缝。
2. 从设置页返回主菜单时，缝里会残留旧页面的 `map size` 等内容。
3. 从 Records 返回时，缝里会残留存档卡片背景色。

根因定位：

1. `src/microciv/tui/screens/menu.py` 的四个按钮之间本来就由 `margin: 1 0` 人为留出了空隙。
2. 这些空隙所在的父容器没有额外的实色衬底，而周围的图像类 widget 又广泛采用透明背景。
3. 因此当上一个 screen 退场时，没有被重新刷成纯背景色的那部分 cell 会直接从缝里透出来。
4. 这和 `341 / 342 / 344 / 345 / 352 / 357` 一样，属于统一的“透明区域 + 尺寸回退后未清底”问题族。

### 20.8 `350` 手动模式里 `City` 按钮语义不清，点击也像没反应

现象：

1. 点击一个可建城地块后，右侧出现 `City` 按钮。
2. 用户只记得按 `Build` 就能建城，不理解 `City` 的额外意义。
3. 当该格实际上只允许建城时，点击 `City` 也几乎看不出任何反馈。

根因定位：

1. `src/microciv/tui/screens/game.py` 的 `PANEL_TERRAIN` 模式下，哪怕只存在单一选项，也会额外渲染一个 `City` 或 `Road` 按钮。
2. 当只有建城这一种合法动作时，该按钮只是重复设置 `_terrain_choice = BUILD_CITY`，并不会带来任何可感知的状态变化。
3. 也就是说，这不是逻辑 bug，而是当前交互语义设计和 `tui.md` 目标不一致：文档希望这里更接近“图标选择 + 白边框”式明确选择，而不是额外摆一个几乎无效果的文本按钮。

### 20.9 `351` 提示文本没有固定在右下角

现象：

1. 手动模式下，提示文本紧挨在 `STEP` 下方，而不是像 Autoplay 那样压到右下角。

根因定位：

1. `src/microciv/tui/widgets/metric_panel.py` 只有在 `autoplay=True` 时才插入 `metric-spacer`。
2. 手动模式不会插入这个撑高元素，因此 `.metric-info` 会直接跟在 `STEP` 行后面。
3. 所以当前不是“偶发错位”，而是 `MetricPanel.compose()` 明确把手动模式信息区布局成了上方紧贴式。

### 20.10 `352` 城市面板点击六边形图标后右侧残留半个图标

现象：

1. 城市面板中点击任意资源六边形图标后，右边都会残留半个图标。

根因定位：

1. 资源按钮内部同样走 `ImageSurface` 图像链路。
2. 这些小图标在交互状态切换后会重新绘制，但 `src/microciv/tui/widgets/image_surface.py` 的 `set_image(...)` 仍然没有先清理旧区域。
3. 再叠加 `background: transparent`，就会让旧图标右缘的一部分像素残留在按钮外侧，形成“半个图标挂在旁边”的效果。

### 20.11 点击已研究科技没有响应

现象：

1. 城市面板里点击一个已经研究过的科技，没有任何提示。

根因定位：

1. `src/microciv/tui/screens/game.py` 在 `on_button_pressed(...)` 处理 `tech-*` 时，会先检查该科技是否已经在 `network.unlocked_techs` 中。
2. 如果已经研究过，就在 `line 246-247` 直接 `return`。
3. 当前没有同时写入 `state.message`、没有弹确认、也没有额外视觉反馈，因此从用户视角看就是“点了没反应”。
4. 这属于缺少反馈分支，而不是科技判定逻辑错误。

### 20.12 `353 / 354 / 355` 分数数字右侧出现奇怪阴影残留

现象：

1. 分数数字右侧会出现不规则的阴影残留。
2. 这个问题不止出现在单一截图，在多处数字显示中都能看到。

根因定位：

1. `src/microciv/tui/renderers/digits.py` 的大型数字本身带有右侧阴影模板。
2. `src/microciv/tui/widgets/metric_panel.py` 又会把这张大数字图进一步缩放到 `0.48`。
3. `src/microciv/tui/screens/final.py` 终局页分数也会做一次 `0.68` 缩放。
4. 这些缩放是对已经带阴影的光栅模板做二次像素缩放，容易把右侧阴影压成不规则锯齿。
5. 再加上 `ImageSurface` 的透明背景和旧区域未清理，视觉上就会被放大成“右边挂着奇怪阴影残留”。

### 20.13 `357` 从终局页回主页面后仍有残留条

现象：

1. 从终局页跳回主页面时，还会留下条状残影。

根因定位：

1. `src/microciv/tui/screens/final.py` 左侧终局地图同样使用 `MapPreview -> ImageSurface` 这条透明图像链。
2. 从终局页退回主菜单后，原先终局地图或分数图像覆盖过的区域并没有被完全清空。
3. 因此这个问题和 `341 / 342 / 344 / 345 / 348 / 349 / 352` 属于同一根因族，而不是终局页自己的独立 bug。

### 20.14 `356` 分数显示不了四位数，`900+` 看成了 `100`

现象：

1. 实际分数已经到九百多甚至四位数时，界面上显示成了更短的数值，看起来像“100”。

根因定位：

1. 当前分数计算逻辑本身没有做截断；`src/microciv/game/engine.py` 和 Records 持久化都直接保存完整整数。
2. 问题出在 TUI 显示层：`src/microciv/tui/widgets/metric_panel.py` 的分数图像是 `render_large_number_image(score)` 后再按 `0.48` 缩放，右侧栏本身宽度又很窄。
3. `src/microciv/tui/screens/final.py` 也同样把大分数图塞进固定宽度右栏。
4. 当分数位数增加到四位时，图像宽度超出右栏可用空间，当前实现没有自适应缩放到“恰好容纳全部位数”，所以高位会被直接裁掉，最终只剩后几位可见。

### 20.15 `358` Records 第三条记录占满整行，宽度和前两条不一致

现象：

1. Records 页在记录数为奇数时，最后一条记录会独占整行，从左到右铺满。
2. 这导致它的宽度明显大于前面的双列卡片。

根因定位：

1. `src/microciv/tui/screens/records.py` 通过 `_pairwise(...)` 把记录两两分组。
2. 当最后一行只有一条记录时，`compose()` 只渲染左卡片，不会补一个占位右卡片。
3. 同时 `.records-row RecordCardButton { width: 1fr; }`，于是这唯一一张卡片会把整行剩余宽度全部吃满。
4. 因此问题不在卡片组件本身，而在奇数行没有补齐第二列的占位结构。

### 20.16 本轮归因结论

这批问题主要收敛到四个根因族：

1. 图像类 widget 大量使用透明背景，且尺寸变小时没有显式清底，导致一整串残影类问题：`341 / 342 / 344 / 345 / 348 / 349 / 352 / 357`。
2. 地图与数字目前仍采用固定 raster 尺寸，没有根据容器实际尺寸做自适应缩放，导致 `343 / 356` 这类裁切问题。
3. 数字模板本身仍然比较脆弱，叠加二次缩放后放大了 `346 / 347 / 353 / 354 / 355` 的可读性问题。
4. 另外还有两类纯交互问题：
   - setup 预览层没有兜住地图生成失败异常，导致 `Recreate / hard 大图` 直接闪退。
   - 手动模式和 Records 里还有少量布局/反馈语义偏差，对应 `350 / 351 / 已研究科技无反馈 / 358`。
