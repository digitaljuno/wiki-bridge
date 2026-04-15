/* ClanDi Training — task checklist logic.
   HTML contract:
     <div class="practice-block" data-practice="P">
       <div class="task-list">
         <div class="task-item" onclick="toggleTask(this)">
           <div class="task-checkbox"><svg class="task-checkmark" ... /></div>
           <div class="task-text">...</div>
         </div>
         ...
       </div>
       <div class="practice-complete-msg">...</div>
     </div>
   Click toggles .done; when every item in the block is done, the completion message shows. */

(function () {
  window.toggleTask = function (el) {
    if (!el || !el.classList) return;
    el.classList.toggle('done');
    var completed = el.classList.contains('done');

    var block = el.closest ? el.closest('.practice-block') : null;
    if (!block) return;

    // Find the index of this item within its block
    var items = block.querySelectorAll('.task-item');
    var taskIndex = -1;
    for (var i = 0; i < items.length; i++) {
      if (items[i] === el) { taskIndex = i; break; }
    }
    var practiceId = block.dataset.practice || '1';

    // Persist to API
    if (window.ClandiModule) {
      window.ClandiModule.saveTask(practiceId, taskIndex, completed);
    }

    // Show/hide "all done" completion message
    var done = block.querySelectorAll('.task-item.done').length;
    var total = items.length;
    var msg = block.querySelector('.practice-complete-msg');
    if (msg) {
      if (done === total && total > 0) msg.classList.add('show');
      else msg.classList.remove('show');
    }
  };
})();
