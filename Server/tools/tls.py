import ssl
from typing import Optional

from config.settings import global_settings


def build_ssl_context(
    certfile: Optional[str] = None,
    keyfile: Optional[str] = None,
    cafile: Optional[str] = None,
    ciphers: Optional[str] = None,
    ecdh_curves: Optional[str] = None,
) -> Optional[ssl.SSLContext]:
    """
    构建 WebSocket TLS (WSS) 所需的 SSLContext。

    说明：Python 使用系统的 OpenSSL/Provider（如已在系统启用 KAE Engine/Provider，
    这里无需改代码即可复用加速能力）。
    """
    certfile = certfile or global_settings.TLS_CERT_FILE
    keyfile = keyfile or global_settings.TLS_KEY_FILE
    cafile = cafile or global_settings.TLS_CA_FILE
    ciphers = ciphers or global_settings.TLS_CIPHERS
    ecdh_curves = ecdh_curves or global_settings.TLS_ECDH_CURVES

    if not (certfile and keyfile):
        return None

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)

    # 客户端证书校验（可选）
    if cafile:
        ctx.load_verify_locations(cafile=cafile)
        ctx.verify_mode = ssl.CERT_REQUIRED

    # 推荐设置
    ctx.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
    ctx.options |= ssl.OP_NO_COMPRESSION
    ctx.set_ecdh_curve(ecdh_curves)
    if ciphers:
        try:
            ctx.set_ciphers(ciphers)
        except Exception:
            # 某些 OpenSSL 构建不支持自定义 cipher 列表，忽略
            pass

    # 启用 Session 缓存以减少握手
    ctx.session_cache_mode = ssl.SESS_CACHE_SERVER

    return ctx
