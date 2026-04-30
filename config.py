# -*- coding: utf-8 -*-
"""
Client Skill 配置

配置Server OpenClaw的地址
"""

# ============ Server OpenClaw 地址（已配置）============
SERVER_URL = "http://114.215.127.115:5007"

# ============ 请求配置 ============
TIMEOUT = 30      # 请求超时（秒）
RETRIES = 2       # 重试次数

# ============ 用户ID配置 ============
# 如果Client OpenClaw没有传user_id，用这个前缀生成
DEFAULT_USER_PREFIX = "user_"
