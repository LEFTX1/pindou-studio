<p align="center">
  <img src="docs/logo.png" width="128" alt="豆绘工坊 Logo" />
</p>

<h1 align="center">豆绘工坊 (Pindou Studio)</h1>

<p align="center">
  离线拼豆图纸生成 · 放大框选裁剪 · 历史图纸与成品照智能识别 · 作品馆成就统计 · 国内五品牌色号对照 Android App
</p>

## 核心亮点

- **纯离线拍照转拼豆**：支持「照片融合精修」与「异形描边镂空」（测地线轮廓抠图 + 阴影脖颈无缝桥接），针对国内常用拼板（`29×29`、`40×40`、`48×48`、`52×52`、`72×72`）一键生成高清色号图，内置白毛偏绿抑制与圆眼等大对称抗锯齿。
- **交互式放大框选 & 相册直达**：相册选图默认直达系统原生相册；导入后支持双指缩放、快捷倍率、`90°` 旋转及 `自由 / 1:1 / 3:4 / 4:3` 自由框选局部区域，并自动矫正 EXIF 拍照方向。
- **历史外部图纸 & 成品照智能识别**：导入小红书/其他生成器导出的网格图纸或实拍拼好/烫好成品照，自动锁定格线、剥离坐标标尺并避让字码提取 MARD 色号，或扣除桌面反光还原成可编辑图纸。
- **国内五大品牌实时互转**：内置 221 色基准色卡，支持 **MARD / COCO / 漫漫 / 盼盼 / 咪小窝** 一键切换，支持 `2.6mm` / `5.0mm` 规格换算与采购备豆清单导出。
- **物理级热熨成品预览**：模拟 2.6mm 融合豆在烘焙油纸下融平闭孔、次表面暖色调与边缘 3D 厚度质感。
- **作品馆与拼豆成就统计盘**：每件作品支持选填关联【参考图 / 拼豆图纸 / 拼好的图 / 烫好的图】4 个过程槽位，统计总拼豆数、豆链米数、解锁 6 大成就勋章、配色指纹环形图与用豆排行对比。
- **免梯云端推送更新**：托管于本仓库 Release + 多路国内加速镜像，安装端内「作品库 → 检查更新」即可自动校验 SHA-256 并升级保留作品数据。

## 目录结构

```text
pindou-studio/
├── android-app/          # Android 客户端（Kotlin + Jetpack Compose）
├── web-studio/           # 本地 Python Web 工坊、CLI、核心引擎与单元测试
│   ├── app/              # FastAPI 交互式工坊后端与前端静态页
│   ├── pindou_core/      # 标准色卡与拼豆转换核心库
│   ├── tests/            # 自动化单元测试
│   ├── run_app.py        # Web 工坊启动入口
│   ├── pindou_cli.py     # 命令行工具
│   └── launch_app.bat    # Windows 一键启动脚本
├── docs/                 # 品牌 Logo 等文档资源
├── scripts/              # Release 更新清单生成脚本
├── update/               # 在线热更新清单（version.json）
├── .gitignore
└── README.md
```

## 本地构建与运行

- **Android 客户端编译**：
  ```bash
  cd android-app
  ./gradlew assembleRelease
  ```
- **Web 工坊与单元测试**：
  ```bash
  python web-studio/run_app.py
  python -m unittest discover -s web-studio/tests -v
  ```

## 最新下载

前往 [Releases 页面](https://github.com/LEFTX1/pindou-studio/releases) 下载最新正式签名 APK。
