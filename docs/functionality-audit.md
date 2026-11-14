# Hilo 功能与发布核对记录

核对日期：2026-11-15。此记录区分源码保留、可复现测试与需要外部服务的验收。

## 仓库与历史

`weiji6/hilo` 是个人账号下的新独立公开仓库，基于经过筛选的源码快照建立，
没有导入原私有仓库的 Git 提交图。原仓库及其历史仍独立保留；本次修改不重写任一仓库的历史。
这不代表全部代码均为 Hilo 作者原创：DeerFlow 等上游的版权与 MIT 许可继续保留在 LICENSE、NOTICE。

## 对比结论

首次公开版与原工作副本比较：`backend/src` 中原有 155 个源码文件、
`frontend/src` 中原有 252 个文件均有对应文件；协议、后端服务与公共 Skills 文件也均保留。
这是文件覆盖核对，不是所有行为完全等价的证明。框架化还修改了领域配置、默认提示词、
产品文案、环境变量兼容、示例配置和启动方式。

首次发布存在配套工具遗漏和默认配置缩减，不能称为完整功能等价。本次补齐：

| 能力 | 修复与保留方式 |
| --- | --- |
| 结构化文档 SQLite 入库/FTS | 恢复 `scripts/ingest_structured_docs_to_db.py`，修正 `--docs-dir` 对默认 DB 路径的作用，支持缺失 DB 重建 |
| 知识库预热与向量重建 | 恢复 `scripts/prewarm_knowledge_indexes.py`、`scripts/reindex_global_knowledge.py` |
| 段落 ID 规范化 | 恢复 `scripts/normalize_structured_paragraph_ids.py` |
| PDF OCR 命令行 | 恢复 `backend/scripts/local_ocr.py`；需要用户部署兼容 MinerU gRPC 服务 |
| Kubernetes 沙箱组件 | 恢复 `docker/provisioner/app.py` 与镜像构建文件，另附通用配置文档 |
| 默认 Agent 工具 | 恢复 ls/read_file/bash/web_fetch/image_search 配置，Skills 可用 read_file 加载；研究子 Agent 仍受来源/工具范围约束 |
| Linux 本地命令执行 | 解除 `/bin/zsh` 硬依赖，按可用性回退到 bash、/bin/sh |
| Docker 辅助入口 | `scripts/docker.sh` 兼容模式检测并转到新的 Hilo Compose 命令，不使用原私有部署栈 |
| 源码导出 | 显式列入以上组件，回归测试检查实际导出目录中的运行源码与工具完整性 |

原部署专用 Compose/nginx、服务器同步/远程资料抓取、CI runner 安装、生产部署脚本、
私有数据修复和调试/性能采样脚本不随公开版发布。全量清空 Qdrant 再重建的旧维护脚本也未发布；
公开版提供面向配置知识库的重建入口。原录屏、示例会话和展示图片被排除。
这些不应被描述为已移植的部署/维护功能。新 Compose 是可移植的本地开发配置。

## 验证范围

本次本地执行 `make test`：**172 passed**。变更 Python 文件通过 Ruff，发布检查通过。

本次新增回归直接使用 SQLite 和虚构结构化文档，验证入库后实际 locator 与 FTS
可以读回正文、物理页码和段落坐标；验证源文件标记仍在时可以重建缺失数据库。
默认配置的工具引用会解析为真实工具实现，并实测无 zsh 时本地 shell 可执行与报告退出码。
导出测试检查 backend/src、frontend/src、协议、服务、公共 Skills 及支持脚本均保留。
原有检索预算、正文证据、目录路由、引用和领域隔离回归继续执行。

`make test` 是选定的框架回归套件，不是全部历史测试。历史套件存在过时断言和模块模拟的
相互污染；本次全量收集得到 458 个测试和 1 个收集错误（translation_grpc 的模块模拟冲突）。
通过框架套件不表示全量历史测试已通过。修复的工具可用性测试使用公开示例配置，
并按现有子 Agent 的 scoped retrieval + submit_task_result 行为检查允许的工具。

前端对静态演示目录缺失添加空列表/404 与跳转回退，避免排除旧录屏后读取不存在目录。
首次发布已通过 TypeScript 检查与生产构建；本次再次执行 TypeScript 检查。结果见仓库 Actions。

## 尚未完成的外部验收

- 全新机器上构建并启动全部 Docker 服务，完成注册、上传、检索、流式问答的完整流程。
- 真实聊天模型与嵌入模型调用、回答质量与引用语义正确性评估。
- 外部 MinerU OCR、Kubernetes/AIO 沙箱创建、MCP 服务器和网络工具的真实服务调用。
- 原私有部署的配置、数据、账号、向量库和检查点迁移。

因此当前可确认的是核心源码保留、已发现发布遗漏已修复、列明的回归路径可验证，
不能保证所有服务组合与全部原应用行为均已端到端验收。
