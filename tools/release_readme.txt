敲敲：Windows 本地键盘次数统计

1. 把整个文件夹解压到固定位置，例如 D:\Apps\Qiaoqiao\0.1.1。
2. 双击“敲敲.exe”开始统计。无需安装 Python，也不依赖开发项目。
3. 双击 Create-Desktop-Shortcut.cmd，可以创建或更新桌面的“敲敲”快捷方式。
4. 关闭或最小化窗口会继续在托盘统计；真正退出请使用托盘右键的“退出程序”。
5. 请保留整个文件夹，尤其是 _internal，不能只移动 EXE。

正式数据一直保存在 %LOCALAPPDATA%\Qiaoqiao\counts.sqlite3。
升级程序不会清空历史。日志为同一目录下的 app.log。
release.json 记录程序版本、构建依赖、Git 状态和源码校验值。

升级：
先从托盘退出旧版并备份数据库，再把新版解压到新的版本目录。
运行新版文件夹中的 Create-Desktop-Shortcut.cmd 更新桌面入口，再启动新版。
升级后保留旧程序及升级前的数据备份。
若新版升级了数据库结构，旧程序可能无法直接读取新版数据。

开发测试：
源码启动默认使用 %LOCALAPPDATA%\Qiaoqiao-dev，不会写正式统计。
测试这个发布包时，可在终端使用：
  .\敲敲.exe --dev
或指定独立的测试数据目录：
  .\敲敲.exe --dev --data-dir D:\Qiaoqiao-test
测试模式的窗口和托盘会标明“开发版”。
