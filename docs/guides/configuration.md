# 配置文件详解

深入理解 `config.yaml` 和 `.env` 的配置选项。

---

## 📄 config.yaml

项目的主配置文件，使用 YAML 格式。

### 完整示例

```yaml
sources:
  aibase: true
  techcrunch: true
  theverge: true
  syft: false

limits:
  max_articles: 14

summarize:
  prompt_path: prompts/daily.md
  prefer_chinese: true
  compress:
    title_max: 200
    desc_max: 400

output:
  json_dir: data
  md_dir: content
```

---

## 🔧 配置详解

### 1. sources (新闻源)

控制启用哪些新闻源。

```yaml
sources:
  aibase: true       # AIBase (中文 AI 资讯)
  techcrunch: true   # TechCrunch (英文科技新闻)
  theverge: true     # The Verge (英文科技新闻)
  syft: false        # Self-hosted Syft (需额外配置)
```

**选项**:
- `true`: 启用该新闻源
- `false`: 禁用该新闻源

**示例场景**:

**仅中文内容**:
```yaml
sources:
  aibase: true
  techcrunch: false
  theverge: false
```

**仅英文内容**:
```yaml
sources:
  aibase: false
  techcrunch: true
  theverge: true
```

**添加自定义源** (见 [扩展新闻源教程](extending-sources.md)):
```yaml
sources:
  aibase: true
  custom_source: true  # 需在 sources/ 中实现
```

---

### 2. limits (限制)

```yaml
limits:
  max_articles: 14  # 每天最多文章数
```

**作用**:
- 去重后的文章数超过此值时，保留最新的 N 篇
- 防止某天新闻过多导致摘要过长

**推荐值**:
- 日报: `10-15`
- 周报: `30-50`

**示例**:
```yaml
limits:
  max_articles: 20  # 增加到 20 篇
```

---

### 3. summarize (摘要配置)

#### 3.1 prompt_path

```yaml
summarize:
  prompt_path: prompts/daily.md
```

**作用**: 指定 AI Prompt 模板文件路径

**自定义 Prompt**:
1. 复制 `prompts/daily.md` 为 `prompts/weekly.md`
2. 修改内容 (见下文 "Prompt 模板定制")
3. 更新配置:
   ```yaml
   summarize:
     prompt_path: prompts/weekly.md
   ```

#### 3.2 prefer_chinese

```yaml
summarize:
  prefer_chinese: true
```

**作用**: 优先使用中文进行摘要 (如果 LLM 支持)

**选项**:
- `true`: Prompt 中包含 "使用中文回复"
- `false`: 使用 LLM 默认语言

#### 3.3 compress (内容压缩)

```yaml
summarize:
  compress:
    title_max: 200   # 标题最大字符数
    desc_max: 400    # 描述最大字符数
```

**作用**: 
- 截断过长的标题和描述
- 避免 Token 超过 LLM 限制

**中文优化** (已应用):
- 中文字符占用更多 Token
- 默认值 `title_max: 200, desc_max: 400` 适配中英文混合

**调整建议**:
| 场景 | title_max | desc_max |
|------|-----------|----------|
| 纯英文 | 100 | 300 |
| 中英混合 | 200 | 400 |
| 纯中文 | 150 | 350 |

---

### 4. output (输出路径)

```yaml
output:
  json_dir: data      # JSON 文件存储目录
  md_dir: content     # Markdown 文件存储目录
```

**默认结构**:
```
data/
└── 2026-01-21.json

content/
└── 2026-01-21.md
```

**自定义路径**:
```yaml
output:
  json_dir: archive/json
  md_dir: posts
```

**生成结构**:
```
archive/json/
└── 2026-01-21.json

posts/
└── 2026-01-21.md
```

> ⚠️ **注意**: 修改路径后需同步更新 `build.py` 中的路径

---

## 🔐 .env (环境变量)

敏感配置使用环境变量存储，从不提交到 Git。

### 完整示例

```bash
# ModelScope API Configuration
MODELSCOPE_API_KEY=sk-1234567890abcdef
MODELSCOPE_MODEL=ZhipuAI/GLM-4.7

# Syft Configuration (Optional)
SYFT_WEB_APP_URL=https://syft.example.com
SYFT_SECRET_KEY=your-syft-secret-key
```

---

## 🔧 环境变量详解

### 1. MODELSCOPE_API_KEY (必需*)

```bash
MODELSCOPE_API_KEY=sk-1234567890abcdef
```

**作用**: ModelScope API 认证密钥

