# 敲敲项目协作规范

本文件适用于整个仓库。所有参与本项目的编码代理在分析、修改、验证和交付前都必须遵守。
当前任务的用户明确要求优先；子目录如有 `AGENTS.md`，同时遵守其更具体的约束。
本文记录项目约定，不代表其中列出的测试或实机验收已经执行。

## 1. 每次开始工作

1. 阅读本文件，并按任务查阅 `README.md` 的产品规则和 `DEVELOPMENT.md` 的实施记录。
2. 执行 `git status --short`，检查相关文件已有差异；保留用户的未提交修改，不覆盖、不回退无关改动。
3. 先定位实际入口、数据流和已有测试，再决定修改位置；不要仅根据文件名或历史说明推断实现。
4. 用户要求“先分析”“先给方案”“不改代码”时，只分析并给出方案；明确要求实现时再落地。
5. 默认做满足需求的最小改动，不顺带重构、不升级无关依赖、不修改版本号或正式使用入口。
6. 开始修改前简要说明范围；完成后说明改了什么、验证结果和未验证事项。

<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tools** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them. `codegraph_node` returns one symbol's source + callers, or reads a whole file with line numbers. If the tools are listed but deferred, load them by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` and `codegraph node <symbol-or-file>` print the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

没有 CodeGraph 索引时优先使用 `rg` / `rg --files`；不要自行创建索引或扫描虚拟环境、构建产物。

## 2. 产品定位与技术栈

敲敲是 Windows 本地物理按键次数统计工具，以键盘热度图、日期查询和后台托盘统计为核心。
保持轻量、离线、聚合统计的定位。未经任务明确要求，不添加联网服务、遥测、账号或开机自启动。

| 项目 | 当前约定 |
| --- | --- |
| 平台 | Windows x64，正常桌面会话 |
| 语言 | Python 3.15，64 位；当前开发环境记录为 3.15.2 |
| UI | PySide6 / Qt Widgets，`Fusion` 风格；运行依赖为 `PySide6-Essentials==6.12.0` |
| 原生采集 | Windows Raw Input，通过标准库 `ctypes` 接入 |
| 数据库 | 标准库 `sqlite3`，本地 SQLite，WAL 模式 |
| 偏好 | `QSettings`，当前数据目录中的 `preferences.ini` |
| 后台保存 | `ThreadPoolExecutor(max_workers=1)` 串行写入 |
| 测试 | 标准库 `unittest`、`unittest.mock`，UI 使用 Qt Test |
| 打包 | PyInstaller 文件夹模式，当前锁定 `6.22.3`，PowerShell 构建入口 |

- 依赖版本以 `requirements.txt`、`requirements-build.txt` 为准；变更依赖时同步文档并验证打包兼容性。
- 复用标准库和现有 Qt 能力，不为简单功能引入另一套 UI、ORM、状态管理或测试框架。
- 开发使用 `.venv`，构建使用 `.venv-build`；不要向全局 Python 或其他项目环境安装依赖。
- 本项目没有 Web 前后端、Node.js 工程或独立服务端，不套用 npm、Vite、React 等工程流程。

## 3. 项目结构与职责

| 路径 | 职责与修改边界 |
| --- | --- |
| `run.py` | 启动入口，调用 `qiaoqiao.app.main`，保持轻量 |
| `start.cmd` | 开发版双击启动入口 |
| `qiaoqiao/__init__.py` | 应用版本号的唯一来源 `__version__` |
| `qiaoqiao/runtime.py` | 参数解析、开发/正式模式、数据路径和版本标题 |
| `qiaoqiao/keys.py` | 扫描码归一化、物理键标识、标准 104 键基础数据 |
| `qiaoqiao/layouts.py` | 显示布局预设及几何位置，复用已有物理键标识 |
| `qiaoqiao/core.py` | 纯计数、长按去重、设备按住状态、日期聚合 |
| `qiaoqiao/storage.py` | 数据库结构、事务、批量保存和失败恢复 |
| `qiaoqiao/raw_input.py` | Windows 原生消息、输入解析、设备和会话事件 |
| `qiaoqiao/ui.py` | Qt 控件、主题样式、键盘绘制、日期和布局交互 |
| `qiaoqiao/app.py` | 组装模型/监听/UI/存储，托盘、单实例和退出生命周期 |
| `assets/` | 像素图原稿及应用 ICO |
| `tests/` | 对应模块的自动化测试 |
| `tools/` | 打包、图标导出、开发和发布快捷方式脚本 |
| `qiaoqiao.spec` | PyInstaller 收集及 EXE 配置 |
| `README.md` / `DEVELOPMENT.md` | 使用与开发说明 / 实施进度和验证记录 |
| `work/` / `releases/` | 临时验收及构建工作区 / 发布产物，不作为业务源码 |

