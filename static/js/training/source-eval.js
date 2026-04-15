/* ClanDi Training — source evaluation exercise.
   HTML contract:
     <div class="source-eval">
       <div class="source-item" data-answer="yes|no">
         <div class="source-item-text">...</div>
         <div class="source-buttons">
           <button class="source-btn" data-choice="yes" onclick="evalSource(this)">Reliable</button>
           <button class="source-btn" data-choice="no" onclick="evalSource(this)">Not reliable</button>
         </div>
       </div>
       <div class="source-feedback">Explanation shown after answering.</div>
       ... (more source-item + source-feedback pairs)
     </div>
   Each item is independent; the feedback element is the item's nextElementSibling. */

(function () {
  window.evalSource = function (btn) {
    if (!btn) return;
    var item = btn.closest ? btn.closest('.source-item') : null;
    if (!item || item.classList.contains('answered')) return;
    item.classList.add('answered');

    var correct = item.dataset.answer;
    var choice = btn.dataset.choice;
    var isRight = choice === correct;

    item.querySelectorAll('.source-btn').forEach(function (b) {
      b.classList.add('disabled');
      if (b.dataset.choice === correct) b.classList.add('correct');
      else if (b === btn && !isRight) b.classList.add('wrong');
    });

    var feedback = item.nextElementSibling;
    if (feedback && feedback.classList.contains('source-feedback')) {
      feedback.classList.add('show');
    }
  };
})();