**获取方式**:
1. 访问 [ModelScope 控制台](https://modelscope.cn/my/myaccesstoken)
2. 注册/登录
3. 创建 API Token
4. 复制到 `.env`

**必需性**:
- ✅ **API Mode**: 必需
- ❌ **Offline Mode** (`--offline`): 不需要

### 2. MODELSCOPE_MODEL (可选)

```bash
MODELSCOPE_MODEL=ZhipuAI/GLM-4.7
```

**作用**: 指定使用的 LLM 模型

**支持的模型** (兼容 OpenAI API):
```bash
# 智谱 AI
MODELSCOPE_MODEL=ZhipuAI/GLM-4.7
MODELSCOPE_MODEL=ZhipuAI/GLM-4

# Qwen 系列
MODELSCOPE_MODEL=qwen/Qwen2.5-72B-Instruct
MODELSCOPE_MODEL=qwen/Qwen-Max

# DeepSeek
MODELSCOPE_MODEL=deepseek-ai/DeepSeek-V2
```

**默认值**: `ZhipuAI/GLM-4.7`

### 3. SYFT_* (可选)

仅在启用 `syft` 新闻源时需要。

```bash
SYFT_WEB_APP_URL=https://syft.example.com
SYFT_SECRET_KEY=your-syft-secret-key
```

**作用**: 连接自建 Syft 实例

**启用方式**:
```yaml
# config.yaml
sources:
  syft: true
```

---

## 🎨 Prompt 模板定制

### 默认 Prompt (`prompts/daily.md`)

```markdown
你是一个专业的科技新闻编辑，负责撰写每日资讯摘要。

**任务要求**:
1. 将提供的新闻列表整理为 Markdown 格式
2. 按重要性排序，优先展示 AI 和前沿科技相关内容
3. 每条新闻包含标题 (带链接)、简短总结 (50 字内)
4. 使用友好、专业的语气
5. 必须使用中文输出

**输出格式**:
## 📰 今日要闻

### 🔥 [新闻标题](链接)
简短总结...

### 🚀 [新闻标题](链接)
简短总结...
```

### 自定义 Prompt 示例

**周报 Prompt** (`prompts/weekly.md`):

```markdown
你是一个科技分析师，负责撰写每周深度报告。

**任务要求**:
1. 分析本周科技新闻趋势
2. 按主题分类 (如: AI、硬件、创投、政策)
3. 每个主题包含 3-5 条代表性新闻
4. 提供趋势分析和未来展望
5. 使用中文输出

**输出格式**:
# 科技周报 (Week XX, 2026)

## 🤖 人工智能
### [新闻1](链接)
描述...

### [新闻2](链接)
描述...

**本周趋势**: ...

---

## 💻 硬件与芯片
...
```

**简洁 Prompt** (`prompts/brief.md`):

```markdown
将以下新闻整理为简洁的列表，每条新闻仅保留标题和链接，无需摘要。

**输出格式**:
- [新闻标题1](链接1)
- [新闻标题2](链接2)
```

---

## 🔄 配置优先级

当相同配置在多处出现时，遵循以下优先级:

```
环境变量 (.env) > config.yaml > 默认值
```

**示例**:

```yaml
# config.yaml
summarize:
  prefer_chinese: true
```

```bash
# .env
PREFER_CHINESE=false  # 此值会覆盖 config.yaml
```

**实际生效**: `prefer_chinese = false`

---

## 🛠️ 验证配置

### 检查配置文件语法

```bash
# 使用 Python 验证 YAML
python -c "import yaml; yaml.safe_load(open('config.yaml'))"
```

**成功**: 无输出  
**失败**: 显示语法错误

### 测试环境变量

```bash
# Windows PowerShell
$env:MODELSCOPE_API_KEY
# 输出: sk-1234567890abcdef

# Linux/macOS
echo $MODELSCOPE_API_KEY
# 输出: sk-1234567890abcdef
```

### 完整配置测试

```bash
# 测试 API 连接
python main.py test

# 运行离线模式 (不依赖 API Key)
python main.py run --offline
```

---

## 🔒 安全最佳实践

### ✅ DO

- ✅ 将 `.env` 添加到 `.gitignore`
- ✅ 提供 `.env.example` 作为模板
- ✅ 在文档中标明必需/可选配置
- ✅ 定期轮换 API Key

### ❌ DON'T

- ❌ 在 `config.yaml` 中硬编码 API Key
- ❌ 提交 `.env` 到 Git
- ❌ 在代码中使用 `print(api_key)`

---

## 📚 配置模板

### 快速启动模板

**.env.example**:
```bash
# Required for API Mode
MODELSCOPE_API_KEY=sk-your-api-key-here
MODELSCOPE_MODEL=ZhipuAI/GLM-4.7

# Optional: Syft Integration
# SYFT_WEB_APP_URL=https://syft.example.com
# SYFT_SECRET_KEY=your-syft-secret-key
```

**config.yaml** (默认):
```yaml
sources:
  aibase: true
  techcrunch: true
  theverge: true

limits:
  max_articles: 14

summarize:
  prompt_path: prompts/daily.md
  prefer_chinese: true
  compress:
    title_max: 200
    desc_max: 400

output:
  json_dir: data
  md_dir: content
```

---

## 🔗 相关资源

- [扩展新闻源教程](extending-sources.md)
- [API 参考文档](../api/README.md)
- [故障排查手册](troubleshooting.md)

---

**Last Updated**: 2026-01-21