### 共享能力与依赖方向

当前只有一个应用包 `qiaoqiao`，没有独立共享包或 monorepo。
共享逻辑通过现有模块复用，不为了形式新增 `packages/`、通用框架或杂项 `utils.py`。

- 物理事件和键名复用 `PhysicalEvent`、`normalize()`、`key_name()`；不要在 UI 或存储层再造键位映射。
- 布局复用 `Key`、`KeyboardLayout`、`LAYOUTS`、`LAYOUT_BY_ID`、`DEFAULT_LAYOUT`。
- 计数和日期规则复用 `CounterModel`、`date_range()`、`move_date()`。
- 数据写入统一经过 `Database` / `Persistence`；路径选择统一经过 `Runtime` / `parse_runtime()`。
- 应用图标复用 `application_icon()` 和 `assets/qiaoqiao.ico`。
- `core.py`、`keys.py`、`layouts.py` 保持不依赖 Qt、原生监听或应用控制器。
- `app.py` 负责协调；UI 不直接写数据库，存储层不反向依赖 UI。
- 只有出现实际复用需求才提取新模块，并同步本文件中的目录职责。

## 4. 不得意外改变的业务规则

### 物理键与日期

- 按物理扫描码统计，不按输入字符、键帽文案或当前显示布局统计。
- 一次按下到松开只计一次；忽略长按重复。保留 Pause 等特殊键的独立归一化规则。
- 多设备合并总数，但按住状态以 `(device, key_id)` 区分；拔出设备只清理对应状态。
- 左右修饰键、主键区与数字小键盘分别统计；Num Lock 不改变小键盘物理键标识。
- 按事件发生时的电脑本地日期计数；查询历史、切换时段或布局不得改变采集日期。
- 周为周一至周日，月为自然月；跨午夜的持续按住不得重复计数。
- 锁屏、休眠及恢复时按现有流程重置按住状态，避免恢复后出现卡住的按键。

### 布局与展示

- 目前支持 104、87、75%、65%、60% 和通用笔记本六种布局。
- 切换布局只改变展示，不改写历史、不合并物理键、不筛掉采集事件。
- 总敲击和已使用按键数包括所有记录；有次数但不在当前布局内的键列入“布局外按键”。
- 热度按当前时段、当前布局内的最大次数归一化，保留现有对数映射。
- 无真实扫描码的 Fn 使用 `key_id=None`，只作灰色占位，不虚构次数或绑定其他物理键。
- 布局 ID 同时用于偏好持久化，不能随意重命名；无效偏好回退到默认 104 键。

### 生命周期

- 关闭或最小化主窗口进入托盘，继续采集和保存；用户正常退出通过托盘“退出程序”完成。
- 普通退出必须先保存；失败时保留模型和未保存数据，恢复运行并提示重试。
- 系统关闭使用现有专门分支，不承诺系统强制结束时仍能阻止退出或保证落盘。
- 单实例以解析后的数据目录为边界；相同目录重复启动唤醒已有窗口，不同目录可独立运行。
- UI 当前每约 250 ms 刷新，保存每约 1 s 尝试一批；不要改成逐键刷盘或无节制重绘。

## 5. 数据、隐私与线程

| 运行方式 | 数据目录 |
| --- | --- |
| 源码运行，或带 `--dev` 的发布包 | `%LOCALAPPDATA%\Qiaoqiao-dev` |
| 默认发布包 | `%LOCALAPPDATA%\Qiaoqiao` |
| 开发模式加 `--data-dir` | 指定的独立测试目录 |

