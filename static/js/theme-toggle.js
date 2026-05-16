/**
 * theme-toggle.js
 * Handles Dark/Light mode switching and persistence
 */

document.addEventListener('DOMContentLoaded', () => {
  const themeToggleBtn = document.getElementById('theme-toggle');
  const htmlElement = document.documentElement;
  
  // Icon elements if they exist
  const darkIcon = document.getElementById('theme-toggle-dark-icon');
  const lightIcon = document.getElementById('theme-toggle-light-icon');

  // Check for saved theme preference or use system preference
  const savedTheme = localStorage.getItem('theme');
  const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

  let currentTheme = 'light';

  if (savedTheme) {
      currentTheme = savedTheme;
  } else if (systemPrefersDark) {
      currentTheme = 'dark';
  }

  setTheme(currentTheme);

  // Toggle theme on button click
  if (themeToggleBtn) {
      themeToggleBtn.addEventListener('click', () => {
          currentTheme = currentTheme === 'light' ? 'dark' : 'light';
          setTheme(currentTheme);
      });
  }

  function setTheme(theme) {
      if (theme === 'dark') {
          htmlElement.setAttribute('data-theme', 'dark');
          htmlElement.classList.add('dark'); // For Tailwind compatibility if used
          if (darkIcon && lightIcon) {
              darkIcon.classList.remove('hidden');
              lightIcon.classList.add('hidden');
          }
      } else {
          htmlElement.setAttribute('data-theme', 'light');
          htmlElement.classList.remove('dark');
          if (darkIcon && lightIcon) {
              darkIcon.classList.add('hidden');
              lightIcon.classList.remove('hidden');
          }
      }
      localStorage.setItem('theme', theme);
      
      // Dispatch event in case Chart.js or other components need to forcefully rerender
      window.dispatchEvent(new Event('themeChanged'));
  }
});
