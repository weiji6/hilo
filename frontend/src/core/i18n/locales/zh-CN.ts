import {
  CompassIcon,
  GraduationCapIcon,
  ImageIcon,
  MicroscopeIcon,
  PenLineIcon,
  ShapesIcon,
  SparklesIcon,
  VideoIcon,
} from "lucide-react";

import type { Translations } from "./types";

export const zhCN: Translations = {
  // Locale meta
  locale: {
    localName: "中文",
  },

  // Common
  common: {
    home: "首页",
    settings: "设置",
    delete: "删除",
    rename: "重命名",
    share: "分享",
    openInNewWindow: "在新窗口打开",
    close: "关闭",
    more: "更多",
    search: "搜索",
    download: "下载",
    thinking: "思考",
    artifacts: "文件",
    public: "公共",
    custom: "自定义",
    notAvailableInDemoMode: "在演示模式下不可用",
    loading: "加载中...",
    version: "版本",
    lastUpdated: "最后更新",
    code: "代码",
    preview: "预览",
    cancel: "取消",
    save: "保存",
    install: "安装",
    create: "创建",
  },

  // Welcome
  welcome: {
    greeting: "你好，我是 Hilo。",
    description:
      "连接你的文档与知识，查找可靠依据，探索问题背后的线索。",

    createYourOwnSkill: "创建自己的技能",
    createYourOwnSkillDescription:
      "添加领域工作流，让 Hilo 适应你的研究方式。",
  },

  // Clipboard
  clipboard: {
    copyToClipboard: "复制到剪贴板",
    copiedToClipboard: "已复制到剪贴板",
    failedToCopyToClipboard: "复制到剪贴板失败",
    linkCopied: "链接已复制到剪贴板",
  },

  // Input Box
  inputBox: {
    placeholder: "想从资料中了解什么？",
    createSkillPrompt:
      "请说明技能的目标、使用场景和工作步骤。",
    addAttachments: "添加附件",
    mode: "模式",
    flashMode: "闪速",
    flashModeDescription: "快速且高效的完成任务，但可能不够精准",
    reasoningMode: "思考",
    reasoningModeDescription: "思考后再行动，在时间与准确性之间取得平衡",
    proMode: "Pro",
    proModeDescription: "思考、计划再执行，获得更精准的结果，可能需要更多时间",
    ultraMode: "Ultra",
    ultraModeDescription:
      "继承自 Pro 模式，可调用子代理分工协作，适合复杂多步骤任务，能力最强",
    researchProLabel: "研究 · Pro",
    researchProDescription:
      "思考、计划再执行，获得更精准的结果，输出报告",
    researchUltraLabel: "研究 · Ultra",
    researchUltraDescription:
      "在 Pro 基础上可调用子Agents分工协作,能更高效的完成复杂多步骤任务",
    qaProLabel: "问答 · Pro",
    qaProDescription:
      "直接回答问题，先结论后补充；适合日常问答",
    qaUltraLabel: "问答 · Simplest",
    qaUltraDescription:
      "极简作答：最短文字、点到为止，非必要不用工具，适合日常问答",
    researchScenario: "研究模型",
    qaScenario: "问答模式",
    searchModels: "搜索模型...",
    surpriseMe: "小惊喜",
    surpriseMePrompt: "给我一个小惊喜吧",
    suggestions: [
      {
        suggestion: "写作",
        prompt: "撰写一篇关于[主题]的博客文章",
        icon: PenLineIcon,
      },
      {
        suggestion: "研究",
        prompt: "深入浅出的研究一下[主题]，并总结发现。",
        icon: MicroscopeIcon,
      },
      {
        suggestion: "收集",
        prompt: "从[来源]收集数据并创建报告。",
        icon: ShapesIcon,
      },
      {
        suggestion: "学习",
        prompt: "学习关于[主题]并创建教程。",
        icon: GraduationCapIcon,
      },
    ],
    suggestionsCreate: [
      {
        suggestion: "网页",
        prompt: "生成一个关于[主题]的网页",
        icon: CompassIcon,
      },
      {
        suggestion: "图片",
        prompt: "生成一个关于[主题]的图片",
        icon: ImageIcon,
      },
      {
        suggestion: "视频",
        prompt: "生成一个关于[主题]的视频",
        icon: VideoIcon,
      },
      {
        type: "separator",
      },
      {
        suggestion: "技能",
        prompt:
          "我们一起用 skill-creator 技能来创建一个技能吧。先问问我希望这个技能能做什么。",
        icon: SparklesIcon,
      },
    ],
  },

  // Sidebar
  sidebar: {
    newChat: "新对话",
    chats: "对话",
    recentChats: "最近的对话",
    demoChats: "演示对话",
  },

  // Breadcrumb
  breadcrumb: {
    workspace: "工作区",
    chats: "对话",
  },

  // Workspace
  workspace: {
    officialWebsite: "访问Hilo官方网站",
    githubTooltip: "访问Hilo的 Github 仓库",
    settingsAndMore: "设置和更多",
    visitGithub: "在 Github 上查看Hilo",
    reportIssue: "报告问题",
    contactUs: "联系我们",
    about: "关于Hilo",
  },

  // Conversation
  conversation: {
    noMessages: "还没有消息",
    startConversation: "开始新的对话以查看消息",
  },

  // Chats
  chats: {
    searchChats: "搜索对话",
  },

  // Page titles (document title)
  pages: {
    appName: "Hilo",
    chats: "对话",
    newChat: "新对话",
    untitled: "未命名",
  },

  // Tool calls
  toolCalls: {
    moreSteps: (count: number) => `查看其他 ${count} 个步骤`,
    lessSteps: "隐藏步骤",
    executeCommand: "正在执行命令",
    presentFiles: "正在整理文件结果",
    needYourHelp: "需要你的补充信息",
    useTool: (toolName: string) => `正在调用“${toolName}”工具`,
    searchFor: (query: string) => `正在检索“${query}”`,
    searchForRelatedInfo: "正在检索相关信息",
    searchForRelatedImages: "正在检索相关图片",
    searchForRelatedImagesFor: (query: string) =>
      `正在检索“${query}”相关图片`,
    searchOnWebFor: (query: string) => `正在全网检索“${query}”`,
    searchBookCatalog: "正在检索权威书目",
    searchYourNotes: "正在检索您的笔记",
    searchThreadMaterials: "正在检索当前对话资料",
    searchKnowledgeBase: "正在检索知识库",
    locateKnowledgePassage: "正在定位原文位置",
    writeKnowledgeCheckpoint: "正在记录检索检查点",
    viewWebPage: "正在查看网页",
    listFolder: "正在查看目录",
    readFile: "正在读取文件",
    writeFile: "正在编辑文件",
    clickToViewContent: "点击查看文件内容",
    writeTodos: "正在更新任务清单",
    skillInstallTooltip: "安装技能并使其可在Hilo中使用",
  },

  subtasks: {
    subtask: "子任务",
    executing: (count: number) =>
      `${count > 1 ? "并行" : ""}执行 ${count} 个子任务`,
    in_progress: "子任务运行中",
    completed: "子任务已完成",
    failed: "子任务失败",
  },

  // Settings
  settings: {
    title: "设置",
    description: "根据你的偏好调整Hilo的界面和行为。",
    sections: {
      appearance: "外观",
      memory: "记忆",
      knowledge: "知识库",
      tools: "工具",
      skills: "技能",
      notification: "通知",
      about: "关于",
    },
    memory: {
      title: "记忆",
      description:
        "Hilo会在后台不断从你的对话中自动学习。这些记忆能帮助Hilo更好地理解你，并提供更个性化的体验。",
      empty: "暂无可展示的记忆数据。",
      rawJson: "原始 JSON",
      markdown: {
        overview: "概览",
        userContext: "用户上下文",
        work: "工作",
        personal: "个人",
        topOfMind: "近期关注（Top of mind）",
        historyBackground: "历史背景",
        recentMonths: "近几个月",
        earlierContext: "更早上下文",
        longTermBackground: "长期背景",
        updatedAt: "更新于",
        facts: "事实",
        empty: "（空）",
        table: {
          category: "类别",
          confidence: "置信度",
          confidenceLevel: {
            veryHigh: "极高",
            high: "较高",
            normal: "一般",
            unknown: "未知",
          },
          content: "内容",
          source: "来源",
          createdAt: "创建时间",
          view: "查看",
        },
      },
    },
    knowledge: {
      title: "知识库",
      description: "管理用于 RAG 检索的本地知识库文档。",
      status: {
        enabled: "知识库已启用",
        disabled: "知识库当前未启用，请在 config.yaml 中开启 knowledge_base。",
        docsPath: "文档目录",
        docCount: "向量条目数",
        collectionName: "Qdrant 集合名",
      },
      actions: {
        reindexTitle: "重新构建索引",
        reindexDescription:
          "手动触发对知识库目录中文档的全量索引。这在新增或大规模修改文档后非常有用。",
        reindex: "重新索引",
        reindexing: "正在重新索引...",
        reindexSuccess: "索引任务已触发。",
        reindexError: "重新索引失败",
      },
      upload: {
        title: "上传文档",
        description:
          "支持的格式：PDF、Markdown (.md) 和纯文本 (.txt) 文件。",
        selectFile: "选择文件",
        selectedFile: "已选择文件",
        noFile: "尚未选择文件",
        autoReindex: "上传后自动重新构建索引",
        uploadButton: "上传文档",
        uploading: "正在上传...",
        success: "上传成功。",
        error: "上传失败",
      },
      docs: {
        title: "已有文档",
        description:
          "当前知识库目录中的文档列表。删除文档后，可根据需要重新构建索引。",
        empty: "当前知识库目录中还没有文档。",
        filename: "文件名",
        size: "大小",
        actions: "操作",
      },
    },
    appearance: {
      themeTitle: "主题",
      themeDescription: "跟随系统或选择固定的界面模式。",
      system: "系统",
      light: "浅色",
      dark: "深色",
      systemDescription: "自动跟随系统主题。",
      lightDescription: "更明亮的配色，适合日间使用。",
      darkDescription: "更暗的配色，减少眩光方便专注。",
      languageTitle: "语言",
      languageDescription: "在不同语言之间切换。",
    },
    tools: {
      title: "工具",
      description: "管理 MCP 工具的配置和启用状态。",
    },
    skills: {
      title: "技能",
      description: "管理 Agent Skill 配置和启用状态。",
      createSkill: "新建技能",
      emptyTitle: "还没有技能",
      emptyDescription:
        "将你的 Agent Skill 文件夹放在Hilo根目录下的 `/skills/custom` 文件夹中。",
      emptyButton: "创建你的第一个技能",
    },
    notification: {
      title: "通知",
      description:
        "Hilo只会在窗口不活跃时发送完成通知，特别适合长时间任务：你可以先去做别的事，完成后会收到提醒。",
      requestPermission: "请求通知权限",
      deniedHint:
        "通知权限已被拒绝。可在浏览器的网站设置中重新开启，以接收完成提醒。",
      testButton: "发送测试通知",
      testTitle: "Hilo",
      testBody: "这是一条测试通知。",
      notSupported: "当前浏览器不支持通知功能。",
      disableNotification: "关闭通知",
    },
    acknowledge: {
      emptyTitle: "致谢",
      emptyDescription: "相关的致谢信息会展示在这里。",
    },
  },
};
