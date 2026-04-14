# 当前仓库 Review 问题与修改计划

## 1. Review 基准

本次 review 以以下材料为依据，优先级从高到低如下：

1. `docs/阶段一项目规则与操作流程.md`
2. `docs/fix.txt`
3. `docs/数值设计.md`
4. `docs/MicroCiv流程/`
5. `README.md`
6. `src/` 与 `tests/` 当前实现

其中：

1. 阶段一正式规则、页面流程、Records 行为与界面约束，以 `docs/阶段一项目规则与操作流程.md` 为直接标准。
2. `docs/MicroCiv流程/` 用于核对页面结构、页面切换与控件位置。
3. `README.md` 与当前实现只用于判断“仓库现状”，不构成高于正式规则的依据。

## 2. 已明确的实施口径

以下问题已在前置讨论中确定，后续实现不再重新决策：

1. `Records` 中 `AI Type` 与 `Playback` 只在 `Autoplay` 详情页作为附加字段显示。
   手动局详情页不显示这两项。
2. 上述变更当前只作用于展示层。
   `RecordEntry` 存储结构暂不强制拆分或升级 schema。
3. `Records` 排序采用“读取时最近记录优先”。
   底层 `records.json` 仍保持追加写入顺序，不要求改成倒序存储。
4. 当前 CSV 导出不再视为正式方案。
   正式实现应改为导出到 `exports/records_export.json`，覆盖同名旧文件。
5. `Delete All`、详情页 `Delete`、空记录页都属于阶段一正式流程，不再视为可选能力。
6. `Autoplay` 需要独立的局内页面语义。
   `幻灯片9` 不是终局页，而是 AI 运行中的局内页。
7. 城市页正式流程为：
   - 城市主页显示四种资源与 `Buildings / Technologies`
   - 建筑页显示四个建筑候选项与 `Build / Cancel`
   - 科技页显示四个科技候选项与 `Research / Cancel`
8. 地图设置页的正式可选值为固定档位：
   - `Map Size = 12 / 16 / 20 / 24`
   - `Turn Limit = 30 / 50 / 80 / 100 / 150`

## 3. 当前实现概况

当前仓库已经具备以下基础能力：

1. 正方形地图生成
2. 资源、城市、道路、科技、建筑与评分逻辑
3. `Greedy` 与 `Random` 自动经营基础能力
4. 本地 Records 持久化
5. 基础 `curses` 页面和局部测试

当前实现同时保留了若干阶段一之外或已过期的内容：

1. `CUSTOM`、`EXPERT` 等未来 AI 能力仍在枚举和运行时路径中保留
2. Records 仍采用 CSV 导出
3. `README.md` 仍存在 `Baseline` 命名和旧快捷键说明

当前测试状态为：

1. `pytest` 通过
2. 现有测试主要证明“当前实现自洽”
3. 现有测试不能证明“当前实现符合正式规格”

## 4. 问题清单

### 4.1 阻塞级问题

1. 鼠标滚轮会导致程序崩溃。  
   `src/microciv/curses_app.py:680-685` 在滚轮事件中调用了不存在的 `self.controller._scroll(...)`。

2. 设置页存在死控件。  
   `src/microciv/curses_app.py:824-837` 渲染的是 `setup-map-size` 和 `setup-turn-limit`，但 `src/microciv/curses_app.py:318-325` 只处理 `setup-map-size-inc/dec` 与 `setup-turn-limit-inc/dec`。  
   结果是控件可见但不可用。

3. 阶段一 AI 范围未收口。  
   `src/microciv/curses_app.py:306-310`、`src/microciv/game/enums.py:42-49`、`src/microciv/session.py:45-49` 仍然保留并暴露 `CUSTOM`、`EXPERT` 或未来 AI 路径。  
   当前正式范围只允许 `Greedy / Random`。

### 4.2 规格不一致问题

4. 地图设置页的取值方式不符合正式规则。  
   `src/microciv/curses_app.py:312-317` 仍按连续增减处理 `map_size` 与 `turn_limit`。  
   正式规则要求离散固定档位，而不是 `+2` 或 `+10` 的连续步进。

5. 非城市格流程与正式流程不一致。  
   `src/microciv/curses_app.py:845-879` 只要选中非城市格，就直接渲染建造面板。  
   正式规则要求非法地块保持默认右侧面板，不显示无效建造面板。

