/**
 * SharedClipboard 账户管理页面逻辑
 *
 * 处理登录/注册、账户信息展示、订阅状态、设备管理等功能。
 * API base URL 默认为 https://api.jlike.com，可通过 URL 参数 ?api=xxx 覆盖。
 */

(function () {
  'use strict';

  // =====================================================
  // 配置
  // =====================================================

  // 从 URL 参数读取自定义 API 地址，默认使用生产地址
  const urlParams = new URLSearchParams(window.location.search);
  const API_BASE = (urlParams.get('api') || '').replace(/\/+$/, '');

  const TOKEN_KEY = 'sc_auth_token';
  const REFRESH_KEY = 'sc_refresh_token';

  // =====================================================
  // DOM 元素引用
  // =====================================================

  const authPanel = document.getElementById('authPanel');
  const dashboardPanel = document.getElementById('dashboardPanel');
  const authTitle = document.getElementById('authTitle');
  const authSubtitle = document.getElementById('authSubtitle');
  const nameField = document.getElementById('nameField');
  const inputName = document.getElementById('inputName');
  const inputEmail = document.getElementById('inputEmail');
  const inputPassword = document.getElementById('inputPassword');
  const authError = document.getElementById('authError');
  const authSubmitBtn = document.getElementById('authSubmitBtn');
  const switchAuthMode = document.getElementById('switchAuthMode');
  const switchHint = document.getElementById('switchHint');
  const logoutBtn = document.getElementById('logoutBtn');

  // 账户面板元素
  const profileEmail = document.getElementById('profileEmail');
  const profileName = document.getElementById('profileName');
  const profileCreatedAt = document.getElementById('profileCreatedAt');
  const planName = document.getElementById('planName');
  const planBadge = document.getElementById('planBadge');
  const usageText = document.getElementById('usageText');
  const usageBar = document.getElementById('usageBar');
  const deviceCountText = document.getElementById('deviceCountText');
  const deviceBar = document.getElementById('deviceBar');
  const expiryRow = document.getElementById('expiryRow');
  const planExpiry = document.getElementById('planExpiry');
  const manageSubBtn = document.getElementById('manageSubBtn');
  const deviceList = document.getElementById('deviceList');
  const deviceLoading = document.getElementById('deviceLoading');

  // 当前是否处于注册模式
  let isRegisterMode = false;

  // =====================================================
  // 工具函数
  // =====================================================

  /** 获取当前 token */
  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  /** 保存 token */
  function saveToken(token, refreshToken) {
    localStorage.setItem(TOKEN_KEY, token);
    if (refreshToken) {
      localStorage.setItem(REFRESH_KEY, refreshToken);
    }
  }

  /** 清除 token */
  function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
  }

  /** 显示错误信息 */
  function showError(msg) {
    if (authError) {
      authError.textContent = msg;
      authError.style.display = 'block';
    }
  }

  /** 隐藏错误信息 */
  function hideError() {
    if (authError) {
      authError.style.display = 'none';
    }
  }

  /** 格式化日期 */
  function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      });
    } catch {
      return dateStr;
    }
  }

  /** HTML 转义，防止 XSS */
  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.textContent;
  }

  /** 发起 API 请求的通用函数，自动附带 token */
  async function apiRequest(endpoint, options = {}) {
    const token = getToken();
    const headers = {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const url = `${API_BASE}${endpoint}`;

    try {
      const resp = await fetch(url, {
        ...options,
        headers
      });

      // token 过期，尝试刷新
      if (resp.status === 401 && localStorage.getItem(REFRESH_KEY)) {
        const refreshed = await refreshAuthToken();
        if (refreshed) {
          headers['Authorization'] = `Bearer ${getToken()}`;
          const retryResp = await fetch(url, { ...options, headers });
          return retryResp;
        }
      }

      return resp;
    } catch (err) {
      console.error('API 请求失败:', err);
      throw err;
    }
  }

  /** 尝试刷新 token */
  async function refreshAuthToken() {
    const rt = localStorage.getItem(REFRESH_KEY);
    if (!rt) return false;

    try {
      const resp = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: rt })
      });

      if (resp.ok) {
        const data = await resp.json();
        saveToken(data.token, data.refresh_token || rt);
        return true;
      }
    } catch (err) {
      console.error('Token 刷新失败:', err);
    }

    // 刷新失败，清除 token 并退回登录
    clearToken();
    showAuthPanel();
    return false;
  }

  // =====================================================
  // 视图切换
  // =====================================================

  /** 显示登录/注册面板 */
  function showAuthPanel() {
    if (authPanel) authPanel.style.display = '';
    if (dashboardPanel) dashboardPanel.style.display = 'none';
  }

  /** 显示账户面板 */
  function showDashboard() {
    if (authPanel) authPanel.style.display = 'none';
    if (dashboardPanel) dashboardPanel.style.display = '';
  }

  /** 切换登录/注册模式 */
  function toggleAuthMode() {
    isRegisterMode = !isRegisterMode;
    hideError();

    if (isRegisterMode) {
      if (authTitle) authTitle.textContent = getI18nText('account_register_title', '注册');
      if (authSubtitle) authSubtitle.textContent = getI18nText('account_register_subtitle', '创建账户以使用云同步功能');
      if (authSubmitBtn) authSubmitBtn.textContent = getI18nText('account_register_btn', '注册');
      if (switchHint) switchHint.textContent = getI18nText('account_has_account', '已有账户？');
      if (switchAuthMode) switchAuthMode.textContent = getI18nText('account_login_link', '登录');
      if (nameField) nameField.style.display = '';
    } else {
      if (authTitle) authTitle.textContent = getI18nText('account_login_title', '登录');
      if (authSubtitle) authSubtitle.textContent = getI18nText('account_login_subtitle', '登录以管理你的订阅和设备');
      if (authSubmitBtn) authSubmitBtn.textContent = getI18nText('account_login_btn', '登录');
      if (switchHint) switchHint.textContent = getI18nText('account_no_account', '还没有账户？');
      if (switchAuthMode) switchAuthMode.textContent = getI18nText('account_register_link', '注册');
      if (nameField) nameField.style.display = 'none';
    }
  }

  /** 获取 i18n 翻译文本（兼容 app.js 的 translations 全局变量） */
  function getI18nText(key, fallback) {
    if (typeof translations !== 'undefined' && typeof currentLang !== 'undefined') {
      const dict = translations[currentLang] || {};
      if (dict[key]) return dict[key];
    }
    return fallback;
  }

  // =====================================================
  // 登录 / 注册
  // =====================================================

  async function handleAuth() {
    hideError();
    const email = (inputEmail ? inputEmail.value : '').trim();
    const password = (inputPassword ? inputPassword.value : '').trim();
    const name = (inputName ? inputName.value : '').trim();

    if (!email || !password) {
      showError(getI18nText('account_error_empty', '请填写邮箱和密码'));
      return;
    }

    // 禁用按钮，显示加载状态
    if (authSubmitBtn) {
      authSubmitBtn.disabled = true;
      authSubmitBtn.textContent = getI18nText('account_loading', '加载中...');
    }

    try {
      const endpoint = isRegisterMode ? '/api/v1/auth/register' : '/api/v1/auth/login';
      const body = isRegisterMode
        ? { email, password, name: name || undefined }
        : { email, password };

      const resp = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      const data = await resp.json().catch(() => ({}));

      if (!resp.ok) {
        showError(data.message || data.error || `${getI18nText('account_error_failed', '操作失败')} (${resp.status})`);
        return;
      }

      // 登录/注册成功，保存 token
      saveToken(data.token, data.refresh_token);
      showDashboard();
      loadAccountData();
    } catch (err) {
      showError(getI18nText('account_error_network', '网络错误，请检查连接后重试'));
    } finally {
      if (authSubmitBtn) {
        authSubmitBtn.disabled = false;
        authSubmitBtn.textContent = isRegisterMode
          ? getI18nText('account_register_btn', '注册')
          : getI18nText('account_login_btn', '登录');
      }
    }
  }

  // =====================================================
  // 加载账户数据
  // =====================================================

  async function loadAccountData() {
    // 并行请求用户信息、订阅状态、设备列表
    await Promise.all([
      loadProfile(),
      loadSubscription(),
      loadDevices()
    ]);
  }

  /** 加载用户信息 */
  async function loadProfile() {
    try {
      const resp = await apiRequest('/api/v1/auth/me');
      if (!resp.ok) {
        if (resp.status === 401) {
          clearToken();
          showAuthPanel();
          return;
        }
        return;
      }
      const data = await resp.json();
      if (profileEmail) profileEmail.textContent = data.email || '—';
      if (profileName) profileName.textContent = data.name || data.display_name || '—';
      if (profileCreatedAt) profileCreatedAt.textContent = formatDate(data.created_at || data.registered_at);
    } catch (err) {
      console.error('加载用户信息失败:', err);
    }
  }

  /** 加载订阅状态 */
  async function loadSubscription() {
    try {
      const resp = await apiRequest('/api/v1/subscription');
      if (!resp.ok) return;
      const data = await resp.json();

      // 套餐名称与徽章
      const plan = data.plan || data.plan_name || 'Free';
      if (planName) planName.textContent = plan;
      if (planBadge) {
        planBadge.textContent = plan;
        planBadge.className = 'account-plan-badge account-plan-badge-' + plan.toLowerCase();
      }

      // 用量进度
      const usedRecords = data.used_records || data.records_used || 0;
      const maxRecords = data.max_records || data.records_limit || 30;
      if (usageText) usageText.textContent = `${usedRecords} / ${maxRecords}`;
      if (usageBar) {
        const pct = maxRecords > 0 ? Math.min((usedRecords / maxRecords) * 100, 100) : 0;
        usageBar.style.width = pct + '%';
        // 超过 80% 显示警告色
        usageBar.style.background = pct > 80 ? 'var(--cta)' : 'var(--accent)';
      }

      // 设备数
      const usedDevices = data.used_devices || data.devices_used || 0;
      const maxDevices = data.max_devices || data.devices_limit || 2;
      const maxDevicesDisplay = maxDevices >= 9999 ? '\u221e' : maxDevices;
      if (deviceCountText) deviceCountText.textContent = `${usedDevices} / ${maxDevicesDisplay}`;
      if (deviceBar) {
        const dpct = maxDevices >= 9999 ? Math.min(usedDevices * 10, 100) : Math.min((usedDevices / maxDevices) * 100, 100);
        deviceBar.style.width = dpct + '%';
      }

      // 到期时间（付费用户显示）
      if (data.expires_at && plan.toLowerCase() !== 'free') {
        if (expiryRow) expiryRow.style.display = '';
        if (planExpiry) planExpiry.textContent = formatDate(data.expires_at);
      } else {
        if (expiryRow) expiryRow.style.display = 'none';
      }

      // 管理订阅链接
      if (manageSubBtn && data.manage_url) {
        manageSubBtn.href = data.manage_url;
        manageSubBtn.target = '_blank';
        manageSubBtn.rel = 'noopener';
      }
    } catch (err) {
      console.error('加载订阅信息失败:', err);
    }
  }

  /** 加载设备列表 */
  async function loadDevices() {
    try {
      const resp = await apiRequest('/api/v1/devices');
      if (!resp.ok) {
        if (deviceLoading) deviceLoading.style.display = 'none';
        return;
      }
      const data = await resp.json();
      const devices = data.devices || data || [];

      if (deviceLoading) deviceLoading.style.display = 'none';

      // 清空列表内容
      while (deviceList.firstChild) {
        deviceList.removeChild(deviceList.firstChild);
      }

      if (devices.length === 0) {
        const p = document.createElement('p');
        p.className = 'account-no-devices';
        p.setAttribute('data-i18n', 'account_no_devices');
        p.textContent = getI18nText('account_no_devices', '暂无已注册设备');
        deviceList.appendChild(p);
        return;
      }

      // 使用 DOM API 安全渲染设备列表
      devices.forEach(function (device) {
        const platformIcon = getPlatformIcon(device.platform || device.os);
        const lastOnline = device.last_online || device.last_seen_at || '';
        const deviceId = device.id || device.device_id || '';

        const item = document.createElement('div');
        item.className = 'account-device-item';
        item.setAttribute('data-device-id', deviceId);

        const infoDiv = document.createElement('div');
        infoDiv.className = 'account-device-info';

        const iconSpan = document.createElement('span');
        iconSpan.className = 'account-device-icon';
        iconSpan.textContent = platformIcon;

        const detailsDiv = document.createElement('div');
        detailsDiv.className = 'account-device-details';

        const nameSpan = document.createElement('span');
        nameSpan.className = 'account-device-name';
        nameSpan.textContent = device.name || device.device_name || '未知设备';

        const metaSpan = document.createElement('span');
        metaSpan.className = 'account-device-meta';
        metaSpan.textContent = (device.platform || device.os || '') +
          (lastOnline ? ' \u00b7 ' + formatDate(lastOnline) : '');

        detailsDiv.appendChild(nameSpan);
        detailsDiv.appendChild(metaSpan);
        infoDiv.appendChild(iconSpan);
        infoDiv.appendChild(detailsDiv);

        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn btn-secondary account-device-remove';
        removeBtn.setAttribute('data-device-id', deviceId);
        removeBtn.textContent = getI18nText('account_remove_device', '移除');
        removeBtn.addEventListener('click', function () {
          removeDevice(deviceId);
        });

        item.appendChild(infoDiv);
        item.appendChild(removeBtn);
        deviceList.appendChild(item);
      });
    } catch (err) {
      console.error('加载设备列表失败:', err);
      if (deviceLoading) deviceLoading.style.display = 'none';
    }
  }

  /** 移除设备 */
  async function removeDevice(deviceId) {
    if (!deviceId) return;
    const confirmMsg = getI18nText('account_confirm_remove', '确定要移除此设备吗？');
    if (!confirm(confirmMsg)) return;

    try {
      const resp = await apiRequest('/api/v1/devices/' + encodeURIComponent(deviceId), {
        method: 'DELETE'
      });

      if (resp.ok) {
        // 重新加载设备列表和订阅状态
        loadDevices();
        loadSubscription();
      } else {
        const data = await resp.json().catch(() => ({}));
        alert(data.message || getI18nText('account_error_failed', '操作失败'));
      }
    } catch (err) {
      console.error('移除设备失败:', err);
      alert(getI18nText('account_error_network', '网络错误，请检查连接后重试'));
    }
  }

  /** 根据平台返回对应图标 */
  function getPlatformIcon(platform) {
    if (!platform) return '\uD83D\uDCBB';
    const p = platform.toLowerCase();
    if (p.includes('win')) return '\uD83E\uDE9F';
    if (p.includes('mac') || p.includes('darwin')) return '\uD83C\uDF4E';
    if (p.includes('linux')) return '\uD83D\uDC27';
    if (p.includes('android')) return '\uD83D\uDCF1';
    if (p.includes('ios') || p.includes('iphone') || p.includes('ipad')) return '\uD83D\uDCF1';
    return '\uD83D\uDCBB';
  }

  // =====================================================
  // 退出登录
  // =====================================================

  function handleLogout() {
    clearToken();
    showAuthPanel();
    // 清空表单
    if (inputEmail) inputEmail.value = '';
    if (inputPassword) inputPassword.value = '';
    if (inputName) inputName.value = '';
    hideError();
  }

  // =====================================================
  // 初始化
  // =====================================================

  function initAccount() {
    // 绑定事件
    if (authSubmitBtn) {
      authSubmitBtn.addEventListener('click', handleAuth);
    }

    if (switchAuthMode) {
      switchAuthMode.addEventListener('click', function (e) {
        e.preventDefault();
        toggleAuthMode();
      });
    }

    if (logoutBtn) {
      logoutBtn.addEventListener('click', handleLogout);
    }

    // 支持回车提交
    [inputEmail, inputPassword, inputName].forEach(function (el) {
      if (el) {
        el.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') handleAuth();
        });
      }
    });

    // 检查是否已登录
    const token = getToken();
    if (token) {
      showDashboard();
      loadAccountData();
    } else {
      showAuthPanel();
    }
  }

  // 等待 DOM 和 app.js 的 i18n 初始化完成后再执行
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      // 延迟一帧以确保 app.js init() 已执行
      setTimeout(initAccount, 50);
    });
  } else {
    setTimeout(initAccount, 50);
  }
})();
