/* ClanDi Training — core module runtime.
   Section unlocking, progress bar, progress/completion API calls.
   Reads module_id and total_sections from #moduleRoot data attributes. */

(function () {
  var root = document.getElementById('moduleRoot');
  if (!root) return;

  var MODULE_ID = parseInt(root.dataset.moduleId, 10);
  var TOTAL_SECTIONS = parseInt(root.dataset.totalSections, 10);
  var LOGGED_IN = root.dataset.loggedIn === '1';

  window.ClandiModule = {
    moduleId: MODULE_ID,
    totalSections: TOTAL_SECTIONS,
    loggedIn: LOGGED_IN,
  };

  // ---- API helpers (fire-and-forget, non-blocking) ----
  function apiPost(path, body) {
    if (!LOGGED_IN) return Promise.resolve(null);
    return fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      credentials: 'same-origin',
    }).then(function (r) { return r.json().catch(function () { return null; }); })
      .catch(function () { return null; });
  }

  window.ClandiModule.saveProgress = function (sectionIndex) {
    return apiPost('/api/training/progress', {
      module_id: MODULE_ID,
      section_index: sectionIndex,
      total_sections: TOTAL_SECTIONS,
    });
  };

  window.ClandiModule.saveCheck = function (checkId, correct) {
    return apiPost('/api/training/check', {
      module_id: MODULE_ID,
      check_id: checkId,
      correct: !!correct,
    });
  };

  window.ClandiModule.saveTask = function (practiceId, taskIndex, completed) {
    return apiPost('/api/training/task', {
      module_id: MODULE_ID,
      practice_id: String(practiceId),
      task_index: taskIndex,
      completed: !!completed,
    });
  };

  window.ClandiModule.completeModule = function () {
    return apiPost('/api/training/complete', { module_id: MODULE_ID });
  };

  // ---- Progress bar ----
  function updateProgress(complete) {
    var fill = document.getElementById('progressFill');
    if (!fill) return;
    if (complete) { fill.style.width = '100%'; return; }
    var visible = document.querySelectorAll('.section.visible').length;
    var pct = Math.round((visible / TOTAL_SECTIONS) * 100);
    fill.style.width = pct + '%';
  }
  window.ClandiModule.updateProgress = updateProgress;

  // ---- Section unlocking ----
  window.unlockNext = function (n) {
    var sec = document.querySelector('[data-section="' + n + '"]');
    var div = document.getElementById('div-' + n);
    if (sec) {
      sec.classList.remove('locked');
      if (div) div.classList.add('show');
      // Stagger reveal: two animation frames for smoother fade-up
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          sec.classList.add('visible');
          sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
          updateProgress();
        });
      });
    } else {
      updateProgress();
    }
    window.ClandiModule.saveProgress(n);
  };

  // ---- Module completion screen ----
  window.showCompletion = function () {
    var c = document.getElementById('completion');
    if (c) {
      c.classList.add('show');
      c.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    updateProgress(true);
    window.ClandiModule.completeModule().then(function (res) {
      // Optional: redirect or update UI with next module link
      if (res && res.next_module) {
        var nextLink = document.getElementById('next-module-link');
        if (nextLink) nextLink.href = '/training/module/' + res.next_module;
      }
    });
  };

  // ---- Initial paint ----
  // Mark the first section as having been reached (progress 1/total)
  updateProgress();
  if (LOGGED_IN) window.ClandiModule.saveProgress(1);
})();
