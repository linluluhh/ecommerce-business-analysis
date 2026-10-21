# V2.1 本地发布候选

## 基线与策略

- 目标：`https://github.com/linluluhh/ecommerce-business-analysis` 的 `main`。
- 获取的远程基线：`c7146b45806386d194c88c2109fd25a71b6dae9a`（已公开 V1）。
- 文件快照来源：`b95b9e455fcacb252fd80fd3ad6bd333565fd07b`（V2.1 开发版）。
- 分支：`release/v2.1-portfolio`；在独立 worktree 从远程基线建立，形成一个直接子提交，不 merge/cherry-pick 本地开发历史。
- V1 四个公开提交完整保留。远程基线也是开发版共同祖先，未发现额外远程更新。原本 origin 指向安全备份的本地引用已改名 safety-origin，origin 改为上述 GitHub 仓库；未向备份写入。

## 发布范围

保留 V1 的数据、报告、Notebook、SQL、脚本、静态 Dashboard 和许可证。根 README 改为 V2.1，原 V1 介绍独立保存，提醒 V1 构建脚本会重建根 README，应在副本中重跑。

V2.1 Python 源码、SQL 结构/迁移、浏览器脚本、依赖锁、测试及 Synthetic 示例均原样来自验收版本。包含质量、审核、修订、指标、13 条手动预警、日报、HTML 导出，以及架构/演示文档、七张真实截图和一个 HTML 样例。

发布整理仅修改说明与忽略规则：排除 `v2/evidence/` 下 15 个原始 JSON/XML 和 20 张重复历史截图，避免机器名、运行状态及过量测试产物公开；完整原件留在开发仓库。保留精选 `docs/portfolio/` 验收副本及 `assets/v21/` 展示文件。历史验收 Markdown 明确注明原始材料不随发布快照提供。

## 风险分类

|类别|本次处理|
|---|---|
|A：已公开 V1|原历史不重写；既有作者使用 GitHub noreply。V1 内容不因升级被删除。既有第三方可视化资源中的联系文本沿用公开版本。|
|B：本地开发历史|路径、非 noreply 邮箱和中间提交不在发布提交祖先链中；开发分支保持原样。|
|C：新增内容|排除原始机器报告；新提交使用已公开 noreply 身份。常见 token/私钥扫描无命中；合成安全测试中的 SecretUser 路径是测试输入，不是真实身份。|

不含运行数据库、上传原件、缓存、环境密钥或临时日志。有限模式扫描不构成全面安全认证。没有生产权限、平台自动同步、计划通知或 AI 助手；全部经营演示均为 Synthetic。

## 本轮发布验证

- 检查 V2.1 源码、测试、SQL、依赖与示例文件和开发提交的 Git blob/文件内容一致；没有修改指标或业务逻辑。
- Python AST 语法检查通过；使用既有验收 Python 环境 `pip check` 返回无依赖冲突。没有声称本轮进行了联网全新安装。
- 发布目录模块导入指向本 worktree；六个工作表的 Synthetic XLSX 可读取。
- 在忽略的独立空目录执行一次 Streamlit AppTest 入口冒烟，页面无异常。不是新一轮全量测试或浏览器验收。
- 检查文档相对链接、图片、七张截图与 HTML 样例、候选文件清单和忽略规则；验证 V1 无删除、发布提交继承 main。
- 沿用对应功能版本的 176 passed 与 C2 浏览器证据，不把它们标为本轮新执行。

## 获得授权后的非强制发布

必须在本发布 worktree 操作。重新 fetch 并确认 main 仍是上述基线；若已前进，停止并检查更新。然后使用明确 refspec：

```powershell
git fetch origin main
# 确认输出仍为 c7146b45806386d194c88c2109fd25a71b6dae9a
git rev-parse origin/main
git merge-base --is-ancestor origin/main release/v2.1-portfolio
# 仅在检查通过且已获得正式推送授权后执行：
git push origin release/v2.1-portfolio:main
```

不使用 force。若分支保护要求 PR，停止直接更新并按仓库规则另行处理。本轮未创建远程分支、未执行 push。

发布后 fetch main，核对 main 等于本地发布提交；检查 GitHub 首页、图片、Mermaid、V1 入口和 Synthetic 说明；下载 HTML 离线打开。可在全新目录 clone，按 README 安装/启动，确认发布文件完整。不要将此本地应用部署为无认证的公开服务。
