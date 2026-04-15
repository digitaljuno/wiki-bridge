/* ClanDi Training — edit verification via public Wikipedia API.
   Adds a "Verify edit" button to specific practice blocks.
   Configuration is driven by data attributes on the practice-block:
     data-verify="sandbox"  → checks User namespace (ns 2)
     data-verify="live"     → checks Article namespace (ns 0)
   When verified, the last task in the block is auto-checked. */

(function () {
  'use strict';

  function createVerifyButton(block) {
    var type = block.dataset.verify; // "sandbox" or "live"
    if (!type) return;

    var wrap = document.createElement('div');
    wrap.style.cssText = 'margin-top: 16px; display: flex; align-items: center; gap: 12px;';

    var btn = document.createElement('button');
    btn.className = 'continue-btn';
    btn.style.cssText = 'background: var(--ink, #1a1a1a); font-size: 14px; padding: 10px 20px;';
    btn.innerHTML = type === 'sandbox'
      ? 'Verify sandbox edit <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>'
      : 'Verify live edit <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';

    var status = document.createElement('span');
    status.style.cssText = 'font-size: 13px; color: var(--mid, #6b6b6b);';

    wrap.appendChild(btn);
    wrap.appendChild(status);

    // Insert before the practice-complete-msg
    var completeMsg = block.querySelector('.practice-complete-msg');
    if (completeMsg) {
      block.insertBefore(wrap, completeMsg);
    } else {
      block.appendChild(wrap);
    }

    btn.addEventListener('click', function () {
      btn.disabled = true;
      btn.style.opacity = '0.5';
      status.textContent = 'Checking Wikipedia…';

      fetch('/api/training/verify-edit?type=' + encodeURIComponent(type))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.verified) {
            status.style.color = 'var(--success, #2d7a4f)';
            if (data.dev) {
              status.textContent = 'Dev mode — auto-verified.';
            } else {
              status.textContent = 'Verified! Edit found: ' + (data.title || '');
            }
            btn.style.background = 'var(--success, #2d7a4f)';
            btn.innerHTML = 'Verified &#10003;';

            // Auto-check the last task in this block
            autoCheckLastTask(block);
          } else {
            status.style.color = 'var(--accent, #c44b2b)';
            status.textContent = data.error
              ? 'Error: ' + data.error
              : 'No edit found yet. Make an edit, then try again.';
            btn.disabled = false;
            btn.style.opacity = '1';
          }
        })
        .catch(function (err) {
          status.style.color = 'var(--accent, #c44b2b)';
          status.textContent = 'Network error. Try again.';
          btn.disabled = false;
          btn.style.opacity = '1';
        });
    });
  }

  function autoCheckLastTask(block) {
    var tasks = block.querySelectorAll('.task-item');
    if (!tasks.length) return;
    var lastTask = tasks[tasks.length - 1];
    if (!lastTask.classList.contains('done')) {
      // Simulate click to toggle it via tasks.js
      if (typeof window.toggleTask === 'function') {
        window.toggleTask(lastTask);
      } else {
        lastTask.classList.add('done');
      }
    }
  }

  // Init: find all practice blocks with data-verify
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.practice-block[data-verify]').forEach(createVerifyButton);
  });
  // Also run immediately in case DOM is already loaded
  if (document.readyState !== 'loading') {
    document.querySelectorAll('.practice-block[data-verify]').forEach(createVerifyButton);
  }
})();
