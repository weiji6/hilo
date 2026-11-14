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

export const enUS: Translations = {
  // Locale meta
  locale: {
    localName: "English",
  },

  // Common
  common: {
    home: "Home",
    settings: "Settings",
    delete: "Delete",
    rename: "Rename",
    share: "Share",
    openInNewWindow: "Open in new window",
    close: "Close",
    more: "More",
    search: "Search",
    download: "Download",
    thinking: "Thinking",
    artifacts: "Artifacts",
    public: "Public",
    custom: "Custom",
    notAvailableInDemoMode: "Not available in demo mode",
    loading: "Loading...",
    version: "Version",
    lastUpdated: "Last updated",
    code: "Code",
    preview: "Preview",
    cancel: "Cancel",
    save: "Save",
    install: "Install",
    create: "Create",
  },

  // Welcome
  welcome: {
    greeting: "Welcome to the Scholarly Pavilion.",
    description:
      "Within these digital halls lie the records of fiscal lineages across the ages. We stand ready to assist your inquiry into the deep currents of history.",

    createYourOwnSkill: "Forge New Pathways",
    createYourOwnSkillDescription:
      "Design your proprietary strategies to navigate the vast sea of records and establish your own historical thesis.",
  },

  // Clipboard
  clipboard: {
    copyToClipboard: "Copy to clipboard",
    copiedToClipboard: "Copied to clipboard",
    failedToCopyToClipboard: "Failed to copy to clipboard",
    linkCopied: "Link copied to clipboard",
  },

  // Input Box
  inputBox: {
    placeholder: "Inquire within... your command is awaited.",
    createSkillPrompt:
      "Grant me the blueprints of your strategy, and I shall labor to fulfill its structure and vision.",
    addAttachments: "Add attachments",
    mode: "Mode",
    flashMode: "Flash",
    flashModeDescription: "Fast and efficient, but may not be accurate",
    reasoningMode: "Reasoning",
    reasoningModeDescription:
      "Reasoning before action, balance between time and accuracy",
    proMode: "Pro",
    proModeDescription:
      "Reasoning, planning and executing, get more accurate results, may take more time",
    ultraMode: "Ultra",
    ultraModeDescription:
      "Pro mode with subagents to divide work; best for complex multi-step tasks",
    researchProLabel: "Research · Pro",
    researchProDescription:
      "Think, plan, then execute—more accurate, may take longer (same as legacy Pro)",
    researchUltraLabel: "Research · Ultra",
    researchUltraDescription:
      "Pro plus subagents for parallel work; best for complex tasks (same as legacy Ultra)",
    qaProLabel: "Q&A · Pro",
    qaProDescription:
      "Answer directly—conclusion first, brief support; no todo lists or subagents",
    qaUltraLabel: "Q&A · Ultra",
    qaUltraDescription:
      "Ultra-concise replies; skip tools unless essential",
    researchScenario: "Research",
    qaScenario: "Q&A",
    searchModels: "Search models...",
    surpriseMe: "Surprise",
    surpriseMePrompt: "Surprise me",
    suggestions: [
      {
        suggestion: "Write",
        prompt: "Write a blog post about the latest trends on [topic]",
        icon: PenLineIcon,
      },
      {
        suggestion: "Research",
        prompt:
          "Conduct a deep dive research on [topic], and summarize the findings.",
        icon: MicroscopeIcon,
      },
      {
        suggestion: "Collect",
        prompt: "Collect data from [source] and create a report.",
        icon: ShapesIcon,
      },
      {
        suggestion: "Learn",
        prompt: "Learn about [topic] and create a tutorial.",
        icon: GraduationCapIcon,
      },
    ],
    suggestionsCreate: [
      {
        suggestion: "Webpage",
        prompt: "Create a webpage about [topic]",
        icon: CompassIcon,
      },
      {
        suggestion: "Image",
        prompt: "Create an image about [topic]",
        icon: ImageIcon,
      },
      {
        suggestion: "Video",
        prompt: "Create a video about [topic]",
        icon: VideoIcon,
      },
      {
        type: "separator",
      },
      {
        suggestion: "Skill",
        prompt:
          "We're going to build a new skill step by step with `skill-creator`. To start, what do you want this skill to do?",
        icon: SparklesIcon,
      },
    ],
  },

  // Sidebar
  sidebar: {
    newChat: "New chat",
    chats: "Chats",
    recentChats: "Recent chats",
    demoChats: "Demo chats",
  },

  // Breadcrumb
  breadcrumb: {
    workspace: "Workspace",
    chats: "Chats",
  },

  // Workspace
  workspace: {
    officialWebsite: "Hilo's official website",
    githubTooltip: "Hilo on Github",
    settingsAndMore: "Settings and more",
    visitGithub: "Hilo on GitHub",
    reportIssue: "Report a issue",
    contactUs: "Contact us",
    about: "About Hilo",
  },

  // Conversation
  conversation: {
    noMessages: "No messages yet",
    startConversation: "Start a conversation to see messages here",
  },

  // Chats
  chats: {
    searchChats: "Search chats",
  },

  // Page titles (document title)
  pages: {
    appName: "Hilo",
    chats: "Chats",
    newChat: "New chat",
    untitled: "Untitled",
  },

  // Tool calls
  toolCalls: {
    moreSteps: (count: number) => `${count} more step${count === 1 ? "" : "s"}`,
    lessSteps: "Less steps",
    executeCommand: "Running command",
    presentFiles: "Preparing files",
    needYourHelp: "Need more information from you",
    useTool: (toolName: string) => `Using "${toolName}" tool`,
    searchFor: (query: string) => `Searching for "${query}"`,
    searchForRelatedInfo: "Searching for related information",
    searchForRelatedImages: "Searching for related images",
    searchForRelatedImagesFor: (query: string) =>
      `Searching for images related to "${query}"`,
    searchOnWebFor: (query: string) => `Searching the web for "${query}"`,
    searchBookCatalog: "Searching authoritative books",
    searchYourNotes: "Searching your notes",
    searchThreadMaterials: "Searching this conversation's materials",
    searchKnowledgeBase: "Searching the knowledge base",
    locateKnowledgePassage: "Locating the source passage",
    writeKnowledgeCheckpoint: "Recording retrieval checkpoint",
    viewWebPage: "Opening web page",
    listFolder: "Inspecting folder",
    readFile: "Reading file",
    writeFile: "Editing file",
    clickToViewContent: "Click to view file content",
    writeTodos: "Updating to-do list",
    skillInstallTooltip:
      "Install skill and make it available to Hilo",
  },

  // Subtasks
  subtasks: {
    subtask: "Subtask",
    executing: (count: number) =>
      `Executing ${count === 1 ? "" : count + " "}subtask${count === 1 ? "" : "s in parallel"}`,
    in_progress: "Running subtask",
    completed: "Subtask completed",
    failed: "Subtask failed",
  },

  // Settings
  settings: {
    title: "Settings",
    description: "Adjust how Hilo looks and behaves for you.",
    sections: {
      appearance: "Appearance",
      memory: "Memory",
      knowledge: "Knowledge base",
      tools: "Tools",
      skills: "Skills",
      notification: "Notification",
      about: "About",
    },
    memory: {
      title: "Memory",
      description:
        "Hilo automatically learns from your conversations in the background. These memories help Hilo understand you better and deliver a more personalized experience.",
      empty: "No memory data to display.",
      rawJson: "Raw JSON",
      markdown: {
        overview: "Overview",
        userContext: "User context",
        work: "Work",
        personal: "Personal",
        topOfMind: "Top of mind",
        historyBackground: "History",
        recentMonths: "Recent months",
        earlierContext: "Earlier context",
        longTermBackground: "Long-term background",
        updatedAt: "Updated at",
        facts: "Facts",
        empty: "(empty)",
        table: {
          category: "Category",
          confidence: "Confidence",
          confidenceLevel: {
            veryHigh: "Very high",
            high: "High",
            normal: "Normal",
            unknown: "Unknown",
          },
          content: "Content",
          source: "Source",
          createdAt: "CreatedAt",
          view: "View",
        },
      },
    },
    knowledge: {
      title: "Knowledge base",
      description:
        "Manage local knowledge documents used for RAG-based retrieval.",
      status: {
        enabled: "Knowledge base is enabled.",
        disabled:
          "Knowledge base is currently disabled. Please enable `knowledge_base` in config.yaml.",
        docsPath: "Docs path",
        docCount: "Vector entries",
        collectionName: "Qdrant collection",
      },
      actions: {
        reindexTitle: "Rebuild index",
        reindexDescription:
          "Manually trigger a full reindex of all documents in the knowledge docs directory. Useful after adding or updating many documents.",
        reindex: "Reindex",
        reindexing: "Reindexing...",
        reindexSuccess: "Reindex task has been triggered.",
        reindexError: "Failed to reindex",
      },
      upload: {
        title: "Upload documents",
        description:
          "Supported formats: PDF, Markdown (.md), and Text (.txt) files.",
        selectFile: "Select file",
        selectedFile: "Selected file",
        noFile: "No file selected",
        autoReindex: "Automatically rebuild index after upload",
        uploadButton: "Upload document",
        uploading: "Uploading...",
        success: "Upload succeeded.",
        error: "Upload failed",
      },
      docs: {
        title: "Existing documents",
        description:
          "Documents currently stored in the knowledge docs directory. After deleting files, you may want to rebuild the index.",
        empty: "No documents found in the knowledge docs directory.",
        filename: "Filename",
        size: "Size",
        actions: "Actions",
      },
    },
    appearance: {
      themeTitle: "Theme",
      themeDescription:
        "Choose how the interface follows your device or stays fixed.",
      system: "System",
      light: "Light",
      dark: "Dark",
      systemDescription: "Match the operating system preference automatically.",
      lightDescription: "Bright palette with higher contrast for daytime.",
      darkDescription: "Dim palette that reduces glare for focus.",
      languageTitle: "Language",
      languageDescription: "Switch between languages.",
    },
    tools: {
      title: "Tools",
      description: "Manage the configuration and enabled status of MCP tools.",
    },
    skills: {
      title: "Agent Skills",
      description:
        "Manage the configuration and enabled status of the agent skills.",
      createSkill: "Create skill",
      emptyTitle: "No agent skill yet",
      emptyDescription:
        "Put your agent skill folders under the `/skills/custom` folder under the root folder of Hilo.",
      emptyButton: "Create Your First Skill",
    },
    notification: {
      title: "Notification",
      description:
        "Hilo only sends a completion notification when the window is not active. This is especially useful for long-running tasks so you can switch to other work and get notified when done.",
      requestPermission: "Request notification permission",
      deniedHint:
        "Notification permission was denied. You can enable it in your browser's site settings to receive completion alerts.",
      testButton: "Send test notification",
      testTitle: "Hilo",
      testBody: "This is a test notification.",
      notSupported: "Your browser does not support notifications.",
      disableNotification: "Disable notification",
    },
    acknowledge: {
      emptyTitle: "Acknowledgements",
      emptyDescription: "Credits and acknowledgements will show here.",
    },
  },
};
