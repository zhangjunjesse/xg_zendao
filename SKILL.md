---
name: zentao
version: 1.1.0
description: "公司内网禅道（ZenTao 15.7.1）的读写通道、Bug 与需求管理、权限排查。当需要查看/新建/指派/解决/关闭禅道 Bug，提交或查询研发需求，读写产品、项目、执行、任务，或排查「某人看不到某个产品/项目」「禅道 API 401/404/无权访问/502」时使用。"
---

# 内网禅道 · 通道 · Bug 与需求管理 · 权限排查

> 🔴 本文所有结论均来自在真实实例上的**实测**，不是照禅道官方文档抄的。
> 每个 🔴 标记的坑都真踩过一次。

## 0. 先决条件

本技能配套一个 Python 客户端 `scripts/zentao_api.py`，**优先用它**，不要自己手写请求 ——
绕代理、UTF-8、无权限识别、multipart 附件这些坑它都封好了。

```bash
python scripts/selftest.py          # 装完先跑：验凭证 / 连通 / 读权限 / 网页会话
python scripts/selftest.py --write <产品id>   # 可选：验写链路（建一条 Bug 再删掉）
```

凭证解析顺序：环境变量 → 仓库根 `config.yaml` → `~/.zentao.yaml` → DSH 凭证库
`~/.dsh/.credentials.yaml` 的 `refs.ZENTAO_*`。找不到会报错并告诉你怎么配，**不会静默用默认值**。

🔴 **各人用各人的禅道账号**。禅道把操作记在账号名下，共用账号出事查不清是谁做的。

## 1. 🔴 四个必踩的坑

1. **内网地址必须绕过本机代理**，否则 502 Bad Gateway。
   `urllib.request.build_opener(urllib.request.ProxyHandler({}))`；curl 用 `--noproxy "*"`。
   客户端已内置；自己写请求时别忘。
2. **HTTP 200 不代表成功**。无权限时禅道返回 `200` + 一段 HTML：
   `<script>alert('您无权访问该产品')`。**解析前必须先试 JSON，失败再看原文**
   （客户端用 `ZenTao.denied(data)` 判定）。
3. **404 有两种含义**：「记录不存在」和「有记录但你无权」，**二者不可区分**。
   想分清就请求它的子路径（如 `/products/8/bugs`）：无权限那条会吐出上面那句 alert，
   真不存在的不会。**别把 404 直接读成「没这条记录」** —— 这是最容易得出错误结论的地方。
4. **网页登录表单字段名是 `keepLogin[]`（带方括号）**，密码用**明文**，md5 不认。
   用 `keepLogin` 会静默失败、被打回登录页。

补充：Windows 的 git bash 控制台是 GBK，**中文一律花屏**。别据此判断读写坏了 ——
要验证就在 Python 里比布尔值（`got['title'] == SENT`），或写 UTF-8 文件再看。

## 2. 对象模型（别搞混）

```
项目集(program) ─┬─ 产品线(line) ─── 产品(product) ── 需求(story) / Bug
                 └─ 项目(project) ── 执行(execution/sprint) ── 任务(task)
```

- **Bug 和需求挂在「产品」上**，不是项目上。项目没关联产品时，查它的 bugs/stories 会 404 或回 HTML 报错。
- **任务挂在「执行」上**：`/api.php/v1/executions/{id}/tasks`。
  `/projects/{id}/tasks` 是 **404**（最常见的走错路）。
- 新建的**执行初始为 `wait`**，要「启动」后才能正常派任务。

## 3. Bug 管理（全流程实测通过）

| 动作 | 调用 | 备注 |
|---|---|---|
| 列 Bug | `GET /api.php/v1/products/{pid}/bugs?limit=50` | 返回 `{total, bugs:[...]}` |
| 读单条 | `GET /api.php/v1/bugs/{id}` | |
| 建 Bug | `POST /api.php/v1/products/{pid}/bugs` | 见下方必填项 |
| 改 | `PUT /api.php/v1/bugs/{id}` | 传什么改什么 |
| 解决 | `PUT` body `{'status':'resolved','resolution':'fixed'}` | |
| **关闭** | `PUT` body `{'status':'closed','closedBy':'<账号>'}` | 🔴 只传 `status` **不生效**，会停在 resolved |
| 删除 | `DELETE /api.php/v1/bugs/{id}` | 🔴 **软删**，见下 |

**建 Bug 必填项**：

