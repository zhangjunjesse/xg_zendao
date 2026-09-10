# xg_zendao —— 禅道 AI 技能

给 AI 编码助手（DSH / Claude Code 等）用的**禅道操作技能**：让 AI 能直接读写公司内网禅道的
Bug、需求、产品、项目，并能排查「某人看不到某个产品」这类权限问题。

配套一个可直接调用的 Python 客户端，人也能用。

> ⚠️ **本仓库不含任何凭证，也不写死内网地址** —— 地址与账号一律由使用者本地配置。
> 提 issue / PR 时请勿粘贴内网地址、账号密码、或包含真实数据的截图。

## 这个技能解决什么

禅道的 API 有一堆**反直觉的地方**，不知道就会卡住甚至得出错误结论。本技能把它们全部实测并固化：

- 内网地址不绕代理会 **502**
- 无权限时返回 **HTTP 200 + 一段 HTML `alert('您无权访问该产品')`**，状态码骗人
- **404 同时表示「不存在」和「没权限」**，不可区分 —— 最容易得出错误结论的地方
- 建 Bug 必填 `openedBuild`；建需求必填的是 `category` 而不是 `type`
- 关闭 Bug **只传 `status` 不生效**，必须同时带 `closedBy`
- DELETE 是**软删除**，删完 GET 仍返回 200
- 产品可见性有**两层门**：分组「视野维护」白名单 → 产品自身 ACL，
  第一层不过时，改产品 ACL 完全无效

## 安装

### 1. 拿到代码

```bash
git clone https://github.com/zhangjunjesse/xg_zendao.git
cd xg_zendao
```

### 2. 配置你自己的禅道账号（三选一）

🔴 **用你自己的账号，不要共用别人的** —— 禅道把操作记在账号名下，共用出了事查不清是谁做的。

**方式 A：配置文件（推荐）**

```bash
cp config.example.yaml config.yaml
# 编辑 config.yaml 填账号密码。config.yaml 已在 .gitignore 里，不会被提交。
```

**方式 B：环境变量**

```bash
export ZENTAO_BASE_URL=http://your-zentao-host/zentao   # 内网禅道地址，问同事要
export ZENTAO_ACCOUNT=your_account
export ZENTAO_PASSWORD=your_password
```

**方式 C：DSH 用户** —— 在 `~/.dsh/.credentials.yaml` 的 `refs:` 下加：

```yaml
refs:
  ZENTAO_BASE_URL: http://your-zentao-host/zentao
  ZENTAO_ACCOUNT: your_account
  ZENTAO_PASSWORD: your_password
```

### 3. 自检（装完必跑）

```bash
python scripts/selftest.py
```

全绿说明凭证、网络、读权限、网页会话都正常。想连写链路一起验：

```bash
python scripts/selftest.py --write <你有权限的产品id>   # 建一条 Bug 再立刻删掉
```

自检失败时会直接告诉你原因（凭证没配 / 502 代理 / 一个产品都看不到 = 分组视野问题）。

### 4. 装成 AI 技能

把 `SKILL.md` 放到你的助手的技能目录，目录名用 `zentao`：

| 工具 | 放这里 |
|---|---|
| DSH | `~/.dsh/skills/zentao/SKILL.md` |
| Claude Code | `~/.claude/skills/zentao/SKILL.md` |

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force "$HOME\.dsh\skills\zentao"
Copy-Item SKILL.md "$HOME\.dsh\skills\zentao\SKILL.md"
```

macOS / Linux：

```bash
mkdir -p ~/.dsh/skills/zentao && cp SKILL.md ~/.dsh/skills/zentao/SKILL.md
```

装好后跟助手说「看看禅道上有哪些 Bug」「帮我提个需求」就会自动加载。

> 技能里引用了 `scripts/zentao_api.py`，把本仓库留在本地即可（技能会让助手按路径调用）。
> 也可以 `pip install pyyaml` 让配置解析更稳（没装也能跑，脚本内置了极简 YAML 解析）。

## 直接当 Python 库用

```python
import sys; sys.path.insert(0, 'scripts')
from zentao_api import ZenTao

zt = ZenTao()
print(zt.whoami()['account'])

for p in zt.products():
    print(p['id'], p['name'])

print(zt.bugs(8)['total'])          # 产品 8 的 Bug 数
print(zt.get_bug(4400)['title'])    # 读单条

# 建 Bug（openedBuild 必填）
st, r = zt.api('/api.php/v1/products/8/bugs', {
    'title': '示例缺陷', 'openedBuild': ['trunk'],
    'severity': 3, 'pri': 3, 'type': 'codeerror',
    'steps': '<p>[步骤]</p><p>…</p>', 'assignedTo': zt.account})

zt.close_bug(r['id'])               # 关闭（内部已带 closedBy）
```

带截图提 Bug 用 `zt.upload(...)`，见 `SKILL.md` §5。

## 仓库结构

```
SKILL.md              技能主体 —— AI 读它
README.md             本文 —— 人读它
config.example.yaml   凭证模板（复制成 config.yaml 用）
.gitignore            已屏蔽 config.yaml 等本地凭证
scripts/
  zentao_api.py       Python 客户端（绕代理 / UTF-8 / 无权限识别 / multipart 附件）
  selftest.py         一键自检
```

## 安全约定

- 🔴 **密码绝不进 git**。`config.yaml` / `.zentao.yaml` / `.env` 已在 `.gitignore`。
- 🔴 **各人用各人的账号**，不共用、不把超管账号写进配置文件。
- 🔴 **写操作先复述再执行**，别在别人的真实产品里做测试 —— 禅道会给相关人发通知。
- 🔴 **提完自己读回来验一遍**，不要只看响应里的「保存成功」。

## 已知问题

- 改分组「视野维护」并保存后，`actions[actions][case][*]` 这 8 个勾选项会被服务端丢弃
  （禅道 15.7.1 自身缺陷，稳定复现）。只影响「动态」是否显示测试用例操作，
  **不影响功能权限**。改前请备份原页面。详见 `SKILL.md` §6。
