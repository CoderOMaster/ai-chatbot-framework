// Simple embeddable widget script that loads the chatbot iframe
(function () {
  // Prefer runtime-provided public env for client-side usage
  // Fallback to a global set by the embedding page
  var apiBase =
    (typeof process !== 'undefined' && process.env && process.env.NEXT_PUBLIC_API_BASE_URL) ||
    (typeof window !== 'undefined' && window.__CHATBOT_API_BASE__) ||
    '';

  function createIframe(src) {
    var iframe = document.createElement('iframe');
    iframe.src = src;
    iframe.style.border = '0';
    iframe.style.width = '100%';
    iframe.style.height = '500px';
    iframe.setAttribute('title', 'AI Chatbot');
    return iframe;
  }

  function init() {
    var containers = document.querySelectorAll('[data-chatbot-widget]');
    containers.forEach(function (el) {
      var path = el.getAttribute('data-path') || '/';
      var url = apiBase ? String(apiBase).replace(/\/$/, '') + path : path;
      var iframe = createIframe(url);
      el.appendChild(iframe);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();