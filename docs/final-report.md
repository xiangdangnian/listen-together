# 最终测试报告

## 环境

- Windows 11
- Python 3.12.14
- PySide6-Essentials 6.8.3
- python-vlc 3.0.21203
- VLC 3.0.24 Vetinari
- PyInstaller 6.22.3

## 自动化测试

测试覆盖：

- 播放时间线、暂停位置和结束边界。
- 双进程时钟偏差估计。
- 播放器状态控制。
- 真实 VLC 加载、播放、暂停、跳转和速率设置。
- 元数据时长异常时通过 VLC 播放探测真实时长。
- 扩展名与实际容器不一致的 MP3 兼容播放。
- 音乐库扫描、元数据读取和 SHA-256。
- SQLite 音乐库缓存。
- 会话缓存导入、清理和异常会话清理。
- TCP 房间握手、房间口令校验。
- 控制消息双向传输。
- 文件上传和下载。
- 控制连接断开后的客户端自动重连。
- Host 单源文件分发。
- 普通成员单源文件分发。
- 双端状态同步。
- 晚加入成员触发全员暂停。
- 队列权限。
- 桌面窗口离屏渲染。

测试结果：

```text
Ran 26 tests
OK

compileall: OK
```

## 端到端验证

### 源码版界面

- 使用真实 Windows 平台启动。
- 完成窗口渲染、本地音乐加载、共享队列显示和截图验证。

截图：

```text
docs/app-smoke.png
```

### 打包版界面

- 使用 PyInstaller 生成 Windows 非控制台程序。
- 打包版成功启动并生成截图。

截图：

```text
docs/packaged-smoke.png
```

### 打包版音频

- 使用打包程序内置 VLC 运行库生成测试音。
- 完成加载、播放、暂停和跳转。
- 结果记录在 `docs/audio-self-test-packaged.log`。
- 对实际异常文件 `Max_Verstappen.mp3` 完成打包版扫描验证，时长从 1 ms 修正为 170713 ms。

## 产物

```text
dist\ListenTogether\ListenTogether.exe
dist\ListenTogether-Windows.zip
```

最终压缩包 SHA-256：

```text
ABBC1BB9E16D366229112AFB771B0ACE7EEDE3AB58F6B44A749C42336C602C61
```

## 剩余风险

- 自动化测试在同一台电脑上通过 TCP 回环完成，不能完全替代真实 Radmin 网络的带宽、抖动和防火墙差异。
- VLC 对变速的支持未进行双机主观试听，因此正式同步不启用软变速。
- Windows 不同声卡的输出缓冲差异可能需要真实设备上的个人同步偏移校准。
