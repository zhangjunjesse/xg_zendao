#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键自检：装完先跑这个，确认凭证、网络、读权限、写通道都正常。

用法：
    python scripts/selftest.py            # 只读自检（安全，零副作用）
    python scripts/selftest.py --write 8  # 额外验证写链路：在产品 8 建一条 Bug 再立刻删掉

输出一律 ASCII 友好，避免 Windows GBK 控制台把中文显示成乱码而误判失败。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zentao_api import ZenTao, CredentialError  # noqa: E402

OK, BAD = '[ OK ]', '[FAIL]'
fails = []


def check(name, cond, detail=''):
    print('%s %-46s %s' % (OK if cond else BAD, name, detail))
    if not cond:
        fails.append(name)
    return cond


def main():
    print('=' * 74)
    print('ZenTao skill self-test')
    print('=' * 74)

    # 1. 凭证
    try:
        zt = ZenTao()
    except CredentialError as e:
        print(BAD + ' credentials')
        print(str(e))
        return 1
    check('credentials resolved', True, 'base=%s account=%s' % (zt.base, zt.account))

    # 2. 连通 + 认证（顺带验证「必须绕过代理」这一条）
    try:
        tok = zt.token
        check('REST token obtained', len(tok) > 10, 'len=%d' % len(tok))
    except Exception as e:
        check('REST token obtained', False, str(e)[:160])
        if '502' in str(e):
            print('       -> 502 通常是本机代理拦了内网地址；本客户端已内置绕代理，'
                  '若仍 502 请检查公司网络策略。')
        return 1

    # 3. 身份
    me = zt.whoami()
    check('identity readable', bool(me.get('account')),
          'account=%s role=%s' % (me.get('account'), (me.get('role') or {}).get('code')))

    # 4. 读产品
    prods = zt.products()
    check('product list readable', isinstance(prods, list), 'visible=%d' % len(prods))
    for p in prods:
        print('         - id=%-4s %s' % (p['id'], p['name']))
    if not prods:
        print('       -> 一个产品都看不到，多半是分组「视野维护」的可访问产品白名单没包含你。'
              '见 SKILL.md 权限章节。')

    # 5. 读 Bug / 需求（拿第一个可见产品试）
    if prods:
        pid = prods[0]['id']
        b = zt.bugs(pid, limit=1)
        s = zt.stories(pid, limit=1)
        check('bugs readable', 'total' in b, 'product %s total=%s' % (pid, b.get('total')))
        check('stories readable', 'total' in s, 'product %s total=%s' % (pid, s.get('total')))

    # 6. 网页会话（关闭 Bug、改视野、传附件都依赖它）
    try:
        st, html = zt.web('/my.html')
        check('web session usable', len(html) > 3000, 'http=%s len=%d' % (st, len(html)))
    except Exception as e:
        check('web session usable', False, str(e)[:160])

    # 7. 无权限探测形态（确认调用方懂得区分 404 与「无权」）
    if prods:
        missing = max(int(p['id']) for p in prods) + 900
        st, d = zt.api('/api.php/v1/products/%d' % missing)
        check('missing-object returns 404', st == 404, 'probe id=%d http=%s' % (missing, st))

    # 8. 可选写链路
    if '--write' in sys.argv:
        i = sys.argv.index('--write')
        pid = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        if not pid:
            print(BAD + ' --write 需要跟一个产品 id，例如 --write 8')
            fails.append('write arg')
        else:
            print('-' * 74)
            print('write test on product %s (creates a bug then deletes it)' % pid)
            body = {'title': '[selftest] channel write check - will be deleted',
                    'openedBuild': ['trunk'],   # 必填，漏了报 400
                    'severity': 3, 'pri': 3, 'type': 'codeerror',
                    'steps': 'self-test probe, deleted immediately',
                    'assignedTo': zt.account}
            st, r = zt.api('/api.php/v1/products/%s/bugs' % pid, body)
            bid = r.get('id') if isinstance(r, dict) else None
            if not check('create bug', bool(bid), 'http=%s %s' % (st, '' if bid else str(r)[:150])):
                pass
            else:
                got = zt.get_bug(bid)
                check('read back bug', got.get('title') == body['title'], 'id=%s' % bid)
                st2, _ = zt.api('/api.php/v1/bugs/%s' % bid, method='DELETE')
                check('delete bug', st2 == 200, 'http=%s' % st2)
                after = zt.bugs(pid, limit=1)
                check('cleanup verified', str(bid) not in str(after.get('bugs', [])),
                      'product total=%s' % after.get('total'))

    print('=' * 74)
    if fails:
        print('RESULT: FAIL (%d) -> %s' % (len(fails), ', '.join(fails)))
        return 1
    print('RESULT: ALL PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