```python
body = {
  'title': '一句话说清什么情况下什么不对',
  'openedBuild': ['trunk'],   # 🔴 必填！漏了报 400『影响版本』不能为空；没有版本就填 trunk
  'severity': 3,              # 1~4
  'pri': 3,                   # 1~4
  'type': 'codeerror',        # codeerror/config/install/security/performance/standard/designdefect/others
  'assignedTo': zt.account,
  'steps': '<p>[步骤]</p><p>…</p><p>[结果]</p><p>…</p><p>[期望]</p><p>…</p>',
}
st, r = zt.api('/api.php/v1/products/8/bugs', body)   # 成功 http=200，r['id'] 是新 Bug 号
```

**两个反直觉的语义**：

- 🔴 **关闭必须同时传 `closedBy`**。实测 `{'status':'closed'}` → 返回 200 但实际仍是 `resolved`。
  也可以走网页路径 `POST /bug-close-{id}.html`，它会自动填 `closedBy`。客户端封装为 `zt.close_bug(id)`。
- 🔴 **DELETE 是软删除**。删完 `GET /api.php/v1/bugs/{id}` **仍返回 200**，只是 `deleted=True`；
  产品的 Bug 列表里不再出现。**别拿 GET 200 判断「没删掉」**，要看 `deleted` 或看列表 total。

`status`：`active` / `resolved` / `closed`。`resolution` 实测用过 `fixed`；
禅道还有 bydesign/duplicate/external/notrepro/postponed/willnotfix/tostory ——
**这些没逐个实测**，用之前先在测试产品上试一次。
`steps` 存的是 HTML（`<p>…</p>`），读出来当 HTML 处理，别当纯文本。

## 4. 需求（story）管理

| 动作 | 调用 |
|---|---|
| 列需求 | `GET /api.php/v1/products/{pid}/stories?limit=50` |
| 读单条 | `GET /api.php/v1/stories/{id}` |
| 建需求 | `POST /api.php/v1/products/{pid}/stories` |
| 删除 | `DELETE /api.php/v1/stories/{id}`（同样软删，`deleted=1`） |

**跟 Bug 不一样的三点**：

1. 🔴 **必填的是 `category`，不是 `type`**。`type` 是隐藏字段固定 `story`；
   报错文案说的「『类型』不能为空」指的是 **`category`**（值域：
   `feature` 功能 / `interface` 接口 / `performance` 性能 / `safe` 安全 /
   `experience` 体验 / `improve` 改进 / `other` 其他）。这里最容易卡住。
2. 🔴 **新建后是 `status=draft` 草稿、`stage=wait`，不是激活态**（Bug 建出来直接 active）。
   需求要**走评审**才转 `active`：表单有 `reviewer[]`（评审人）和 `needNotReview`（免评审）。
   填了评审人就挂在待评审；要直接激活就带 `needNotReview=1`。**提完记得告诉用户它是草稿**，
   否则用户会以为没提上去。
3. 有 `source` 字段（需求来源：customer/user/po/market/service/operation/support/
   competitor/partner/dev/tester）和 `sourceNote`，Bug 没有。按来源统计很有用。

正文分两栏：`spec`（需求描述）和 `verify`（验收标准），都是 HTML。

```python
body = {'title': '…', 'category': 'feature', 'type': 'story',
        'pri': 2, 'source': 'po', 'sourceNote': '来源可追溯到哪',
        'spec': '<p>[背景]</p>…<p>[期望]</p>…<p>[非目标]</p>…',
        'verify': '<p>1. …</p><p>2. …</p>',
        'reviewer': ['<评审人账号>']}
st, r = zt.api('/api.php/v1/products/8/stories', body)
```

## 5. 附件：REST API 传不了，走 multipart

建 Bug / 建需求要带截图时，**REST API 不支持附件**，必须走网页表单的 multipart 提交：

```python
zt.upload('/bug-create-8-0-moduleID=0.html',
          fields=[('product','8'), ('title','…'), ('openedBuild[]','trunk'),
                  ('severity','3'), ('pri','3'), ('type','codeerror'),
                  ('steps','<p>…</p>'), ('assignedTo', zt.account),
                  ('status','active'), ('uid', uuid.uuid4().hex),
                  # 可选：挂到项目/执行
                  ('project','55'), ('execution','56')],
          files=[('files[]', r'C:\path\to\shot.png')])
# 成功响应里含 alert('保存成功')
```

需求同理，表单是 `/story-create-{pid}.html`，字段见 §4。

**验证附件真的传上去了**：读回对象的 `files` 字段，里面有 `webPath`；
把它下载回来跟本地原图做 MD5 比对 —— **别只看响应说成功**。

