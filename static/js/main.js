/**
 * main.js
 * Core application interactions (Navbar, Modals, Loading screen, etc.)
 */

document.addEventListener('DOMContentLoaded', () => {
  /* 
   * 1. Loading Screen Implementation
   */
  const loader = document.getElementById('page-loader');
  if (loader) {
      const hideLoader = () => {
          loader.style.opacity = '0';
          setTimeout(() => {
              loader.style.display = 'none';
          }, 500);
      };
      if (document.readyState === 'complete') {
          hideLoader();
      } else {
          window.addEventListener('load', hideLoader);
          // Fallback just in case
          setTimeout(hideLoader, 3000);
      }
  }

  /* 
   * 2. Navbar Scroll-to-Hide & Shadow toggle
   */
  const navbar = document.getElementById('main-navbar');
  let lastScrollY = window.scrollY;
  
  window.addEventListener('scroll', () => {
      if (!navbar) return;
      
      const currentScrollY = window.scrollY;
      
      // Shadow toggle
      if (currentScrollY > 10) {
          navbar.classList.add('shadow-xl', 'border-b', 'border-white/10');
      } else {
          navbar.classList.remove('shadow-xl', 'border-b', 'border-white/10');
      }

      // Hide on scroll down, show on scroll up (beyond 100px)
      if (currentScrollY > 100) {
          if (currentScrollY > lastScrollY) {
              navbar.style.transform = 'translateY(-100%)';
          } else {
              navbar.style.transform = 'translateY(0)';
          }
      }
      
      lastScrollY = currentScrollY;
  }, { passive: true });

  /* 
   * 3. Mobile Hamburger Menu Toggle
   */
  const mobileMenuBtn = document.getElementById('mobile-menu-btn');
  const mobileMenuDrawer = document.getElementById('mobile-menu-drawer');
  
  if (mobileMenuBtn && mobileMenuDrawer) {
      mobileMenuBtn.addEventListener('click', () => {
          mobileMenuDrawer.classList.toggle('translate-x-full');
      });
  }

  /* 
   * 4. Flash Message Auto-dismiss (Toast behavior)
   */
  const toasts = document.querySelectorAll('.toast, .flashes li');
  toasts.forEach(toast => {
      // Create close button if not exists
      if (!toast.querySelector('.toast-close')) {
          const closeBtn = document.createElement('button');
          closeBtn.className = 'toast-close material-symbols-outlined ml-4';
          closeBtn.textContent = 'close';
          closeBtn.onclick = () => {
              toast.style.opacity = '0';
              setTimeout(() => toast.remove(), 300);
          };
          toast.appendChild(closeBtn);
      }
      
      // Auto dismiss after 5 seconds
      setTimeout(() => {
          if(toast && toast.parentNode) {
              toast.style.opacity = '0';
              setTimeout(() => toast.remove(), 300);
          }
      }, 5000);
  });

  /* 
   * 5. Profile Dropdown Logic
   */
  const pBtn = document.getElementById('profile-button');
  const pMenu = document.getElementById('profile-menu');
  if (pBtn && pMenu) {
      pBtn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          pMenu.classList.toggle('hidden');
      });
      document.addEventListener('click', (e) => {
          if (!pBtn.contains(e.target) && !pMenu.contains(e.target)) {
              pMenu.classList.add('hidden');
          }
      });
  }
});
