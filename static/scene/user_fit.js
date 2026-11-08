/* SPDX-License-Identifier: MIT */
/* App-owned user-block fitting: preserve the complete text and its type floor. */
window.__ready = window.__ready.then(() => {
  for (const el of document.querySelectorAll('[data-fit]')) {
    let size = parseFloat(getComputedStyle(el).fontSize);
    while (size > 44 && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)) {
      el.style.fontSize = `${size = Math.max(44, size - 1)}px`;
    }
  }
});