## 6. 🔴 权限模型：两层门（最大的坑）

产品可见性**先过分组视野，再过产品自身 ACL**。绝大多数人只知道第二层，改半天没用：

```
① 分组「视野维护」的「可访问产品」白名单        ← 真正的拦路虎
   后台 → 分组 → 视野维护   (URL: /group-manageView-<gid>.html)
   表单字段 actions[products][] / actions[programs][] / actions[projects][] / actions[sprints][]
   下拉框旁写着「空代表没有访问限制」
        ↓ 过了才轮到
② 产品自身 acl(open/private) / PO / QD / RD / whitelist
   (URL: /product-edit-<id>.html)
```

实测结论：

- **受限分组会压过无限制分组**。某人同时属于「受限组 A」和「无限制组 B」，
  仍然只能看到 A 的白名单 —— 不是取并集。
- 第一层没过时，**产品 acl 改成「公开」、把人设成 PO、加进白名单，全都无效**。
- 🔴 **新建产品后，必须去每个受限分组的「视野维护」里把它加上**，否则除超管外谁都看不见。
- 若本来就不想按产品做隔离：把这些分组的「可访问产品」**清空**（= 无限制），以后新建产品不用再管。

### 排查「某人看不到某对象」的标准五步

1. 用**该用户**的 token 列 `/api.php/v1/products`，记下能看到哪些 ID。
2. 用超管列一遍，对出差集。
3. 对被挡的 ID 请求 `/products/<id>/bugs`，看是否吐 `alert('您无权访问该产品')`
   → 确认是「存在但无权」而不是「不存在」。
4. 查该用户属于哪些分组：逐个 `/group-manageMember-<gid>.html`，找 `name='members[]' … checked`。
5. 逐个看这些分组的 `/group-manageView-<gid>.html` 里 `actions[products][]` 的 `selected`
   —— **答案通常在这里**。

### ⚠️ 改分组视野的写法与已知副作用

视野表单有 **176 个勾选项**（`actions[views][*]` 与几百个 `actions[actions][模块][动作]`）。
**只提交下拉框会把它们全部清空**，必须把当前所有 `checked` 项原样带上再提交：

```text
1) 读页面 → 收集所有 checked 的 (name,value) 和 4 个 select 的 selected
2) data = 所有 checked + select 各值（products 里加上新产品 id）+ ('foo','')
3) POST /group-manageView-<gid>.html，成功返回 alert('保存成功')
4) 回读页面核对：勾选项数量差、products 是否含新 id
```

🔴 **已知副作用（禅道自身缺陷，不是调用方写错）**：这样保存后
`actions[actions][case][*]` 这 8 项（测试用例模块的**动态记录**设置）会被服务端丢弃，
换 `testcase` 键名也救不回来，**稳定复现**。它只影响「动态」里显不显示测试用例操作，
**不影响任何功能权限**（功能权限在 `/group-managePriv-<gid>.html`，另一个页面）。
**改之前务必把原页面 HTML 存一份备份**，改完把差异如实报给用户。

## 7. 🔴 写进禅道的文字规范（必须遵守）

禅道是**产品、开发、测试三方共用**的台账。写进去的东西默认会被非本人、非开发的人读到。
**专业、简洁、一目了然**是硬要求，不是建议。

### 七条硬规矩

1. **标题一句话说清「什么场景下什么不对」或「要什么能力」**，控制在 40 字以内。
   不堆修饰词，不加 emoji，不用「！！」。
2. **用界面上的词，不用代码符号当主语**。
   非开发看不懂 `deleteAgent`、`acl=open`、`computeUserView`。
   要提代码位置，放到正文末尾的「参考」里，别放开头。
3. **正文用固定小节，不写流水账**：
   - Bug：`[步骤]` → `[结果]` → `[期望]`，需要时补 `[根因]`、`[影响]`
   - 需求：`[背景]` → `[现状]` → `[期望]` → `[非目标]`，验收写进 `verify` 字段
4. **写事实，不写情绪**。
   ❌「体验极差」「很不方便」「这个设计有问题」
   ✅「凭证生成后无法再查看，丢失只能回收重办」
5. **一条只说一件事**。能拆成两条就拆两条 —— 混在一起会导致改了一半就被关掉。
6. **不贴大段日志/堆栈/代码**。超过 10 行就存成附件，正文只留结论那一两行。
7. **内部代号必须先用人话解释**。
   ❌ 标题写「修复 L46」——除了写的人没人知道 L46 是什么
   ✅ 标题说清是什么，正文里再注明「对应遗留问题 L46」