- 源码默认开发模式；开发模式不能指向正式目录。不要绕过 `parse_runtime()` 的校验。
- 测试使用临时目录或 `work/` 下的独立目录，不读取、复制或修改用户正式统计来生成测试数据。
- 不硬编码本机用户名、个人安装目录或 `D:\qiaoqiao`；路径从项目位置或运行配置解析。
- 数据库仅保存 `daily_counts(day, key_id, count)` 聚合值，当前 `PRAGMA user_version=1`。
- 不记录输入文字、按键顺序、逐次按键时间或应用名称；设备句柄和按住状态只保留在内存。
- 日志仅用于错误诊断，不能输出逐键事件或原始输入包。
- 保存使用绝对累计值的事务 UPSERT，不改成可能重复累加的增量重试。
- 保存失败重新标记待保存项，重试读取最新累计值，不能用旧快照覆盖新计数。
- SQLite 写入继续在单工作线程执行，每次操作自行管理连接；不跨线程共享连接或操作 Qt 控件。
- 原生输入回调和绘制过程保持轻量，不加入阻塞 I/O；原生回调异常必须转为可见错误，保留 Windows 默认消息处理。
- 修改数据库结构或键标识时提供版本兼容和迁移方案，不静默清空历史、不降低未知数据库版本。
- 不提交数据库、WAL/SHM、日志、偏好、虚拟环境、临时截图或构建产物；遵守 `.gitignore`。

## 6. 样式与主题规范

保持浅色、紧凑的桌面工作窗口，以键盘和统计为主体。
不添加宣传页、装饰性大卡片、嵌套卡片或无关视觉效果。
现有主题入口是 `qiaoqiao/ui.py` 的 `STYLE`，键盘使用 `KeyboardWidget.paintEvent()` 自绘。

| 用途 | 现有约定 |
| --- | --- |
| 页面背景 | `#F3F5F7` |
| 普通键面 / 控件背景 | `#FFFFFF` |
| 正文 | `#20262B` |
| 次要文字 | `#6B7279` |
| 主交互、选中、按住边框、正常状态 | `#147D68` |
| 控件边框 / 键面边框 | `#D5DBE0` / `#D3DAE0` |
| 悬停背景 / 悬停边框 | `#E7EEEC` / `#93B5AA` |
| 禁用或 Fn 背景 | `#EDF0F2` |
| 保存错误 | `#A43B28`，现位于 `app.py` 的状态样式 |
| 热度 | 暖黄色系，按现有 `log1p` 比例和 `QColor.fromRgbF` 计算，不替换为单一固定色 |
| 圆角 | 现有控件和键面均为 5 px，新增同类元素保持一致 |

`DEVELOPMENT.md` 中的 `#DF9F39` 是暖黄色的设计参考，实际热度值以绘制代码为准。

- 中文界面使用 `Microsoft YaHei UI`，基准 10 pt；键名和数字使用 `Segoe UI`。
- 总次数保持完整整数及千位分隔，不以 `1.2k` 等缩写替代；悬停保留键名和完整次数。
- 使用固定字号，不按窗口宽度等比缩放字体。现有键面可按文字宽度缩小至 7 pt，下限仍不足时扩大内容区域并滚动。
- 默认窗口为 `1260 × 680`，最小为 `1040 × 570`；键盘通过 `QScrollArea` 处理窄窗口和极大数值。
- 沿用上部时间/日期/统计、中部键盘、底部布局/保存状态的顺序；布局切换不应使工具栏跳动。
- 图标按钮优先使用 Qt `QStyle.StandardPixmap`，并提供 tooltip 和可访问名称。
- 时段使用互斥可选按钮，日期使用 `QDateEdit`，布局使用互斥菜单，不用自由文本输入替代这些控件。
- 保留 hover、checked、disabled、focus 及错误状态；错误不能只用颜色表达。
- 新样式优先加入现有 `STYLE` 并复用语义对象名，避免到处添加重复的局部 `setStyleSheet()`。
- 如确需拆出主题模块，应同时覆盖 QSS 与自绘颜色，避免只改控件而漏改键盘。
- 图标原稿为 `assets/qiaoqiao-pixel.png`，通过 `tools/build_icon.py` 导出 ICO；保持最近邻缩放和像素边缘。
- 窗口、托盘、EXE 和快捷方式共用应用图标，不分别维护不同图案。

## 7. 编码约定

