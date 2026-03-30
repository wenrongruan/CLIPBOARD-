/**
 * SharedClipboard Website
 * i18n engine + download links + interactions
 *
 * To update the version: change APP_VERSION below.
 * To update GitHub repo: change GITHUB_REPO below.
 */

const APP_VERSION = '1.1.0';
const GITHUB_REPO = 'YOUR_USERNAME/SharedClipboard'; // <-- 替换为你的 GitHub 仓库地址

// Download URLs — derived from GITHUB_REPO + APP_VERSION
const DOWNLOADS = {
  windows: `https://github.com/${GITHUB_REPO}/releases/download/v${APP_VERSION}/SharedClipboard.exe`,
  macos:   `https://github.com/${GITHUB_REPO}/releases/download/v${APP_VERSION}/%E5%85%B1%E4%BA%AB%E5%89%AA%E8%B4%B4%E6%9D%BF-macOS.dmg`,
  linux:   `https://github.com/${GITHUB_REPO}/releases/download/v${APP_VERSION}/SharedClipboard-Linux-x86_64.AppImage`,
  github:  `https://github.com/${GITHUB_REPO}`,
  releases:`https://github.com/${GITHUB_REPO}/releases`,
};

// =====================================================
// i18n Engine
// =====================================================

const SUPPORTED_LANGS = ['zh_CN','en_US','ja_JP','ko_KR','es_ES','fr_FR','de_DE','ru_RU'];
let translations = {};
let currentLang = 'zh_CN';

async function loadTranslations() {
  const resp = await fetch('i18n.json');
  translations = await resp.json();
}

function detectLanguage() {
  // Priority: URL hash → localStorage → browser language → default zh_CN
  const hash = window.location.hash;
  const hashMatch = hash.match(/[#&]lang=([a-z]{2}_[A-Z]{2})/);
  if (hashMatch && SUPPORTED_LANGS.includes(hashMatch[1])) return hashMatch[1];

  const saved = localStorage.getItem('sc_lang');
  if (saved && SUPPORTED_LANGS.includes(saved)) return saved;

  const browser = (navigator.language || navigator.userLanguage || '').replace('-', '_');
  if (SUPPORTED_LANGS.includes(browser)) return browser;

  // Partial match (e.g. "zh" → "zh_CN")
  const prefix = browser.split('_')[0];
  const matched = SUPPORTED_LANGS.find(l => l.startsWith(prefix));
  if (matched) return matched;

  return 'zh_CN';
}

function applyTranslations(lang) {
  const dict = translations[lang] || translations['zh_CN'];
  if (!dict) return;

  // data-i18n="key" → textContent
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (dict[key] !== undefined) el.textContent = dict[key];
  });

  // data-i18n-html="key" → innerHTML (for strings with <code> / <br>)
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    const key = el.getAttribute('data-i18n-html');
    if (dict[key] !== undefined) el.innerHTML = dict[key];
  });

  // Update <html lang>
  document.documentElement.lang = lang.replace('_', '-');

  // Update page title & description
  const appName = dict['hero_title'] || 'SharedClipboard';
  document.title = `${appName} — ${dict['hero_subtitle'] ? dict['hero_subtitle'].slice(0,30) + '…' : ''}`;
}