### 一个对照例子

❌ **反面**（真实反例改写）：

> 标题：资产bug
> 正文：demo遗漏了资产-Agent中，对Agent的管理功能，目前只有详情，还应该有删除功能；
> 修改demo，修改bug；另外编辑的时候流式和可用模型这两个属性去掉

问题：标题无信息量；正文混了两件事；没有复现步骤；没写期望是什么；「流式」为什么去掉没说。

✅ **正面**：

> 标题：Agent 列表缺少删除入口；详情编辑弹窗多出「流式」「可用模型」两项
>
> [步骤] 资产管理 → Agent → 已注册，查看「操作」列；再点「详情」→「编辑」
> [结果] 1. 操作列只有「详情」，无法删除 Agent。
>        2. 编辑弹窗出现「流式」和「可用模型」，其中「可用模型」与访问护栏的模型规则重复。
> [期望] 1. 操作列提供「删除」，二次确认需说明会连带删除绑定凭证且不可恢复。
>        2. 编辑弹窗移除这两项 —— 流式是运行时观测结果不是可配置项；模型权限由访问护栏统一管。
> [参考] 后端删除接口已具备；前端提交 67811cd；关联台账 ISS-026。

（若两件事的负责人或修复节奏不同，按规矩 5 应拆成两条。）

### 格式约束

- 禅道富文本存的是 HTML：换行用 `<p>…</p>`，**不认 Markdown**。
  写 `- 列表`、`**加粗**`、`## 标题` 会原样显示成字符。
- 中文标点用全角，英文与数字两侧留空格。
- 附件名要能自解释：`bug-before.png` / `bug-after.png`，不要 `1.png`、`微信截图_2026.png`。

## 8. 写操作纪律

- 🔴 **写之前把内容复述给用户确认**（标题、落到哪个产品、指派给谁），不闷头写。
- 🔴 **别在别人的真实产品里做写探针** —— 禅道会给相关人发通知。
  要验证写链路，用自己的、干净的产品，建完立刻删（`selftest.py --write` 就是这么做的）。
- 🔴 **提完自己读回来验一遍**：列表能查到、字段与提交值一致、附件下载回来 MD5 与原图一致。
  **不要只看响应里的「保存成功」就报完成。**
- 提 Bug 还是提需求：「本来就该有但没有 / 做错了 / 报错了」→ **Bug**；
  「现在没有，想加 / 能不能更好」→ **需求**。

## 9. 排障速查

| 现象 | 原因 | 处置 |
|---|---|---|
| 502 Bad Gateway | 本机代理拦内网 | `ProxyHandler({})` / `--noproxy "*"` |
| 网页登录被打回登录页 | 用了 `keepLogin` 而非 `keepLogin[]`，或用了 md5 密码 | 见 §1.4 |
| 200 但返回 HTML `alert('您无权访问该产品')` | 无权限 | 走 §6 排查五步 |
| 对象 404 | 不存在 **或** 无权限（不可区分） | 请求其子路径逼出真实错误 |
| 建 Bug 400『影响版本』不能为空 | 少 `openedBuild` | 填 `['trunk']` |
| 建需求 400『类型』不能为空 | 少 `category`（不是 `type`） | 填 `feature` 等 |
| 需求提完不见于「激活」列表 | 新建是 `draft` 草稿，要评审 | 评审通过，或建时带 `needNotReview=1` |
| PUT 关闭 Bug 后仍是 resolved | 少 `closedBy` | 补上，或走 `/bug-close-{id}.html` |
| DELETE 后 GET 仍 200 | 软删除 | 看 `deleted` 字段或列表 total |
| `/projects/{id}/tasks` 404 | 任务不挂项目 | 用 `/executions/{id}/tasks` |
| 项目查 bugs/stories 报错 | 项目没关联产品 | 先在项目里关联产品 |
| 中文回显乱码 | Windows git bash 控制台 GBK | 写 UTF-8 文件再读，或只打印布尔值 |

## 10. 本站点当前数据（会变，用前先查）

> ⚠️ 下面是写文档当天（2026-09-10）的实测快照，**产品/项目 ID 会随时间变化**。
> 用 `zt.products()` 或 `python scripts/selftest.py` 现查，别把这些 ID 当常量写进代码。

ASG（Agent 安全网关）在禅道里的坐标：产品 **8**（代号 `Asg`）、项目 **55**、执行 **56**。