- 沿用现有 Python 风格：4 空格缩进，函数/变量 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE_CASE`。
- Qt 覆写方法保留框架名称，如 `paintEvent`、`closeEvent`，不为统一命名而改动接口。
- 新增或修改的公共接口补充有用的类型标注；数据模型优先沿用现有 `dataclass`。
- 文件、标识符使用清晰的英文；界面和用户文档使用中文，保持 UTF-8，不批量转换现有中文转义写法。
- 注释解释业务原因、线程边界和特殊硬件行为，不复述显而易见的赋值或循环。
- 不滥用宽泛异常捕获；边界处确需捕获时保留日志、用户状态和恢复路径。
- 新功能同时考虑启动、空数据、历史数据、失败重试和退出清理，不只实现正常路径。
- 资源路径必须兼容源码与 PyInstaller 包内目录；不要依赖进程当前工作目录。
- 需求、技术栈、目录、运行命令或主题发生实际变化时同步相关文档，避免本规范与实现脱节。

## 8. 开发与验证

以下命令在仓库根目录的 PowerShell 中执行，无需激活虚拟环境。
仅在环境缺失或依赖变更时安装依赖，不在每次任务中重建环境。

```powershell
# 初始化开发环境
py -3.15 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 启动独立验收实例；按任务选择专用目录
.\.venv\Scripts\python.exe run.py --dev --data-dir .\work\acceptance

# 针对单个模块验证，按修改范围替换文件名
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_core.py" -v

# 全量测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 依赖变更后检查
.\.venv\Scripts\python.exe -m pip check

# 检查补丁空白问题
git diff --check
```

### 按改动选择验证

| 改动范围 | 必须关注 |
| --- | --- |
| 计数 / 映射 / 日期 | `test_core.py`：长按、多设备、跨天、左右键、小键盘、特殊键 |
| 持久化 | `test_storage.py`：事务回滚、幂等、失败后最新值重试、退出前刷盘 |
| 布局 | `test_layouts.py` + `test_app.py`：唯一键 ID、无重叠、Fn、布局外统计、偏好和热度 |
| 原生监听 | `test_raw_input.py`：64 位 ABI、消息边界、注册/注销、会话状态 |
| 运行模式 / 生命周期 | `test_runtime.py` + `test_app.py`：目录隔离、单实例、托盘和退出失败恢复 |
| 打包 / 依赖 / 资源 | `test_build_release.py`、全量测试及实际构建冒烟 |
| 仅文档 | 核对路径、命令与实现，检查差异；不因此强制运行整套 UI 测试或打包 |

- 修复行为问题时优先添加能复现问题的聚焦测试；不为文案或低风险格式变化添加形式化测试。
- 跨模块修改及发布前运行全量测试。测试数量以本次输出为准，不照抄文档中的历史数字。
- 原生监听测试需要正常 Windows 桌面和真实 HWND，不能使用 Qt `offscreen` 替代后声称通过。
- UI 修改检查默认/最小窗口、100%/150% 缩放、零值/极大次数；涉及布局时覆盖六种预设。
- UI 验证应包含控件交互和实际截图，确认文本完整、按键无重叠、热度和按住状态可辨识；临时截图放 `work/`。
- 模拟事件、Qt Test 和截图不等同于 MK3 实机验收；真实特殊键、拔插、锁屏/休眠需要单独记录结果。
- 不因验收停止用户正在使用的正式实例；验证结束清理自己创建的实例和临时资源。
- 无法运行某项验证时明确说明原因及影响，不把未执行、模拟通过或历史记录写成当前实测通过。

## 9. 打包与交付

仅当任务涉及发布或确需验证打包行为时执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\build.ps1
```

- 保持 `.venv-build` 独立、Windows x64 文件夹包形式，以及构建时的 PATH / Python / Qt 环境隔离。
- 保留构建中的全量测试、源码一致性校验和包外干净环境 `--version` 冒烟，不绕过失败继续发布。
- 版本号只改 `qiaoqiao/__init__.py` 的 `__version__`；同版本产物拒绝覆盖，不删除旧产物来规避。
- 保留发布 ZIP、源码 ZIP、SHA-256 和 `release.json` 的可追溯信息；未提交构建不得宣称等于 Git 提交快照。
- 新增需要随包或源码快照交付的文件时，分别检查 `qiaoqiao.spec` 和 `tools/build_release.py:source_files()` 的收集范围。
- 发布包验收使用 `--dev --data-dir` 的隔离目录；构建成功和 `--version` 成功不能代替键盘、托盘实机验收。
- 替换正式程序、更新正式快捷方式或迁移正式数据只在用户要求的范围内执行；升级流程遵循 `README.md`。
- 交付说明列出实际改动、执行过的验证和剩余限制；区分源码已更新、发布包已生成、正式版已切换这三种状态。