function switchLanguage(lang) {
  if (!SUPPORTED_LANGS.includes(lang)) return;
  currentLang = lang;
  localStorage.setItem('sc_lang', lang);

  // Update URL hash without reload
  const newHash = window.location.hash.replace(/[#&]lang=[a-z_A-Z]+/, '');
  history.replaceState(null, '', (newHash || '#') + `lang=${lang}`);

  applyTranslations(lang);

  // Update language switcher button label
  const dict = translations[lang] || {};
  const langCurrent = document.getElementById('langCurrent');
  if (langCurrent) langCurrent.textContent = dict['lang_name'] || lang;

  // Mark active item in menu
  document.querySelectorAll('#langMenu li').forEach(li => {
    li.classList.toggle('active', li.dataset.lang === lang);
  });
}

// =====================================================
// Download Links
// =====================================================

function setDownloadLinks() {
  const pairs = [
    ['dlWindows', DOWNLOADS.windows],
    ['dlMacos',   DOWNLOADS.macos],
    ['dlLinux',   DOWNLOADS.linux],
    ['dlWin2',    DOWNLOADS.windows],
    ['dlMac2',    DOWNLOADS.macos],
    ['dlLinux2',  DOWNLOADS.linux],
    ['githubLink',DOWNLOADS.github],
    ['footerGithub', DOWNLOADS.github],
  ];
  pairs.forEach(([id, url]) => {
    const el = document.getElementById(id);
    if (el) el.href = url;
  });

  // Version badges
  ['versionBadge', 'footerVersion'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = `v${APP_VERSION}`;
  });
}

// Detect OS and highlight recommended download button
function highlightCurrentPlatform() {
  const ua = navigator.userAgent.toLowerCase();
  const cards = {
    windows: document.getElementById('dlCardWin'),
    macos:   document.getElementById('dlCardMac'),
    linux:   document.getElementById('dlCardLinux'),
  };
  const heroButtons = {
    windows: document.getElementById('dlWindows'),
    macos:   document.getElementById('dlMacos'),
    linux:   document.getElementById('dlLinux'),
  };

  let platform = null;
  if (ua.includes('win')) platform = 'windows';
  else if (ua.includes('mac')) platform = 'macos';
  else if (ua.includes('linux')) platform = 'linux';

  if (platform) {
    // Highlight download card
    if (cards[platform]) cards[platform].classList.add('highlighted');
    // Make hero button primary for current platform, secondary for others
    Object.entries(heroButtons).forEach(([p, btn]) => {
      if (!btn) return;
      if (p === platform) {
        btn.classList.remove('btn-secondary');
        btn.classList.add('btn-primary');
      } else {
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-secondary');
      }
    });
  }
}

// =====================================================
// Language Switcher Dropdown
// =====================================================

function initLangSwitcher() {
  const btn = document.getElementById('langBtn');
  const menu = document.getElementById('langMenu');
  if (!btn || !menu) return;

  btn.addEventListener('click', e => {
    e.stopPropagation();
    menu.classList.toggle('open');
  });

  menu.querySelectorAll('li').forEach(li => {
    li.addEventListener('click', () => {
      switchLanguage(li.dataset.lang);
      menu.classList.remove('open');
    });
  });

  document.addEventListener('click', () => menu.classList.remove('open'));
}

// =====================================================
// FAQ Accordion
// =====================================================

function initFAQ() {
  document.querySelectorAll('.faq-q').forEach(btn => {
    btn.addEventListener('click', () => {
      const item = btn.closest('.faq-item');
      const isOpen = item.classList.contains('open');

      // Close all
      document.querySelectorAll('.faq-item.open').forEach(el => {
        el.classList.remove('open');
        el.querySelector('.faq-q').setAttribute('aria-expanded', 'false');
      });

      // Toggle clicked
      if (!isOpen) {
        item.classList.add('open');
        btn.setAttribute('aria-expanded', 'true');
      }
    });
  });
}

// =====================================================
// Nav scroll shadow
// =====================================================

function initNavScroll() {
  const nav = document.getElementById('nav');
  if (!nav) return;
  const onScroll = () => {
    nav.style.borderBottomColor = window.scrollY > 10
      ? 'var(--border-hover)'
      : 'var(--border)';
  };
  window.addEventListener('scroll', onScroll, { passive: true });
}

// =====================================================
// Privacy Modal
// =====================================================

function initPrivacyModal() {
  const modal = document.getElementById('privacyModal');
  const trigger = document.getElementById('footerPrivacy');
  const closeBtn = document.getElementById('modalClose');
  if (!modal || !trigger) return;

  trigger.addEventListener('click', e => {
    e.preventDefault();
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
  });

  const closeModal = () => {
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
  };

  if (closeBtn) closeBtn.addEventListener('click', closeModal);
  modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
}

// =====================================================
// Smooth scroll for nav links
// =====================================================

function initSmoothScroll() {
  document.querySelectorAll('a[href^="#"]').forEach(a => {
    const href = a.getAttribute('href');
    // Skip language hash links and empty
    if (href === '#' || href.startsWith('#lang=')) return;
    a.addEventListener('click', e => {
      const target = document.querySelector(href);
      if (target) {
        e.preventDefault();
        const navH = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--nav-h')) || 60;
        const top = target.getBoundingClientRect().top + window.scrollY - navH - 16;
        window.scrollTo({ top, behavior: 'smooth' });
      }
    });
  });
}

// =====================================================
// Boot
// =====================================================

async function init() {
  await loadTranslations();

  currentLang = detectLanguage();
  applyTranslations(currentLang);

  // Set switcher label
  const dict = translations[currentLang] || {};
  const langCurrent = document.getElementById('langCurrent');
  if (langCurrent) langCurrent.textContent = dict['lang_name'] || currentLang;

  // Mark active lang in menu
  document.querySelectorAll('#langMenu li').forEach(li => {
    li.classList.toggle('active', li.dataset.lang === currentLang);
  });

  setDownloadLinks();
  highlightCurrentPlatform();
  initLangSwitcher();
  initFAQ();
  initNavScroll();
  initPrivacyModal();
  initSmoothScroll();
}

document.addEventListener('DOMContentLoaded', init);
