// core/static/core/js/telegram_fallback.js
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('a.tg-link').forEach(function(el) {
      el.addEventListener('click', function(event) {
        event.preventDefault();
  
        const targetUsername = el.dataset.username;
        const targetPhone    = el.dataset.phone;
        let protocolUrl = '';
        let webUrl      = '';
  
        if (targetUsername) {
          protocolUrl = 'tg://resolve?domain=' + targetUsername;
          webUrl      = 'https://t.me/'      + targetUsername;
        } else if (targetPhone) {
          protocolUrl = 'tg://resolve?phone='  + targetPhone;
          webUrl      = '/user-profile/' + targetPhone;
        } else {
          return; // هیچ راهی برای چت با این کاربر وجود ندارد
        }
  
        // اول تلاش برای باز کردن تلگرام نصب‌شده و چت با target_user
        window.location = protocolUrl;
  
        // اگر پس از ۵۰۰ میلی‌ثانیه پروتکل هندلر جوابی نداد، لینک وب (fallback) باز می‌شود
        setTimeout(function() {
          window.open(webUrl, '_blank');
        }, 500);
      });
    });
  });
  