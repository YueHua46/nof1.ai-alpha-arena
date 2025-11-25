# 网络连接问题解决方案

## 🚨 问题说明

您遇到的错误：
```
OSError: [Errno 64] Host is down
Cannot connect to host www.okx.com:443
RequestTimeout: okx GET https://www.okx.com/api/v5/asset/currencies
```

**根本原因**：**OKX 在中国大陆被墙，无法直接访问**

---

## ✅ 解决方案

### 步骤 1：启动代理软件

您需要使用代理软件才能访问 OKX。常见的代理软件：

- **Clash** (推荐)
- **V2Ray**
- **Shadowsocks (SSR)**
- **Clash for Windows**
- **Clash X (Mac)**

确保您的代理软件：
1. ✅ 已启动
2. ✅ 处于全局模式或规则模式
3. ✅ 可以正常访问外网

### 步骤 2：查看代理端口

**Clash 用户**：
1. 打开 Clash 软件
2. 查看设置中的端口号
3. 通常是：
   - HTTP 端口：`7890`
   - SOCKS5 端口：`7891`

**V2Ray 用户**：
1. 打开 V2Ray 软件
2. 查看设置中的本地端口
3. 通常是：`1080` 或 `10808`

### 步骤 3：配置 .env 文件

打开 `.env` 文件，找到代理配置部分，填入您的代理端口：

#### 🔸 使用 HTTP 代理（Clash 默认）

```bash
# 网络代理配置（中国大陆用户必填）
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
SOCKS5_PROXY=
```

#### 🔸 使用 SOCKS5 代理

```bash
# 网络代理配置（中国大陆用户必填）
HTTP_PROXY=
HTTPS_PROXY=
SOCKS5_PROXY=socks5://127.0.0.1:7891
```

**重要**：
- 端口号要根据您的代理软件实际端口填写
- 只需要配置其中一种（HTTP 或 SOCKS5）
- `127.0.0.1` 表示本地代理

### 步骤 4：重启程序

保存 `.env` 文件后，重启交易程序：

```bash
python main.py
```

---

## 🔍 如何找到代理端口

### Clash 用户

1. **Clash for Windows**：
   - 点击 "General" 或"常规"
   - 查看 "Port" 和 "Socks Port"
   - 通常是 7890 和 7891

2. **Clash X (Mac)**：
   - 点击菜单栏的 Clash 图标
   - 选择 "设置"
   - 查看 "HTTP 代理端口" 和 "SOCKS5 代理端口"

### V2Ray 用户

1. 打开 V2RayN 或 V2RayX
2. 点击 "参数设置"
3. 查看 "本地监听端口"
4. 通常是 10808 或 1080

### 测试代理是否工作

在终端运行：

```bash
# 测试 HTTP 代理
curl -x http://127.0.0.1:7890 https://www.google.com

# 测试 SOCKS5 代理
curl -x socks5://127.0.0.1:7891 https://www.google.com
```

如果能返回 HTML 内容，说明代理正常。

---

## 📋 完整配置示例

### Clash 用户（推荐配置）

```bash
# .env 文件

# OKX 交易所配置
OKX_API_KEY=your_api_key
OKX_SECRET_KEY=your_secret_key
OKX_PASSPHRASE=your_passphrase
OKX_FLAG=1

# 网络代理配置（Clash 默认端口）
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
SOCKS5_PROXY=

# 其他配置...
```

### V2Ray 用户配置

```bash
# .env 文件

# OKX 交易所配置
OKX_API_KEY=your_api_key
OKX_SECRET_KEY=your_secret_key
OKX_PASSPHRASE=your_passphrase
OKX_FLAG=1

# 网络代理配置（V2Ray 默认端口）
HTTP_PROXY=http://127.0.0.1:10808
HTTPS_PROXY=http://127.0.0.1:10808
SOCKS5_PROXY=

# 其他配置...
```

---

## 🎯 验证配置

启动程序后，查看日志：

### ✅ 成功的日志

```
2025-11-24 21:30:00 [INFO] 🌐 使用 HTTP 代理：http://127.0.0.1:7890
2025-11-24 21:30:01 [INFO] 🔄 加载市场信息... (尝试 1/3)
2025-11-24 21:30:02 [INFO] ✅ 市场信息加载成功
2025-11-24 21:30:02 [INFO] OKX 客户端（CCXT）初始化完成（模拟盘：False）
```

### ❌ 失败的日志

```
2025-11-24 21:30:00 [WARNING] ⚠️  未配置代理。如果在中国大陆，OKX 可能无法访问！
2025-11-24 21:30:01 [ERROR] ❌ 网络连接失败 (尝试 1/3): Cannot connect to host
2025-11-24 21:30:06 [ERROR] ❌ 无法连接到 OKX 服务器。请检查：
```

---

## 🐛 常见问题

### Q1: 配置了代理还是连接失败

**解决方案**：
1. 确认代理软件正在运行
2. 确认端口号填写正确
3. 尝试在浏览器中访问 https://www.okx.com
4. 如果浏览器也打不开，说明代理有问题

### Q2: 不知道代理端口号

**解决方案**：
1. 打开代理软件设置页面
2. 或在终端运行：
   ```bash
   # Mac/Linux
   env | grep -i proxy
   
   # 或查看系统代理设置
   # Mac: 系统偏好设置 > 网络 > 高级 > 代理
   ```

### Q3: 代理软件没有端口号设置

**解决方案**：
- 使用系统全局代理模式
- 或者更换代理软件（推荐 Clash）

### Q4: 在海外，不需要代理

**解决方案**：
保持代理配置为空：
```bash
HTTP_PROXY=
HTTPS_PROXY=
SOCKS5_PROXY=
```

程序会自动直连 OKX。

---

## 📞 技术支持

如果按照以上步骤还是无法解决：

1. 查看完整日志：`bot.log`
2. 确认网络状况：`ping www.google.com`
3. 测试代理：`curl -x http://127.0.0.1:7890 https://www.okx.com`

---

## 🔄 已实现的优化

✅ **自动重试机制**：连接失败会自动重试 3 次
✅ **指数退避**：每次重试等待时间加倍（5秒 → 10秒 → 20秒）
✅ **详细错误提示**：明确告知问题所在
✅ **代理支持**：支持 HTTP/HTTPS/SOCKS5 代理
✅ **超时优化**：请求超时时间设置为 30 秒

---

## 📝 快速检查清单

- [ ] 代理软件已启动
- [ ] 代理软件工作正常（能访问外网）
- [ ] 已在 `.env` 文件中配置代理
- [ ] 端口号填写正确
- [ ] 已重启程序
- [ ] 查看日志确认代理生效

如果以上都完成，程序应该可以正常连接到 OKX！
