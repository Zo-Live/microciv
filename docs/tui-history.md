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
