#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禅道 API 客户端 —— 可移植版，任何同事装上就能用。

设计要点（每条都对应一个实测踩过的坑）：
  1. 内网地址必须绕过本机代理，否则 502 Bad Gateway；
  2. 禅道无权限时返回 HTTP 200 + 一段 HTML `alert('您无权访问该产品')`，
     所以不能拿状态码判成功，必须先试 JSON 解析、失败再看原文；
  3. 中文必须 ensure_ascii=False + UTF-8 编码提交，走 shell 的 curl 会被 mangle；
  4. 网页登录表单字段名是 keepLogin[]（带方括号），密码用明文，md5 不认。

凭证解析顺序（先到先用，方便不同环境）：
  ① 环境变量 ZENTAO_BASE_URL / ZENTAO_ACCOUNT / ZENTAO_PASSWORD
  ② 仓库根目录 config.yaml
  ③ ~/.zentao.yaml
  ④ DSH 凭证库 ~/.dsh/.credentials.yaml 的 refs.ZENTAO_*
都取不到就抛错并打印怎么配，绝不静默用默认值。
"""

import json
import os
import io
import uuid
import urllib.request
import urllib.parse
import urllib.error
import http.cookiejar

__all__ = ['ZenTao', 'load_credentials', 'CredentialError']

_KEYS = ('ZENTAO_BASE_URL', 'ZENTAO_ACCOUNT', 'ZENTAO_PASSWORD')


class CredentialError(RuntimeError):
    pass


def _read_yaml(path):
    """只在文件存在时读；没装 pyyaml 就退化成极简解析，避免为一个配置文件加依赖。"""
    if not path or not os.path.exists(path):
        return {}
    text = io.open(path, encoding='utf-8').read()
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        out, stack = {}, [(-1, out)]
        for raw in text.splitlines():
            if not raw.strip() or raw.lstrip().startswith('#'):
                continue
            indent = len(raw) - len(raw.lstrip())
            key, _, val = raw.strip().partition(':')
            val = val.strip()
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1] if stack else out
            if val == '':
                node = {}
                parent[key] = node
                stack.append((indent, node))
            else:
                parent[key] = val.strip('"\'')
        return out


def load_credentials(explicit=None):
    """返回 dict(base_url, account, password)。找不到就抛 CredentialError，并说明怎么配。"""
    if explicit:
        return explicit

    # ① 环境变量
    if all(os.environ.get(k) for k in _KEYS):
        return {'base_url': os.environ['ZENTAO_BASE_URL'].rstrip('/'),
                'account': os.environ['ZENTAO_ACCOUNT'],
                'password': os.environ['ZENTAO_PASSWORD']}

    # ② 仓库根 config.yaml  ③ ~/.zentao.yaml  ④ DSH 凭证库
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        (os.path.join(here, 'config.yaml'), lambda d: d.get('zentao', d)),
        (os.path.expanduser('~/.zentao.yaml'), lambda d: d.get('zentao', d)),
        (os.path.expanduser('~/.dsh/.credentials.yaml'), lambda d: d.get('refs', {})),
    ]
    for path, pick in candidates:
        data = pick(_read_yaml(path))
        if not data:
            continue
        base = data.get('ZENTAO_BASE_URL') or data.get('base_url')
        acc = data.get('ZENTAO_ACCOUNT') or data.get('account')
        pwd = data.get('ZENTAO_PASSWORD') or data.get('password')
        if base and acc and pwd:
            return {'base_url': str(base).rstrip('/'), 'account': str(acc), 'password': str(pwd)}

    raise CredentialError(
        '未找到禅道凭证。任选一种配置方式：\n'
        '  1) 环境变量：ZENTAO_BASE_URL / ZENTAO_ACCOUNT / ZENTAO_PASSWORD\n'
        '  2) 仓库根目录建 config.yaml（复制 config.example.yaml 改），或 ~/.zentao.yaml\n'
        '  3) DSH 用户：在 ~/.dsh/.credentials.yaml 的 refs: 下加 ZENTAO_BASE_URL / '
        'ZENTAO_ACCOUNT / ZENTAO_PASSWORD\n'
        '注意：配置文件已在 .gitignore 里，别把密码提交上去。'
    )


class ZenTao(object):
    """禅道客户端。REST API 走 .api()；API 覆盖不到的（关闭 Bug、改分组视野、传附件）走 .web()。"""

    def __init__(self, creds=None, timeout=30):
        c = load_credentials(creds)
        self.base = c['base_url']
        self.account = c['account']
        self._password = c['password']
        self.timeout = timeout
        # 🔴 ProxyHandler({}) = 绕过本机代理，内网地址不绕会 502
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._cj = http.cookiejar.CookieJar()
        self._web = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(self._cj))
        self._token = None
        self._logged_in = False

    # ── REST API ────────────────────────────────────────────────
    @property
    def token(self):
        if self._token is None:
            st, data = self._raw('/api.php/v1/tokens',
                                 {'account': self.account, 'password': self._password})
            if not isinstance(data, dict) or 'token' not in data:
                raise RuntimeError('禅道取 token 失败 http=%s resp=%s' % (st, str(data)[:200]))
            self._token = data['token']
        return self._token

    def _raw(self, path, payload=None, method=None, token=None):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload else None
        req = urllib.request.Request(self.base + path, data=body,
                                     method=method or ('POST' if body else 'GET'))
        req.add_header('User-Agent', 'Mozilla/5.0')
        if body:
            req.add_header('Content-Type', 'application/json; charset=utf-8')
        if token:
            req.add_header('Token', token)
        try:
            with self._opener.open(req, timeout=self.timeout) as r:
                text = r.read().decode('utf-8', 'replace')
                status = r.status
        except urllib.error.HTTPError as e:
            return e.code, {'__err__': e.read().decode('utf-8', 'replace')[:400]}
        if not text.strip():
            return status, None
        try:
            return status, json.loads(text)
        except ValueError:
            # 🔴 200 也可能是 HTML：无权限时禅道回 alert('您无权访问该产品')
            return status, {'__html__': text[:400]}

    def api(self, path, payload=None, method=None):
        """调 REST API。返回 (status, data)。data 里若有 __err__/__html__ 说明不是正常 JSON。"""
        return self._raw(path, payload, method, token=self.token)

    @staticmethod
    def denied(data):
        """判断返回是不是「无权访问」——这是禅道最迷惑的一种失败：HTTP 200 + HTML。"""
        blob = str(data)
        return ('无权访问' in blob) or ('无权限' in blob)

    # ── 网页会话 ────────────────────────────────────────────────
    def web(self, path, data=None, referer='/'):
        """走网页会话（自动登录一次）。data 为 dict 时按表单编码提交。返回 (status, html)。"""
        if not self._logged_in:
            self._weblogin()
        return self._web_raw(path, data, referer)

    def _web_raw(self, path, data=None, referer='/'):
        body = urllib.parse.urlencode(data, doseq=True).encode() if data else None
        req = urllib.request.Request(self.base + path, data=body)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120')
        req.add_header('Referer', self.base + referer)
        if body:
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        try:
            with self._web.open(req, timeout=self.timeout) as r:
                return r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'replace')

    def _weblogin(self):
        self._web_raw('/user-login.html')
        # 🔴 字段名是 keepLogin[]（带方括号），密码明文；用 keepLogin 会静默失败
        self._web_raw('/user-login.html',
                      {'account': self.account, 'password': self._password,
                       'keepLogin[]': 'on', 'referer': '/zentao/'},
                      referer='/user-login.html')
        st, html = self._web_raw('/my.html')
        if len(html) < 3000:
            raise RuntimeError('禅道网页登录失败（被打回登录页）。检查账号密码，或该站点是否启用了验证码。')
        self._logged_in = True

    def upload(self, path, fields, files, referer=None):
        """multipart 提交（建 Bug / 建需求带附件必须走这条，REST API 不支持传附件）。
        fields: [(name, value)]   files: [(name, 本地路径)]"""
        if not self._logged_in:
            self._weblogin()
        boundary = '----ZT' + uuid.uuid4().hex
        buf = io.BytesIO()

        def w(s):
            buf.write(s.encode('utf-8') if isinstance(s, str) else s)

        for k, v in fields:
            w('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n' % (boundary, k))
            w(v if isinstance(v, str) else str(v))
            w('\r\n')
        for k, p in files:
            name = os.path.basename(p)
            ext = name.rsplit('.', 1)[-1].lower()
            mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
                    'gif': 'image/gif', 'pdf': 'application/pdf'}.get(ext, 'application/octet-stream')
            w('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
              'Content-Type: %s\r\n\r\n' % (boundary, k, name, mime))
            w(open(p, 'rb').read())
            w('\r\n')
        w('--%s--\r\n' % boundary)

        req = urllib.request.Request(self.base + path, data=buf.getvalue())
        req.add_header('Content-Type', 'multipart/form-data; boundary=' + boundary)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120')
        req.add_header('Referer', self.base + (referer or path))
        try:
            with self._web.open(req, timeout=max(self.timeout, 90)) as r:
                return r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'replace')

    # ── 常用封装 ────────────────────────────────────────────────
    def products(self):
        _, d = self.api('/api.php/v1/products?limit=200')
        return (d or {}).get('products', [])

    def bugs(self, product_id, limit=50):
        _, d = self.api('/api.php/v1/products/%s/bugs?limit=%s' % (product_id, limit))
        return d or {}

    def stories(self, product_id, limit=50):
        _, d = self.api('/api.php/v1/products/%s/stories?limit=%s' % (product_id, limit))
        return d or {}

    def get_bug(self, bug_id):
        return self.api('/api.php/v1/bugs/%s' % bug_id)[1]

    def get_story(self, story_id):
        return self.api('/api.php/v1/stories/%s' % story_id)[1]

    def close_bug(self, bug_id, comment=''):
        """🔴 只传 status='closed' 不生效（会停在 resolved），必须带 closedBy。"""
        return self.api('/api.php/v1/bugs/%s' % bug_id,
                        {'status': 'closed', 'closedBy': self.account}, method='PUT')

    def whoami(self):
        return (self.api('/api.php/v1/user')[1] or {}).get('profile', {})
