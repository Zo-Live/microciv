# MicroCiv Instruction

本文档说明当前版本的启动方式，以及 Play / Autoplay / Records 的实际操作方法。

## 1. 启动

推荐直接使用项目虚拟环境启动：

```bash
cd /home/zolive/microciv
./.venv/bin/python main.py
```

如果你更习惯模块入口，也可以使用：

```bash
cd /home/zolive/microciv
PYTHONPATH=src ./.venv/bin/python -m microciv.app
```

进入程序后会看到主菜单。

## 2. 主菜单

主菜单有 5 个入口：

1. `Play`
   手动游玩
2. `Records`
   查看本地已保存对局，并导出 CSV
3. `Autoplay Baseline Normal`
   用阶段一 `Baseline` AI 正常速度自动游玩
4. `Autoplay Baseline Speed`
   用阶段一 `Baseline` AI 加速自动游玩
5. `Quit`
   退出程序

## 3. 设置页

无论是 `Play` 还是 `Autoplay`，都会先进入设置页。

当前可调项如下：

1. `Map Size - / Map Size +`
   调整地图大小
2. `Turn Limit`
   在固定候选值之间循环切换：
   `30 / 50 / 80 / 100 / 150`
3. `Difficulty`
   在 `normal` 和 `hard` 之间切换
4. `Seed - / Seed +`
   调整地图随机种子
5. `Start`
   按当前配置开局
6. `Back`
   返回主菜单

注意：

1. 从设置页返回后，再次进入设置页不会保留之前的配置。
2. Play 模式不会保存中途退出的进度。
3. Records 只保存“自然打到终局”的完整对局。

## 4. 游戏界面

游戏界面分为两块：

1. 左侧 `HEX MAP`
   地图区域，可点击格子
2. 右侧 `STATUS`
   当前回合、分数、资源、选中格、选中城市和提示信息

地图字符说明：

1. `C`
   城市
2. `=`
   道路
3. `.`
   平原
4. `F`
   森林
5. `M`
   山地
6. `~`
   河流
7. `X`
   荒地

## 5. Play 模式操作

### 5.1 选中

先点击左侧地图上的一个格子。

点击后，右侧会显示：

1. 该格子的坐标
2. 地形
3. 当前占用物
4. 若该格是城市，还会显示该城市及其网络信息

### 5.2 地图动作

右侧 `MAP ACTIONS` 区有两个动作：

1. `Build City`
   在当前选中格上建城
2. `Build Road`
   在当前选中格上修路

要求：

1. 必须先选中格子
2. 不合法动作不会执行
3. 错误原因会显示在右侧 `Message`

### 5.3 建筑动作

右侧 `BUILDINGS` 区有 4 个动作：

1. `Farm`
2. `Lumber Mill`
3. `Mine`
4. `Library`

要求：

1. 必须先选中一个城市
2. 该城市所属网络必须满足科技前置
3. 网络资源必须足够

### 5.4 科研动作

右侧 `RESEARCH` 区有 4 个动作：

1. `Research Agriculture`
2. `Research Logging`
3. `Research Mining`
4. `Research Education`

要求：

1. 必须先选中一个城市
2. 该城市所属网络必须有足够 `science`
3. 已研究科技不能重复研究

### 5.5 回合动作

右侧 `TURN` 区有两个按钮：

1. `Skip`
   不建造，直接结算并进入下一回合
2. `Back To Menu`
   直接返回主菜单

注意：

1. `Back To Menu` 不会把当前未结束对局写入 Records。
2. 只有自然打到终局的完整对局才会保存。

## 6. Autoplay 模式

主菜单有两个 Autoplay 入口：

1. `Autoplay Baseline Normal`
2. `Autoplay Baseline Speed`

这两种模式都会使用阶段一 `Baseline` AI。

区别：

1. `Normal`
   正常速度逐步刷新
2. `Speed`
   加速刷新，会批量推进若干决策后再刷新界面

Autoplay 中：

1. 左侧地图和右侧状态仍然会更新
2. 手动动作按钮会被禁用
3. 你仍然可以点击地图查看格子和城市信息
4. 对局自然结束后会自动保存 Records

## 7. 终局页

到达最终回合后会进入终局页。

终局页会显示：

1. 最终分数
2. 回合数
3. 城市 / 道路 / 网络数量
4. 终局资源
5. 若已保存，会显示保存的 `Record` 编号

终局页按钮：

1. `Records`
   进入 Records 页面
2. `Main Menu`
   返回主菜单

终局页出现时，该对局已经自动写入本地 Records。

## 8. Records 页面

Records 页面用于查看已保存完整对局。

当前提供的操作：

1. `Previous`
   上一条记录
2. `Next`
   下一条记录
3. `Export CSV`
   导出当前所有记录到 `exports/`
4. `Back`
   返回上一页

页面内容：

1. 左侧是记录列表
2. 右侧是当前记录详情

导出后会在 `exports/` 下看到类似文件：

```text
exports/records-YYYYMMDD-HHMMSS.csv
```

## 9. 本地数据位置

当前版本运行时数据位置如下：

1. Records JSON：
   `data/records.json`
2. CSV 导出目录：
   `exports/`

## 10. 测试建议

如果你要手工验证阶段一主流程，建议按这个顺序：

1. 先用 `Play` 开一局，测试点击地图、建城、修路、建建筑、研究科技、`Skip`
2. 打到终局，确认自动进入终局页
3. 进入 `Records`，确认刚才的对局已经出现
4. 点击 `Export CSV`，确认 `exports/` 下出现导出文件
5. 再跑一次 `Autoplay Baseline Normal`
6. 再跑一次 `Autoplay Baseline Speed`

## 11. 当前限制

当前版本已经实现阶段一冻结范围，但仍有这些边界：

1. `Expert` 和 `Custom` AI 只是保留接口，不能运行
2. TUI 目前是“最小可用 + 视觉增强”版本，不是最终美术版
3. 只保存完整终局局面，不保存中途退出的对局
