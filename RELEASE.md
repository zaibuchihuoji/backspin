# 发布清单(从零到 PyPI)

本文是维护者发布手册,按顺序执行即可完成首次公开发布。

## 第 0 步:准备账号(一次性)

1. **PyPI 账号**:在 https://pypi.org/account/register/ 注册。
2. **API Token**:注册后进入 Account Settings → API tokens,创建一个
   token(范围先选 "Entire account",之后可收紧到 project)。
3. **GitHub 仓库**:在 GitHub 上创建空仓库(建议名 `backspin`,描述:
   `The flight recorder for AI agents — record, replay, diff & debug
   agent runs, 100% local.`),勾选 topics:`llm` `agents` `debugging`
   `observability` `openai` `anthropic` `record-replay`。

## 第 1 步:构建发布包(本机已完成过,可随时重跑)

```bash
cd D:\opencode-sessions\agent-debug&back
.venv\Scripts\activate
pip install -q build
python -m build          # 生成 dist/backspin-<版本>.tar.gz 和 .whl
```

检查产物:解压 wheel 确认 `backspin/ui/`、`backspin/py.typed` 都在
(历史上验证过,改动打包配置后要重查)。

## 第 2 步:上传到 PyPI

```bash
pip install -q twine
python -m twine upload dist/* -u __token__ -p <你的PyPI Token>
```

上传成功后到 https://pypi.org/project/backspin/ 确认 README 渲染正常。
**注意**:PyPI 上传后同名版本无法覆盖,发错了就升版本号重发。

## 第 3 步:推送 GitHub

```bash
git remote add origin git@github.com:<你的用户名>/backspin.git
git push -u origin main
```

推送后 GitHub Actions(.github/workflows/ci.yml)会自动在
Linux/macOS/Windows × Python 3.9–3.12 上跑全部测试。
仓库首页设置:About 填描述 + 网站(以后指向文档站),上传一张
`docs/ui-timeline.png` 作为 Social preview。

## 第 4 步:首发宣传(建议顺序)

1. **掘金/V2EX**(中文首发):标题方向
   「给 AI Agent 装了个行车记录仪:录制、离线回放、精确定位哪一步开始跑偏」。
   重点演示 proxy 零代码接入 + `backspin ui` 中文界面 + what-if 分支。
2. **Show HN**:标题 `Show HN: Backspin – Record, replay and diff AI agent runs, 100% local`。
   第一条评论自己补:动机(rr 类比)、与 Langfuse 等的区别(调试器 vs 仪表盘)、
   路线图。
3. **动图**:用 `asciinema`/截图工具录一段 30 秒演示(录制 → ui → diff),
   放 README 首屏。

## 日常发版流程(后续版本)

1. 改代码,补测试,`pytest` 全绿(TypeScript 侧:`npm test`)。
2. 更新 `CHANGELOG.md`。
3. 升 `pyproject.toml` / `backspin/__init__.py` / `sdks/typescript/package.json` 版本号。
4. `python -m build && python -m twine upload dist/*`。
5. `git commit && git push && git tag v<版本> && git push --tags`。

## 当前状态速查

- 代码:0.5.0,107 Python 测试 + 6 TypeScript 测试全绿
- PyPI 名 `backspin`:空闲(2026-08-29 验证)
- npm 包名 `@backspin/sdk`(scoped,发布需 npm 账号,可选)