6. `Autoplay` 缺少独立的局内页面语义。  
   当前 `Autoplay` 进行中仍使用 `ScreenRoute.GAME`，渲染逻辑与手动局共用 `src/microciv/curses_app.py:845-879`。  
   正式规则要求 `Autoplay` 局内页单独对应 `幻灯片9`：显示当前地图、分数、回合和 `AI Type / Playback` 提示区，不显示 `Skip`、建造面板或研究面板。

7. 城市流程只对齐了一部分，仍未完整符合正式流程。  
   当前实现已经有 `Buildings / Technologies` 两个入口，这一点与正式规则一致；但 `src/microciv/curses_app.py:881-991` 的布局、页面切换和状态展示仍是简化版，不满足正式流程图中的固定结构、绝对位置和提示区要求。

8. 页面布局不是按正式布局稿实现。  
   `src/microciv/curses_app.py:804-843`、`845-855`、`881-1123` 仍使用居中和自适应的简化布局，没有按 `docs/MicroCiv流程/` 中的黑框/红框和绝对位置实现。

9. 颜色与选中态不符合正式规范。  
   `src/microciv/curses_app.py:639-654` 中的颜色映射与正式颜色标准不一致，尤其道路颜色仍是 `MAGENTA`。  
   `src/microciv/curses_app.py:1149-1151` 仍用静态方框表示选中格，没有实现手动闪烁选中态。

10. 快捷键语义与正式标准不一致。  
    `src/microciv/curses_app.py:484-511` 当前只处理 `q`、`b`、`m` 和方向键。  
    现有实现中：
    - `q` 会直接退出，缺少场景约束
    - `b` 仍承担“执行建造/研究”的语义
    - 没有实现 `d / t`
    - 没有实现“菜单页按 `m` 等价于 `Resume`”

11. 回合显示语义尚未按正式标准固定。  
    当前 UI 使用 `turn/turn_limit` 的显示方式，记录字段与测试断言也尚未按“`turn` 表示当前将要执行的回合”统一核对，仍有 off-by-one 风险。

### 4.3 Records 问题

12. Records 默认浏览顺序不符合正式标准。  
    `src/microciv/records/store.py:53-62` 采用追加顺序保存；`src/microciv/curses_app.py:1048-1073` 也直接按原顺序显示前几条。  
    正式规则要求浏览时按“最近记录优先；若时间相同按 `record_id` 降序”排序。

13. Records 列表页只实现了静态 8 格展示，没有真正实现滚动和跳转。  
    `src/microciv/curses_app.py:95-98` 虽然有 `records_scroll/detail_scroll` 字段，但 `src/microciv/curses_app.py:1048-1073` 实际渲染时没有使用。  
    因此当前不存在稳定分页、滚轮滚动、`d` 跳底或 `t` 跳顶。

14. Records 流程不完整。  
    当前实现只有：
    - 列表页 `Export / Back`
    - 详情页 `Back / Menu`
    - 空记录页 `Back`
    
    但正式规则还要求：
    - 列表页 `Delete All`
    - 详情页 `Delete`
    - 删除后的返回路径
    - 空记录页与列表页、详情页之间的完整切换

15. Records 导出格式与正式规则不一致。  
    `src/microciv/records/export.py` 与 `src/microciv/curses_app.py:142-146` 仍实现的是时间戳 CSV 导出。  
    正式规则要求导出到 `exports/records_export.json`，覆盖同名旧文件。

16. Records 详情字段与正式规则不一致。  
    `src/microciv/curses_app.py:1099-1115` 当前详情页固定显示 `AI`、`Mode`、时间统计等一组混合字段。  
    现行正式规则要求：
    - 手动局详情页不显示 `AI Type / Playback`
    - `Autoplay` 详情页在基础字段之外附加显示 `AI Type / Playback`
    - `Autoplay` 详情页再附加显示回合总耗时与单步平均耗时
    - 详情字段需按正式文档固定排列

17. Records 展示层与存储层需要明确分离处理。  
    当前 `RecordEntry` 仍直接持有 `ai_type` 与 `playback_mode` 字段，这本身不是问题；真正的问题是当前 UI 直接照搬存储字段渲染，没有按照正式规则区分手动局与自动局展示口径。  
    本轮后续实现应先改展示层，不强制先改 schema。

### 4.4 文档与测试问题

18. `README.md` 与正式命名不一致。  
    `README.md:14` 仍使用 `Baseline`，与正式命名 `Greedy` 不一致。

