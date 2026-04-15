/* ClanDi Training — comprehension check (quiz) logic.
   HTML contract (see CLANDI_TECHNICAL_SPEC.md):
     <div class="check-wrap" data-check="N" data-correct="M"> ... </div>
   User selects an option, clicks submit, then correct/wrong feedback and
   the continue button (which unlocks the next section) are revealed. */

(function () {
  // Option click -> mark selected, activate submit button
  document.addEventListener('click', function (e) {
    var opt = e.target.closest ? e.target.closest('.check-option') : null;
    if (!opt) return;
    var wrap = opt.closest('.check-wrap');
    if (!wrap || wrap.classList.contains('answered')) return;
    wrap.querySelectorAll('.check-option').forEach(function (o) {
      o.classList.remove('selected');
    });
    opt.classList.add('selected');
    var submit = wrap.querySelector('.check-submit');
    if (submit) submit.classList.add('active');
  });

  window.submitCheck = function (n) {
    var wrap = document.querySelector('[data-check="' + n + '"]');
    if (!wrap || wrap.classList.contains('answered')) return;
    var selected = wrap.querySelector('.check-option.selected');
    if (!selected) return;

    var correctValue = wrap.dataset.correct;
    var isCorrect = selected.dataset.value === correctValue;

    wrap.classList.add('answered');
    wrap.querySelectorAll('.check-option').forEach(function (o) {
      o.classList.add('disabled');
      if (o.dataset.value === correctValue) {
        o.classList.add('correct');
        o.classList.remove('selected');
      } else if (o.classList.contains('selected') && !isCorrect) {
        o.classList.add('incorrect');
        o.classList.remove('selected');
      } else {
        o.classList.add('incorrect');
      }
    });

    var submit = wrap.querySelector('.check-submit');
    if (submit) submit.style.display = 'none';

    var feedback = wrap.querySelector(isCorrect ? '.check-feedback.right' : '.check-feedback.wrong');
    if (feedback) feedback.classList.add('show');

    var cont = wrap.querySelector('.continue-wrap');
    if (cont) cont.classList.add('show');

    if (window.ClandiModule) {
      window.ClandiModule.saveCheck(n, isCorrect);
      window.ClandiModule.updateProgress();
    }
  };
})();
