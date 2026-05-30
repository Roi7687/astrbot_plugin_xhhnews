"""小黑盒 API 签名工具（hkey/nonce 生成）。

基于 https://blog.sakurasen.cn/post/1778064732895/ 的逆向分析。
"""

import hashlib
import random
import time

KEY = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def _av(e: str, t: str, n: int) -> str:
    i = t[:n]
    return "".join(i[ord(c) % len(i)] for c in e)


def _sv(e: str, t: str) -> str:
    return "".join(t[ord(c) % len(t)] for c in e)


def _interleave(strs: list[str]) -> str:
    s = ""
    mx = max(len(x) for x in strs)
    for i in range(mx):
        for x in strs:
            if i < len(x):
                s += x[i]
    return s


def _Vm(e: int) -> int:
    return ((e << 1) ^ 27) & 0xFF if e & 128 else (e << 1) & 0xFF


def _qm(e: int) -> int:
    return _Vm(e) ^ e


def _Dm(e: int) -> int:
    return _qm(_Vm(e))


def _Ym(e: int) -> int:
    return _Dm(_qm(_Vm(e)))


def _Gm(e: int) -> int:
    return _Ym(e) ^ _Dm(e) ^ _qm(e)


def _Km(e: list[int]) -> list[int]:
    """GF(2^8) 矩阵混淆，原地修改 e 的前 4 位并返回 e。"""
    t = [0] * 4
    t[0] = _Gm(e[0]) ^ _Ym(e[1]) ^ _Dm(e[2]) ^ _qm(e[3])
    t[1] = _qm(e[0]) ^ _Gm(e[1]) ^ _Ym(e[2]) ^ _Dm(e[3])
    t[2] = _Dm(e[0]) ^ _qm(e[1]) ^ _Gm(e[2]) ^ _Ym(e[3])
    t[3] = _Ym(e[0]) ^ _Dm(e[1]) ^ _qm(e[2]) ^ _Gm(e[3])
    e[0], e[1], e[2], e[3] = t[0], t[1], t[2], t[3]
    return e


def create_hkey(path: str, t: int, nonce: str) -> str:
    """生成 hkey。

    Args:
        path: API 路径，如 "/bbs/app/api/search/topic"
        t: 时间戳（秒），注意实际使用 t+1
        nonce: 大写 MD5 随机数
    """
    path = "/" + "/".join(p for p in path.split("/") if p) + "/"
    str1 = _av(str(t), KEY, -2)
    str2 = _sv(path, KEY)
    str3 = _sv(nonce, KEY)
    ns = _interleave([str1, str2, str3])
    h = _md5(ns[:20])
    last6 = [ord(c) for c in h[-6:]]
    mixed = _Km(last6)
    a = str(sum(mixed) % 100).zfill(2)
    s = _av(h[:5], KEY, -4)
    return s + a


def generate_sign_params(path: str) -> dict:
    """生成完整的 API 签名参数。

    Returns: {"hkey": ..., "_time": ..., "nonce": ..., 以及其他公共参数}
    """
    t = int(time.time())
    nonce = _md5(str(t) + str(random.random())).upper()
    hkey = create_hkey(path, t + 1, nonce)
    return {
        "os_type": "web",
        "app": "heybox",
        "client_type": "mobile",
        "version": "999.0.4",
        "x_client_type": "web",
        "x_os_type": "Windows",
        "x_app": "heybox",
        "heybox_id": "-1",
        "hkey": hkey,
        "_time": str(t),
        "nonce": nonce,
    }