19. `README.md` 中的交互说明与正式规则不一致。  
    `README.md:47-56` 仍描述旧快捷键：
    - `b` 触发 build
    - `t` 触发 research
    - `d` 显示 detail
    - `q` 负责 back / close
    
    这些都与正式规则冲突。

20. UI 相关测试覆盖不足。  
    `tests/test_curses_app.py` 当前只覆盖少量跳转和一次鼠标命中，没有覆盖：
    - 滚轮输入
    - Records 排序、分页、跳底、跳顶
    - 设置页死控件
    - 正式快捷键语义
    - `Autoplay` 局内页
    - `Delete All` / `Delete`
    - 正式流程图对应的页面切换

## 5. 修改计划

### 阶段 A：修复阻塞交互

目标：先让程序不崩，所有关键控件真实可用。

1. 为控制器补齐 Records 滚动接口或改成正确的滚动分发路径。
2. 修复滚轮事件分发，保证滚轮不会崩溃。
3. 修复设置页控件 ID 与点击逻辑不一致的问题。
4. 为这些问题补充最小回归测试。

### 阶段 B：收口阶段一能力范围

目标：让当前正式范围和界面一致。

1. 设置页只保留 `Greedy / Random`。
2. 默认 AI 固定为 `Greedy`。
3. `CUSTOM`、`EXPERT` 与其它未来 AI 不再出现在阶段一交互中。
4. `README.md`、Records 展示与 UI 命名统一使用 `Greedy`。

### 阶段 C：按正式流程重构页面状态

目标：让页面状态和流程切换与正式规则一致。

1. 为 `Autoplay` 增加独立的局内 route 与渲染逻辑。
2. 非法地块保持默认右侧面板。
3. 手动局主界面、城市主页、建筑页、科技页、游戏内菜单、终局页按正式流程拆分状态。
4. 各页面的按钮集合、返回路径与提示区按正式流程重做。

### 阶段 D：重构 Records

目标：让 Records 行为完全符合正式规格。

1. 读取 Records 时按正式标准排序；底层文件仍保持追加顺序。
2. 列表页实现真正的分页/滚动/跳底/跳顶。
3. 补齐 `Delete All`、详情页 `Delete` 与删除后的页面切换。
4. 导出改为 `exports/records_export.json`。
5. 详情页按正式字段重排。
6. `AI Type / Playback` 只在 `Autoplay` 详情页附加显示。
7. 先改展示层，不强制先改 `RecordEntry` schema。

### 阶段 E：统一快捷键、回合显示与视觉

目标：让基础交互标准稳定，视觉结果接近正式验收状态。

1. `b` 只负责返回上一层。
2. `m` 负责打开菜单，并在菜单页等价于 `Resume`。
3. `d / t` 实现 Records 跳底 / 跳顶。
4. `q` 只保留退出语义。
5. 所有页面与记录字段统一采用“当前将执行的回合”显示标准。
6. 颜色、闪烁选中态和互斥选项样式按正式规范修正。
7. 页面布局从简化布局过渡到正式绝对布局。

### 阶段 F：补齐测试与 README

目标：避免后续实现再次偏离正式规格。

1. 为快捷键语义补测试。
2. 为 Records 排序、滚动、跳转、删除、导出补测试。
3. 为设置页死控件补测试。
4. 为 `Autoplay` 局内页和关键流程页补测试。
5. 更新 `README.md` 的 AI 命名、导出说明和交互说明。

## 6. 验收标准

完成改造后，至少应满足以下结果：

1. 滚轮不会崩溃，Records 可稳定滚动。
2. 设置页、Records 页、菜单页、终局页不存在死控件。
3. 只暴露 `Greedy / Random` 两种 AI，默认 `Greedy`。
4. `Autoplay` 具有独立的局内页面语义。
5. 页面流程与 `docs/阶段一项目规则与操作流程.md` 及 `docs/MicroCiv流程/` 一致。
6. 快捷键完全符合正式标准。
7. 回合显示不出现 off-by-one 歧义。
8. Records 支持最多 `10000` 条，并在读取时默认最近记录优先。
9. Records 支持空状态页、列表页、详情页、删除与 JSON 导出。
10. Records 手动局与自动局详情页字段范围符合正式规则。
11. 界面颜色、选中态和互斥选项样式符合正式规范。
12. 自动化测试能够覆盖上述关键行为。
