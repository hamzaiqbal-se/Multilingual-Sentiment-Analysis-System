/**
 * animations.js
 * Initialization script for animation libraries (AOS, GSAP, etc.)
 */

document.addEventListener('DOMContentLoaded', () => {
  // Initialize AOS (Animate On Scroll) if loaded
  if (typeof AOS !== 'undefined') {
      AOS.init({
          offset: 120, // offset (in px) from the original trigger point
          delay: 0, // values from 0 to 3000, with step 50ms
          duration: 600, // values from 0 to 3000, with step 50ms
          easing: 'ease-out-cubic', // default easing for AOS animations
          once: true, // whether animation should happen only once - while scrolling down
          mirror: false, // whether elements should animate out while scrolling past them
          anchorPlacement: 'top-bottom', // defines which position of the element regarding to window should trigger the animation
      });
  }

  // Common GSAP integrations could jump in here.
  // For now, our CSS keyframes handle micro-interactions, 
  // and AOS handles scroll entry.
});
