# Hilo

**连接文档，循证探索。**

Hilo 是一个可扩展的 **Agentic RAG 与知识研究框架**：接入专业文档，通过目录路由、
正文证据定位与引用追溯回答问题，并在明确要求深入研究时组织子智能体协作。

项目基于 [DeerFlow](https://github.com/bytedance/deer-flow) 扩展，保留上游 MIT
许可证和署名。目前是早期的全栈源码框架，还没有稳定的独立 Python SDK。

## 快速开始

准备 Docker Compose、Git、Python 3.12+ 和模型服务 API Key：

```bash
git clone https://github.com/weiji6/hilo.git
cd hilo
make config
```

在 `backend/.env` 中填入自己的 `OPENAI_API_KEY`。可通过 `OPENAI_MODEL`、
`OPENAI_BASE_URL`、`EMBEDDING_MODEL`、`EMBEDDING_BASE_URL` 更换兼容服务。

```bash
make docker-start
make index-knowledge
```

访问 http://localhost:2026，注册本地账号，即可询问示例文档中的重试规则。
首次构建会下载依赖；Docker 模板包含前端、后端、认证数据库、Qdrant 和 nginx。
这套模板用于本地开发，不等于完成了公网生产部署加固。

初始化不会覆盖已有配置；会生成随机登录密钥，选择技术文档领域，并复制原创的模拟文档。
已有 `config.yaml` 时，需要自行修改其中的领域选择。

## 如何接入自己的领域

领域差异放在 YAML 中，不需要修改核心检索代码：

```yaml
domain:
  profile: examples/fiscal-history/domain.yaml
```

将资料放入 `knowledge/docs/`，重新建立索引，修改领域配置后重启后端。
配置路径相对于 `config.yaml`。领域配置目前在进程内共享，不支持逐会话切换。

- [技术文档示例](examples/technical-docs/)：提供模拟资料，可测试版本限定、引用和证据缺口。
- [财政历史示例](examples/fiscal-history/)：将原应用的时期别名、财政查询扩展和史料规范做成配置；不附带书籍。
- [领域扩展说明](docs/domain-profiles.md)：字段、查询预算、主子智能体共享与限制。
- [架构说明](docs/architecture.md)：通用层、领域适配层与交互层。

## 开发与贡献

```bash
make install
make test
cd frontend && pnpm typecheck
```

当前核心包括文档解析入库、目录选源、正文定位、编号引用、普通问答与深入研究路由。
独立 SDK、正式质量评测、逐请求领域切换和生产 API 授权是后续建设方向，
参见 [路线图](docs/roadmap.md)。引用编号检查不能代替逐句事实审核。

开源导出使用文件白名单，不携带原私有仓库的 Git 历史、生产配置、用户资料或录制会话。
见 [贡献指南](CONTRIBUTING.md)、[来源说明](NOTICE) 与 [MIT 许可证](LICENSE)。
