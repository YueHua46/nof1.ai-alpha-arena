#!/usr/bin/env python3
"""
测试 OKX API 连接
用于验证 API 密钥是否正确配置
"""

import asyncio
import ccxt.async_support as ccxt
from dotenv import load_dotenv
import os

async def test_okx_connection():
    """测试 OKX 连接和认证"""
    
    # 加载环境变量
    load_dotenv()
    
    api_key = os.getenv('OKX_API_KEY')
    secret_key = os.getenv('OKX_SECRET_KEY')
    passphrase = os.getenv('OKX_PASSPHRASE')
    flag = os.getenv('OKX_FLAG', '0')
    
    print("=" * 60)
    print("OKX API 连接测试")
    print("=" * 60)
    
    # 检查配置
    print(f"\n📋 当前配置：")
    print(f"   API Key: {api_key[:8]}...{api_key[-4:] if api_key else 'None'}")
    print(f"   Secret Key: {secret_key[:8]}...{secret_key[-4:] if secret_key else 'None'}")
    print(f"   Passphrase: {'*' * len(passphrase) if passphrase else 'None'}")
    print(f"   模式: {'实盘 (Real Trading)' if flag == '1' else '模拟盘 (Demo Trading)'}")
    
    if not all([api_key, secret_key, passphrase]):
        print("\n❌ 错误：API 密钥配置不完整！")
        print("   请检查 .env 文件中的 OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE")
        return
    
    # 创建交易所实例
    exchange = ccxt.okx({
        'apiKey': api_key,
        'secret': secret_key,
        'password': passphrase,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',
        }
    })
    
    if flag == '0':
        exchange.set_sandbox_mode(True)
        print("\n🔧 已切换到模拟盘模式")
    
    try:
        print("\n🔄 测试 1：加载市场信息...")
        markets = await exchange.load_markets()
        print(f"✅ 成功！共加载 {len(markets)} 个交易对")
        
        print("\n🔄 测试 2：获取账户余额...")
        balance = await exchange.fetch_balance({'type': 'swap'})
        
        print("✅ 成功！账户信息：")
        if 'USDT' in balance:
            usdt_balance = balance['USDT']
            print(f"   可用 USDT: {usdt_balance.get('free', 0):.2f}")
            print(f"   总 USDT: {usdt_balance.get('total', 0):.2f}")
        
        # 尝试获取总权益
        if 'info' in balance and 'data' in balance['info']:
            data_list = balance['info']['data']
            if data_list and len(data_list) > 0:
                total_eq = float(data_list[0].get('totalEq', 0))
                print(f"   账户总权益: ${total_eq:.2f}")
        
        print("\n🔄 测试 3：获取持仓信息...")
        positions = await exchange.fetch_positions()
        print(f"✅ 成功！当前持仓数量: {len([p for p in positions if float(p.get('contracts', 0)) > 0])}")
        
        print("\n" + "=" * 60)
        print("🎉 所有测试通过！API 密钥配置正确！")
        print("=" * 60)
        
    except ccxt.AuthenticationError as e:
        print(f"\n❌ 认证失败：{e}")
        print("\n可能的原因：")
        print("1. API 密钥、Secret 或 Passphrase 不正确")
        print("2. 模拟盘/实盘设置错误（OKX_FLAG）")
        print("   - 如果 API 密钥是模拟盘的，OKX_FLAG 应该设置为 0")
        print("   - 如果 API 密钥是实盘的，OKX_FLAG 应该设置为 1")
        print("3. IP 白名单限制（如果设置了）")
        print("4. API 密钥权限不足（需要：读取 + 交易）")
        print("\n💡 建议：")
        print("1. 登录 OKX 检查 API 密钥状态")
        print("2. 重新生成 API 密钥")
        print("3. 确认模拟盘/实盘设置正确")
        
    except Exception as e:
        print(f"\n❌ 错误：{e}")
        
    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(test_okx_connection())
