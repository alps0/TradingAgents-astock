#!/usr/bin/env python3
"""TradingAgents-Astock 授权证书制作工具。

用法::

    # 1. 在目标服务器上导出硬件指纹
    python tool/make_license.py export-fp --output fingerprint.json

    # 2. 使用指纹签发证书（需私钥，仅签发方持有）
    python tool/make_license.py make \
        --fingerprint <SHA256指纹> \
        --type professional \
        --valid-days 365 \
        --customer "客户名称" \
        --issuer "TradingAgents" \
        --output license.json




python tool/make_license.py make \
        --fingerprint 4e1ee61a6bdbbc67381666d7bc841a8e145feef893cc196bf99ef1770d7e8c9f \
        --type professional \
        --valid-days 181 \
        --customer "客户名称" \
        --issuer "TradingAgents" \
        --output license-wsldocker.json

    # 3. 从指纹文件签发
    python tool/make_license.py make \
        --fingerprint-file fingerprint.json \
        --type professional \
        --valid-days 180 \
        --output license.json

    # 4. 验证证书（使用打包的公钥）
    python tool/make_license.py verify license.json

    # 5. 生成 RSA 密钥对
    python tool/make_license.py gen-keys

密钥管理::

    首次运行会自动生成 RSA 密钥对:
        tool/keys/private_key.pem — 签发用（保密，请勿提交到 git）
        tradingagents/data/keys/public_key.pem — 验证用（部署到运行环境）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Project root: tool/ is one level below the root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Private keys live alongside the tool (gitignored)
TOOL_DIR = Path(__file__).parent
KEYS_DIR = TOOL_DIR / "keys"
PRIVATE_KEY_PATH = KEYS_DIR / "private_key.pem"

# Public key bundled with the package for verification
PUBLIC_KEY_PATH = PROJECT_ROOT / "tradingagents" / "data" / "keys" / "public_key.pem"

# Reuse the same feature catalog as the runtime service
from tradingagents.license_service import LICENSED_FEATURES  # noqa: E402

LICENSE_TYPES: dict[str, dict[str, int | list[str]]] = {
    "standard": {"max_agents": 4, "features": LICENSED_FEATURES},
    "professional": {"max_agents": 7, "features": LICENSED_FEATURES},
    "enterprise": {"max_agents": 7, "features": LICENSED_FEATURES},
}


def ensure_keys() -> None:
    """Generate an RSA key pair if either file is missing.

    The private key stays in ``tool/keys/`` (gitignored).
    The public key is written to ``tradingagents/data/keys/`` so it ships
    with the package and is available at runtime for verification.
    """
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)

    if PRIVATE_KEY_PATH.exists() and PUBLIC_KEY_PATH.exists():
        return

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    PRIVATE_KEY_PATH.write_bytes(private_pem)
    try:
        PRIVATE_KEY_PATH.chmod(0o600)
    except PermissionError:
        pass

    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    PUBLIC_KEY_PATH.write_bytes(public_pem)

    print(f"RSA 密钥对已生成:")
    print(f"  私钥: {PRIVATE_KEY_PATH} (签发用，请保密)")
    print(f"  公钥: {PUBLIC_KEY_PATH} (验证用，已写入 package data)")


def sign_certificate(cert_data: dict) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    if not PRIVATE_KEY_PATH.exists():
        print(f"错误: 私钥不存在 ({PRIVATE_KEY_PATH})，请先运行 `gen-keys`")
        sys.exit(1)

    private_pem = PRIVATE_KEY_PATH.read_bytes()
    private_key = serialization.load_pem_private_key(private_pem, password=None)

    message = json.dumps(cert_data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return signature.hex()


def verify_certificate(cert_data: dict) -> bool:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    if not PUBLIC_KEY_PATH.exists():
        print(f"错误: 公钥文件不存在 ({PUBLIC_KEY_PATH})，无法验证")
        return False

    public_pem = PUBLIC_KEY_PATH.read_bytes()
    public_key = serialization.load_pem_public_key(public_pem)

    signature_hex = cert_data.pop("signature", None)
    if not signature_hex:
        print("错误: 证书中无签名")
        return False

    signature = bytes.fromhex(signature_hex)
    message = json.dumps(cert_data, sort_keys=True, ensure_ascii=False).encode("utf-8")

    try:
        public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception as exc:
        print(f"验证失败: {exc}")
        return False


def export_fingerprint(output_path: str) -> None:
    from tradingagents.license_service import license_service

    fp = license_service.export_fingerprint(output_path)
    print(f"硬件指纹: {fp}")
    print(f"已导出到: {output_path}")


def make_license(
    fingerprint: str,
    license_type: str,
    valid_days: int,
    customer: str,
    issuer: str,
    output_path: str,
) -> None:
    ensure_keys()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=valid_days)

    type_config = LICENSE_TYPES.get(license_type, LICENSE_TYPES["standard"])

    cert_data = {
        "fingerprint": fingerprint,
        "license_type": license_type,
        "features": type_config["features"],  # type: ignore[arg-type]
        "max_agents": type_config["max_agents"],
        "issued_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "issuer": issuer,
        "customer_name": customer,
    }

    signature = sign_certificate(cert_data)
    cert_data["signature"] = signature

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cert_data, f, indent=2, ensure_ascii=False)

    print(f"授权证书已生成: {output_path}")
    print(f"  授权类型: {license_type}")
    print(f"  最大 Agent 数: {type_config['max_agents']}")
    print(f"  有效期至: {expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  客户: {customer or '(未指定)'}")
    print(f"  签发方: {issuer}")
    print(f"  签名: {signature[:32]}...")


def verify_license_file(path: str) -> None:
    with open(path, "r", encoding="utf-8") as f:
        cert_data = json.load(f)

    cert_copy = dict(cert_data)
    if verify_certificate(cert_copy):
        print("证书验证通过")
        print(f"  指纹: {cert_data.get('fingerprint', 'N/A')}")
        print(f"  类型: {cert_data.get('license_type', 'N/A')}")
        print(f"  最大 Agent 数: {cert_data.get('max_agents', 'N/A')}")
        print(f"  签发时间: {cert_data.get('issued_at', 'N/A')}")
        print(f"  过期时间: {cert_data.get('expires_at', 'N/A')}")
        print(f"  客户: {cert_data.get('customer_name', 'N/A')}")
        print(f"  签发方: {cert_data.get('issuer', 'N/A')}")

        expires_at = cert_data.get("expires_at")
        if expires_at:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            remaining = (exp - datetime.now(timezone.utc)).days
            if remaining > 0:
                print(f"  剩余天数: {remaining}")
            else:
                print(f"  状态: 已过期 ({-remaining} 天)")
    else:
        print("证书验证失败")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TradingAgents-Astock 授权证书制作工具"
    )
    sub = parser.add_subparsers(dest="command")

    # export-fp
    fp_parser = sub.add_parser("export-fp", help="导出当前服务器硬件指纹")
    fp_parser.add_argument(
        "--output", "-o", default="fingerprint.json", help="输出文件路径"
    )

    # make
    make_parser = sub.add_parser("make", help="签发授权证书")
    make_parser.add_argument("--fingerprint", "-f", help="目标服务器硬件指纹 (SHA256)")
    make_parser.add_argument("--fingerprint-file", help="从指纹文件读取")
    make_parser.add_argument(
        "--type",
        "-t",
        default="standard",
        choices=["standard", "professional", "enterprise"],
        help="授权类型",
    )
    make_parser.add_argument("--valid-days", "-d", type=int, default=365, help="有效天数")
    make_parser.add_argument("--customer", "-c", default="", help="客户名称")
    make_parser.add_argument(
        "--issuer", "-i", default="TradingAgents", help="签发方"
    )
    make_parser.add_argument(
        "--output", "-o", default="license.json", help="输出文件路径"
    )

    # verify
    verify_parser = sub.add_parser("verify", help="验证授权证书")
    verify_parser.add_argument("file", help="证书文件路径")

    # gen-keys
    sub.add_parser("gen-keys", help="生成 RSA 密钥对")

    args = parser.parse_args()

    if args.command == "export-fp":
        export_fingerprint(args.output)

    elif args.command == "make":
        fingerprint = args.fingerprint
        if not fingerprint and args.fingerprint_file:
            with open(args.fingerprint_file, "r", encoding="utf-8") as f:
                fp_data = json.load(f)
                fingerprint = fp_data.get("fingerprint", "")

        if not fingerprint:
            print("错误: 请提供 --fingerprint 或 --fingerprint-file")
            sys.exit(1)

        make_license(
            fingerprint=fingerprint,
            license_type=args.type,
            valid_days=args.valid_days,
            customer=args.customer,
            issuer=args.issuer,
            output_path=args.output,
        )

    elif args.command == "verify":
        verify_license_file(args.file)

    elif args.command == "gen-keys":
        ensure_keys()
        print(f"密钥文件位置:")
        print(f"  私钥: {PRIVATE_KEY_PATH}")
        print(f"  公钥: {PUBLIC_KEY_PATH}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
