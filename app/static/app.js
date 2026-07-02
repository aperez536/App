/* app.js – TV-friendly spatial keyboard navigation + extras */
(function () {
  'use strict';

  /* ── Spatial navigation ─────────────────────────────────── */
  function focusables() {
    return Array.from(
      document.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), [tabindex="0"]'
      )
    ).filter(function (el) {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    });
  }

  function center(el) {
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, r: r };
  }

  function navigate(dir) {
    const active = document.activeElement;
    if (!active || active === document.body) return;

    const ac = center(active);
    let best = null;
    let bestScore = Infinity;

    focusables().forEach(function (el) {
      if (el === active) return;
      const c = center(el);
      let inDir = false;
      switch (dir) {
        case 'up':    inDir = c.y < ac.y - 8; break;
        case 'down':  inDir = c.y > ac.y + 8; break;
        case 'left':  inDir = c.x < ac.x - 8; break;
        case 'right': inDir = c.x > ac.x + 8; break;
      }
      if (!inDir) return;

      const primary = (dir === 'up' || dir === 'down')
        ? Math.abs(c.y - ac.y)
        : Math.abs(c.x - ac.x);
      const ortho = (dir === 'up' || dir === 'down')
        ? Math.abs(c.x - ac.x)
        : Math.abs(c.y - ac.y);
      const score = primary + ortho * 1.8;

      if (score < bestScore) { bestScore = score; best = el; }
    });

    if (best) {
      best.focus();
      best.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  /* ── Keyboard handler ───────────────────────────────────── */
  document.addEventListener('keydown', function (e) {
    const tag = document.activeElement ? document.activeElement.tagName : '';
    const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';

    switch (e.key) {
      case 'ArrowUp':
        if (!isInput) { e.preventDefault(); navigate('up'); }
        break;
      case 'ArrowDown':
        if (!isInput) { e.preventDefault(); navigate('down'); }
        break;
      case 'ArrowLeft':
        if (!isInput) { e.preventDefault(); navigate('left'); }
        break;
      case 'ArrowRight':
        if (!isInput) { e.preventDefault(); navigate('right'); }
        break;
      case 'Enter':
        if (document.activeElement && document.activeElement !== document.body) {
          document.activeElement.click();
        }
        break;
      case 'Escape':
      case 'Backspace':
        if (!isInput) {
          e.preventDefault();
          goBack();
        }
        break;
    }
  });

/* Samsung TV remote "Return" key.
     Tizen OS fires keyCode 10009 for the physical Back button and does not
     map it to a standard e.key value, so keyCode is intentionally used here.
     We handle this inside the same switch fall-through when possible,
     but keyCode cannot be matched in a switch on e.key, so it stays here. */
  document.addEventListener('keydown', function (e) {
    if (e.keyCode === 10009) { e.preventDefault(); goBack(); }
  });

  function goBack() {
    const back = document.querySelector('[data-back]');
    if (back) { back.click(); } else { history.back(); }
  }

  /* ── Image fullscreen toggle ────────────────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    const imgBox = document.querySelector('.viewer-image-box');
    if (imgBox) {
      imgBox.addEventListener('click', function () {
        if (!document.fullscreenElement) {
          imgBox.requestFullscreen && imgBox.requestFullscreen();
          imgBox.classList.add('fullscreen-mode');
        } else {
          document.exitFullscreen && document.exitFullscreen();
          imgBox.classList.remove('fullscreen-mode');
        }
      });

      document.addEventListener('fullscreenchange', function () {
        if (!document.fullscreenElement) {
          imgBox.classList.remove('fullscreen-mode');
        }
      });
    }

    /* Auto-focus first focusable card on page load (TV UX).
       Skip if any interactive element already has focus. */
    const first = document.querySelector('.media-card, .section-card, .folder-card');
    if (first && document.activeElement === document.body) {
      first.focus();
    }
  });
})();
